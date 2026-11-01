import asyncio
import json
import re
from datetime import timedelta

import httpx
import pytest

from app.config import Settings
from app.db import Database
from app.external import ExternalClient
from app.github_client import GitHubClient
from app.service import Service
from tests.test_collection import NOW, external_handler, github_handler


def make_service(handler=github_handler, external=external_handler, **settings):
    calls = []
    def track(request):
        calls.append(request)
        if handler is github_handler and request.url.path == '/repos/owner/repo':
            return httpx.Response(200, json={'full_name': 'owner/repo', 'has_issues': True, 'stargazers_count': 100, 'license': {'spdx_id': 'MIT'}})
        return handler(request)
    service = Service(Database(':memory:'), GitHubClient(transport=httpx.MockTransport(track)), ExternalClient(httpx.MockTransport(external)), Settings(**settings), clock=lambda: NOW)
    return service, calls


async def close(service):
    await service.github.close()
    await service.external.close()
    service.db.close()


async def test_cache_weights_refresh_ttl_and_history():
    service, calls = make_service()
    first = await service.analyze('old/name')
    count = len(calls)
    custom = await service.analyze('old/name', {'activity': 100})
    assert custom['from_cache'] and len(calls) == count
    assert custom['weights'] != first['weights'] and custom['score'] != first['score']
    assert len(service.history('old/name')) == 1
    refreshed = await service.analyze('old/name', refresh=True)
    # Canonical path on a subsequent fresh collection.
    assert not refreshed['from_cache'] and len(service.history('old/name')) == 2
    service.clock = lambda: NOW + timedelta(hours=6)
    await service.analyze('old/name')
    assert len(service.history('old/name')) == 3
    await close(service)


async def test_lock_prevents_duplicate_collection_and_compare():
    service, calls = make_service()
    results = await asyncio.gather(*(service.analyze('old/name') for _ in range(5)))
    assert sum(not r['from_cache'] for r in results) == 1
    assert len(service.history('old/name')) == 1
    compared = await service.compare(['old/name', 'old/name'])
    assert compared['sensitivity']['trials'] == 300
    assert (await service.compare(['old/name']))['sensitivity'] is None
    await close(service)


@pytest.mark.parametrize('severity', ['HIGH', 'CRITICAL'])
async def test_background_scan_persistence_versions_sorting_and_truncation(severity):
    versions = []
    def ext(request):
        if request.url.host == 'registry.npmjs.org':
            name = request.url.path.split('/')[1]
            if name == 'missing':
                return httpx.Response(404)
            if name == 'unlinked':
                return httpx.Response(200, json={'version': '1'})
            return httpx.Response(200, json={'version': '3.0', 'repository': 'https://github.com/owner/repo'})
        if request.url.host == 'api.osv.dev':
            payload = json.loads(request.content)
            versions.append(payload['version'])
            return httpx.Response(200, json={'vulns': [{'id': 'GHSA-bad', 'database_specific': {'severity': severity}}] if payload['version'] == '1.0.0' else []})
        return httpx.Response(404)
    service, calls = make_service(external=ext, max_scan_deps=4)
    content = json.dumps({'dependencies': {'vulnerable': '^1.0.0', 'missing': '1', 'unlinked': '1', 'latest': '*', 'extra': '1'}})
    started = service.start_scan('package.json', content)
    assert re.fullmatch(r'[0-9a-fA-F]{12}', started['job_id'])
    assert started['total'] == 4 and started['truncated']
    assert service.get_scan(started['job_id'])['status'] == 'running'
    tasks = list(service.tasks)
    await asyncio.gather(*tasks)
    job = service.get_scan(started['job_id'])
    assert job['status'] == 'done' and job['done'] == job['total'] == 4
    assert job['rows'][0]['name'] == 'vulnerable' and job['rows'][0]['risk'] in ('High', 'Medium')
    assert job['rows'][0]['vuln_ids'] == ['GHSA-bad'] and 'Declared version' in job['rows'][0]['note']
    assert {'not_found', 'no_repo', 'done'} == {r['status'] for r in job['rows']}
    rows_by_name = {row['name']: row for row in job['rows']}
    assert rows_by_name['missing']['note'] == 'Package not found in the registry'
    assert rows_by_name['unlinked']['note'] == 'No GitHub repository linked from the registry'
    assert rows_by_name['vulnerable']['high_vuln_count'] == 1
    assert all(row['score'] is None for row in job['rows'][-2:])
    assert '1.0.0' in versions and '3.0' in versions
    assert service.get_scan('unknown') is None
    await close(service)


async def test_rate_limit_skips_remaining_and_reports_message():
    def handler(request):
        return httpx.Response(429)
    looked_up = []
    def ext(request):
        looked_up.append(request)
        return httpx.Response(200, json={'version': '1', 'repository': 'https://github.com/a/b'})
    service, _ = make_service(handler, ext)
    started = service.start_scan('package.json', json.dumps({'dependencies': {f'p{i}': '1' for i in range(12)}}))
    await asyncio.gather(*list(service.tasks))
    job = service.get_scan(started['job_id'])
    assert job['status'] == 'done' and job['done'] == 12 and 'rate limit' in job['message']
    assert all(row['status'] == 'skipped' for row in job['rows'])
    assert len(looked_up) <= 4
    await close(service)


async def test_job_exception_is_persisted_and_validation():
    service, _ = make_service()
    async def broken(*args):
        raise RuntimeError('example failure')
    service.external.registry = broken
    started = service.start_scan('package.json', '{"dependencies": {"a": "1"}}')
    await asyncio.gather(*list(service.tasks))
    assert service.get_scan(started['job_id'])['status'] == 'failed'
    assert 'example failure' in service.get_scan(started['job_id'])['message']
    with pytest.raises(ValueError, match='No dependencies'):
        service.start_scan('package.json', '{}')
    await close(service)


async def test_four_worker_limit_and_persisted_progress(monkeypatch):
    active, peak = 0, 0
    async def external(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return httpx.Response(404)
    service, _ = make_service(external=external)
    states = []
    original = service.db.save_scan
    def record(*args):
        original(*args)
        states.append((args[2], args[4]))
    monkeypatch.setattr(service.db, 'save_scan', record)
    started = service.start_scan('requirements.txt', '\n'.join(f'p{i}==1' for i in range(9)))
    await asyncio.gather(*list(service.tasks))
    assert peak == 4
    assert states == [('running', i) for i in range(10)] + [('done', 9)]
    assert service.get_scan(started['job_id'])['done'] == 9
    await close(service)
