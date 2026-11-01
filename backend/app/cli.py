"""Dependency risk gate: python -m app.cli MANIFEST."""
import argparse
import asyncio
from pathlib import Path
import sys

from app.config import Settings
from app.db import Database
from app.external import ExternalClient
from app.github_client import GitHubClient
from app.service import Service


async def run(args, service, stdout=None, stderr=None):
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    try:
        content = Path(args.manifest).read_text(encoding='utf-8')
        started = service.start_scan(Path(args.manifest).name, content, args.include_dev)
        await asyncio.gather(*list(service.tasks))
        job = service.get_scan(started['job_id'])
    except (OSError, ValueError) as exc:
        print(f'Unable to scan manifest: {exc}', file=stderr)
        return 1
    if job['message']:
        print(job['message'], file=stderr)
    if job['status'] == 'failed':
        return 1
    print(f'{"Package":<32} {"Score":>7} {"Risk":<12} Repository', file=stdout)
    levels = {'Low': 0, 'Medium': 1, 'High': 2}
    failed = False
    for row in job['rows']:
        value = f"{row['score']:.1f}" if row['score'] is not None else 'n/a'
        print(f"{row['name']:<32} {value:>7} {row['risk'] or 'Not scored':<12} {row['repo'] or '-'}", file=stdout)
        if row['risk'] and levels[row['risk']] > levels[args.max_risk.title()]:
            failed = True
        if row['score'] is not None and row['score'] < args.min_score:
            failed = True
    return int(failed)


async def _main(args):
    settings = Settings()
    db = Database(settings.db_path)
    github, external = GitHubClient(settings.github_token), ExternalClient()
    try:
        return await run(args, Service(db, github, external, settings))
    finally:
        await github.close()
        await external.close()
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check dependency repository health and risk.')
    parser.add_argument('manifest')
    parser.add_argument('--max-risk', choices=['low', 'medium', 'high'], default='medium')
    parser.add_argument('--min-score', type=float, default=0)
    parser.add_argument('--include-dev', action='store_true')
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == '__main__':
    raise SystemExit(main())
