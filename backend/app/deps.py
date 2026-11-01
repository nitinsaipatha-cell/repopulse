"""Manifest parsing and bounded dependency scans."""
import asyncio
import json
import re

from app.github_client import RateLimited

_VERSION = re.compile(r'(?<![A-Za-z0-9])\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?')


def base_version(spec):
    if not isinstance(spec, str):
        return None
    if '/' in spec or re.search(r'(?:[a-z]+://|git(?:\+|:|@)|file:|link:|workspace:|npm:|github:)', spec, re.I):
        return None
    match = _VERSION.search(spec)
    return match.group() if match else None


def parse_package_json(content, include_dev=False):
    try:
        manifest = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid package.json. Upload valid JSON.') from exc
    if not isinstance(manifest, dict):
        raise ValueError('Invalid package.json. Expected a JSON object.')
    rows = []
    seen = set()
    for field, dev in [('dependencies', False), ('devDependencies', True)]:
        if dev and not include_dev:
            continue
        dependencies = manifest.get(field, {})
        if not isinstance(dependencies, dict):
            raise ValueError(f'Invalid package.json. {field} must be an object.')
        for name, spec in dependencies.items():
            if not name or not isinstance(spec, str):
                raise ValueError('Invalid package.json. Dependency names and versions must be strings.')
            if name in seen:
                continue
            seen.add(name)
            rows.append({'name': name, 'ecosystem': 'npm', 'spec': spec, 'dev': dev, 'declared_version': base_version(spec)})
    return rows


def parse_requirements(content):
    rows, seen = [], set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '-', 'http', 'git+', '.')):
            continue
        line = line.split('#', 1)[0].split(';', 1)[0].strip()
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]+\])?\s*((?:(?:===|==|~=|!=|<=|>=|<|>)\s*[^\s,]+\s*,?\s*)*)', line)
        if not match:
            continue
        name, spec = match.groups()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append({'name': name, 'ecosystem': 'PyPI', 'spec': spec.strip(), 'dev': False, 'declared_version': base_version(spec)})
    return rows


def parse_manifest(filename, content, include_dev=False):
    name = filename.lower()
    if name.endswith('.json'):
        return parse_package_json(content, include_dev)
    if name.endswith('.txt') or 'requirements' in name:
        return parse_requirements(content)
    raise ValueError('Unsupported file. Upload a package.json or requirements.txt.')


def sort_rows(rows):
    return sorted(rows, key=lambda row: (row['score'] is None, {'High': 0, 'Medium': 1, 'Low': 2}.get(row['risk'], 3), row['score'] if row['score'] is not None else 0))


async def scan_dependencies(packages, service, progress=None):
    """Four workers claim work only while no rate limit has been observed."""
    rows, index, message = [], 0, None

    async def worker():
        nonlocal index, message
        while index < len(packages):
            package = packages[index]
            index += 1
            row = {**package, 'latest': None, 'status': 'skipped', 'repo': None, 'score': None, 'risk': None, 'categories': {}, 'vuln_count': 0, 'high_vuln_count': 0, 'vuln_ids': [], 'concerns': [], 'note': None}
            if message:
                row['note'] = message
            else:
                try:
                    found = await service.external.registry(package['ecosystem'], package['name'])
                    if found is None:
                        row.update(status='not_found', note='Package not found in the registry')
                    else:
                        row['latest'] = found['version']
                        row['repo'] = found['repo']
                        if not found['repo']:
                            row.update(status='no_repo', note='No GitHub repository linked from the registry')
                        else:
                            analysis = await service.analyze(found['repo'])
                            vulns = await service.external.vulnerabilities(package['ecosystem'], package['name'], package['declared_version'] or found['version'])
                            high = sum((v.get('severity') or '').upper() in {'HIGH', 'CRITICAL'} for v in vulns)
                            risk = analysis['risk']
                            if high and risk == 'Low':
                                risk = 'Medium'
                            row.update(status='done', repo=analysis['full_name'], score=analysis['score'], risk=risk, categories=analysis['category_scores'], vuln_count=len(vulns), high_vuln_count=high, vuln_ids=[v['id'] for v in vulns][:5], concerns=analysis['concerns'][:2] + analysis['overrides'][:1], note='Declared version has known vulnerabilities' if vulns else None)
                except RateLimited as exc:
                    message = str(exc)
                    row['note'] = message
            rows.append(row)
            if progress:
                await progress(sort_rows(rows), message)
    workers = [asyncio.create_task(worker()) for _ in range(4)]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    return sort_rows(rows), message
