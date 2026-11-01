import asyncio
import csv
from io import StringIO
import json

import httpx
import pytest

from app.config import Settings
from app.db import Database
from app.external import ExternalClient
from app.github_client import GitHubClient
from app.main import create_app
from app.service import Service
from tests.test_collection import NOW, github_handler, external_handler


def github_response(request):
    path = request.url.path
    if path == '/rate_limit':
        return httpx.Response(200, json={'resources': {'core': {'limit': 60, 'remaining': 55, 'reset': 123}}})
    for name, status in [('missing', 404), ('limited', 429), ('broken', 500)]:
        if path == f'/repos/owner/{name}':
            return httpx.Response(status)
    if path in ('/repos/owner/repo', '/repos/owner/second', '/repos/owner/archived'):
        return httpx.Response(200, json={'full_name': path.removeprefix('/repos/'), 'has_issues': True,
            'archived': path.endswith('/archived'), 'stargazers_count': 100, 'license': {'spdx_id': 'MIT'}})
    path = path.replace('/repos/owner/second/', '/repos/owner/repo/').replace('/repos/owner/archived/', '/repos/owner/repo/')
    mapped = httpx.Request(request.method, request.url.copy_with(path=path))
    return github_handler(mapped)


def external_response(request):
    if request.url.host == 'registry.npmjs.org':
        name = request.url.path.split('/')[1]
        if name == 'missing':
            return httpx.Response(404)
        if name == 'unlinked':
            return httpx.Response(200, json={'version': '1'})
        if name in ('vulnerable', 'dev-only'):
            return httpx.Response(200, json={'version': '2', 'repository': 'https://github.com/owner/repo'})
    return external_handler(request)


@pytest.fixture
async def api():
    calls = []
    def handler(request):
        calls.append(request)
        return github_response(request)
    settings = Settings(rate_limit_per_min=0, github_token='')
    service = Service(Database(':memory:'), GitHubClient(transport=httpx.MockTransport(handler)),
        ExternalClient(httpx.MockTransport(external_response)), settings, clock=lambda: NOW)
    app = create_app(service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, service, calls
    for task in list(service.tasks):
        task.cancel()
    await asyncio.gather(*list(service.tasks), return_exceptions=True)
    await service.github.close()
    await service.external.close()
    service.db.close()


async def test_analyze_cached_weights_refresh_history(api):
    client, _, calls = api
    first = (await client.get('/api/analyze/owner/repo')).json()
    assert first['full_name'] == 'owner/repo' and first['from_cache'] is False
    assert all(key in first for key in ('score', 'risk', 'weights', 'categories', 'mature', 'adjustments', 'overrides', 'concerns', 'strengths', 'package', 'scorecard', 'facts', 'fetched_at'))
    count = len(calls)
    custom = (await client.get('/api/analyze/owner/repo?activity=100')).json()
    assert custom['from_cache'] and custom['score'] != first['score'] and len(calls) == count
    assert len((await client.get('/api/history/owner/repo')).json()) == 1
    refreshed = await client.get('/api/analyze/owner/repo?refresh=true')
    assert not refreshed.json()['from_cache']
    history = (await client.get('/api/history/owner/repo')).json()
    assert len(history) == 2 and [r['ts'] for r in history] == sorted(r['ts'] for r in history)


async def test_archived_and_error_mapping(api):
    client, _, _ = api
    assert (await client.get('/api/analyze/owner/archived')).json()['risk'] == 'High'
    for name, status, detail in [('missing', 404, 'Repository not found.'), ('limited', 429, 'GitHub API rate limit reached.'), ('broken', 502, 'GitHub request failed')]:
        response = await client.get(f'/api/analyze/owner/{name}')
        assert response.status_code == status and detail in response.json()['detail']


@pytest.mark.parametrize('route', ['/api/analyze/owner/repo', '/api/compare?repos=owner/repo,owner/second', '/api/report/owner/repo.pdf', '/api/report/owner/repo.csv'])
@pytest.mark.parametrize('weight', ['activity', 'bus_factor', 'responsiveness', 'documentation', 'security'])
async def test_weight_bounds(api, route, weight):
    client, _, calls = api
    for value in ('-1', '101', 'nan', 'inf'):
        separator = '&' if '?' in route else '?'
        assert (await client.get(f'{route}{separator}{weight}={value}')).status_code == 422
    assert not calls


async def test_invalid_reference_and_compare_validation(api):
    client, _, calls = api
    assert (await client.get('/api/analyze/bad%20owner/repo')).status_code == 422
    for refs in ('owner/repo', 'owner/repo,OWNER/REPO', 'bad,owner/repo', ',owner/repo', 'a/b,c/d,e/f,g/h,i/j'):
        assert (await client.get('/api/compare', params={'repos': refs})).status_code == 422
    assert not calls
    compared = (await client.get('/api/compare?repos=owner/repo,owner/second')).json()
    assert len(compared['repos']) == 2 and compared['sensitivity']['trials'] == 300
    # Section 10 requires 2-4 over HTTP; section 14's no-sensitivity case is
    # covered by the single-repository service comparison test.


async def test_badge_and_reports_over_http(api):
    client, _, _ = api
    response = await client.get('/api/badge/owner/repo.svg')
    assert response.status_code == 200 and 'repo health' in response.text
    assert response.headers['cache-control'] == 'public, max-age=3600'
    assert response.headers['content-type'] == 'image/svg+xml'
    for name in ('missing', 'limited', 'broken'):
        response = await client.get(f'/api/badge/owner/{name}.svg')
        assert response.status_code == 200 and 'unknown' in response.text
        assert '#6b7b82' in response.text
        assert response.headers['content-type'] == 'image/svg+xml'
        assert response.headers['cache-control'] == 'public, max-age=3600'
    pdf = await client.get('/api/report/owner/repo.pdf')
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-')
    assert pdf.headers['content-type'] == 'application/pdf' and 'attachment' in pdf.headers['content-disposition']
    response = await client.get('/api/report/owner/repo.csv')
    rows = list(csv.DictReader(StringIO(response.text)))
    assert response.status_code == 200 and rows and rows[0]['repository'] == 'owner/repo'
    assert 'commits_90d' in response.text


async def test_full_scan_poll_and_export(api):
    client, service, _ = api
    response = await client.post('/api/scan', json={'filename': 'package.json', 'content': json.dumps({'dependencies': {'vulnerable': '^1.2.3', 'missing': '1', 'unlinked': '*'}, 'devDependencies': {'dev-only': '1'}}), 'include_dev': True})
    assert response.status_code == 200
    job_id = response.json()['job_id']
    await asyncio.gather(*list(service.tasks))
    job = (await client.get(f'/api/scan/{job_id}')).json()
    assert job['status'] == 'done' and job['done'] == job['total'] == 4
    assert job['filename'] == 'package.json' and not job['truncated']
    rows = {r['name']: r for r in job['rows']}
    assert rows['vulnerable']['vuln_count'] == 1 and rows['vulnerable']['risk'] in ('Medium', 'High')
    assert rows['missing']['status'] == 'not_found' and rows['unlinked']['status'] == 'no_repo'
    response = await client.get(f'/api/scan/{job_id}/csv')
    assert response.status_code == 200 and len(list(csv.DictReader(StringIO(response.text)))) == 4
    assert (await client.get('/api/scan/unknown')).status_code == 404
    assert (await client.get('/api/scan/unknown/csv')).status_code == 404


@pytest.mark.parametrize('body', [{}, {'filename': 'x.yaml', 'content': 'a'}, {'filename': 'package.json', 'content': '{bad'}, {'filename': 'package.json', 'content': '{}'}, {'filename': 'requirements.txt', 'content': '#empty'}])
async def test_scan_validation(api, body):
    assert (await api[0].post('/api/scan', json=body)).status_code == 422


async def test_status_config_and_unavailable_status(api):
    client, service, _ = api
    config = (await client.get('/api/config')).json()
    assert [c['key'] for c in config['categories']] == ['activity', 'bus_factor', 'responsiveness', 'documentation', 'security']
    assert config['default_weights']['activity'] == 25 and config['risk_thresholds']['Low'] == 80
    status = (await client.get('/api/status')).json()
    assert status == {'ok': True, 'token_configured': False, 'rate_limit': {'limit': 60, 'remaining': 55, 'reset': 123}}
    from app.github_client import GitHubError
    async def failed(*args):
        raise GitHubError('offline')
    service.github.get = failed
    assert (await client.get('/api/status')).json()['rate_limit'] is None


async def test_rate_limiter_exemptions_ip_isolation_cors_and_expiry(api):
    _, service, _ = api
    now = [0]
    app = create_app(service, Settings(rate_limit_per_min=1, cors_origins=['http://localhost:5173']), rate_clock=lambda: now[0])
    headers = {'Origin': 'http://localhost:5173', 'X-Forwarded-For': '10.0.0.1, proxy'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('socket-ip', 10)), base_url='http://test') as client:
        assert (await client.get('/api/analyze/owner/repo', headers=headers)).status_code == 200
        response = await client.get('/api/compare?repos=owner/repo,owner/second', headers=headers)
        assert response.status_code == 429
        assert response.json()['detail'] == 'Too many requests from your address. Please wait a minute and try again.'
        assert response.headers['retry-after'] == '60'
        assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
        for path in ('/api/report/owner/repo.pdf', '/api/report/owner/repo.csv'):
            assert (await client.get(path, headers=headers)).status_code == 429
        assert (await client.post('/api/scan', headers=headers, json={})).status_code == 429
        for path in ('/api/status', '/api/config', '/api/history/owner/repo', '/api/badge/owner/repo.svg', '/api/scan/unknown', '/api/scan/unknown/csv'):
            assert (await client.get(path, headers=headers)).status_code != 429
        assert (await client.get('/api/analyze/owner/repo', headers={'X-Forwarded-For': '10.0.0.2, proxy'})).status_code == 200
        assert (await client.get('/api/analyze/owner/repo')).status_code == 200  # socket fallback
        assert (await client.get('/api/analyze/owner/repo')).status_code == 429
        preflight = await client.options('/api/scan', headers={**headers, 'Access-Control-Request-Method': 'POST'})
        assert preflight.status_code == 200
        now[0] = 60
        assert (await client.get('/api/analyze/owner/repo', headers=headers)).status_code == 200


async def test_all_registered_routes_live_under_api(api):
    app = create_app(api[1])
    assert app.routes
    for route in app.routes:
        assert route.path.startswith('/api'), route.path
    paths = {route.path for route in app.routes}
    assert {'/api/docs', '/api/openapi.json', '/api/docs/oauth2-redirect'} <= paths


async def test_zero_rate_limit_disables_limiter(api, monkeypatch):
    monkeypatch.setenv('RATE_LIMIT_PER_MIN', '0')
    settings = Settings()
    assert settings.rate_limit_per_min == 0
    app = create_app(api[1], settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for _ in range(100):
            response = await client.get('/api/analyze/owner/repo')
            assert response.status_code == 200
