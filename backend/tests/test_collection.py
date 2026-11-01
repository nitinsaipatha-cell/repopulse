import base64
import json
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx
import pytest

from app.collectors import collect
from app.external import ExternalClient
from app.github_client import GitHubClient, RateLimited, RepoNotFound

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def external_handler(request):
    path = unquote(request.url.path)
    if request.url.host == 'registry.npmjs.org':
        if path == '/@scope/package/latest':
            return httpx.Response(200, json={'version': '1.2.3', 'repository': {'url': 'git+https://github.com/Owner/Repo.git'}})
        if path == '/repo/latest':
            return httpx.Response(200, json={'version': '2.0', 'homepage': 'https://github.com/owner/repo'})
    if request.url.host == 'pypi.org':
        return httpx.Response(200, json={'info': {'version': '3.0', 'project_urls': {'Source': 'https://github.com/owner/repo'}, 'home_page': 'https://github.com/wrong/project'}})
    if request.url.host == 'api.osv.dev':
        payload = json.loads(request.content)
        assert payload['package']['ecosystem'] in ('npm', 'PyPI')
        return httpx.Response(200, json={'vulns': [{'id': 'GHSA-1', 'database_specific': {'severity': 'critical'}, 'summary': 'a' * 150}, {'id': 'withdrawn', 'withdrawn': '2026-01-01'}]})
    if request.url.host == 'api.securityscorecards.dev':
        return httpx.Response(200, json={'score': 8.1, 'date': '2026-01-01', 'checks': [{'name': 'CI-Tests', 'score': 9, 'reason': 'ignored'}]})
    return httpx.Response(404)


async def test_external_registries_osv_and_scorecard():
    client = ExternalClient(httpx.MockTransport(external_handler))
    npm = await client.registry('npm', '@scope/package')
    assert npm['repo'] == 'Owner/Repo' and npm['version'] == '1.2.3'
    pypi = await client.registry('PyPI', 'repo')
    assert pypi['repo'] == 'owner/repo' and pypi['version'] == '3.0'
    vulns = await client.vulnerabilities('npm', '@scope/package', '1.2.3')
    assert len(vulns) == 1 and vulns[0]['severity'] == 'CRITICAL' and len(vulns[0]['summary']) == 140
    assert await client.scorecard('owner/repo') == {'score': 8.1, 'date': '2026-01-01', 'checks': [{'name': 'CI-Tests', 'score': 9}]}
    await client.close()


async def test_external_failure_is_tolerated():
    def fail(request):
        raise httpx.ConnectError('offline', request=request)
    client = ExternalClient(httpx.MockTransport(fail))
    assert await client.registry('npm', 'a') is None
    assert await client.vulnerabilities('npm', 'a', '1') == []
    assert await client.scorecard('a/b') is None
    await client.close()


def github_handler(request):
    path = request.url.path
    if path == '/repos/old/name':
        return httpx.Response(200, json={'full_name': 'owner/repo', 'has_issues': True, 'stargazers_count': 100, 'license': {'spdx_id': 'MIT'}})
    root = '/repos/owner/repo'
    data = {
        root + '/commits': [{'author': {'login': 'alice'}, 'commit': {'committer': {'date': '2026-10-30T00:00:00Z'}}}, {'author': None, 'commit': {'author': {'name': 'Bob'}, 'committer': {'date': '2026-10-29T00:00:00Z'}}}],
        root + '/contributors': [{'login': 'alice', 'contributions': 20}],
        root + '/releases': [{'published_at': '2026-09-01T00:00:00Z'}],
        root + '/issues': [{'number': 1, 'created_at': '2026-10-01T00:00:00Z', 'closed_at': None, 'comments': 3, 'user': {'login': 'alice'}}, {'number': 2, 'created_at': '2026-10-01T00:00:00Z', 'closed_at': None, 'comments': 0, 'user': {'login': 'bob'}}, {'number': 3, 'pull_request': {}}],
        root + '/issues/1/comments': [{'user': {'login': 'alice', 'type': 'User'}}, {'user': {'login': 'bot', 'type': 'Bot'}}, {'user': {'login': 'bob', 'type': 'User'}, 'created_at': '2026-10-02T00:00:00Z'}],
        root + '/pulls': [{'created_at': '2026-10-01', 'merged_at': '2026-10-02'}, {'merged_at': None}],
        root + '/community/profile': {'files': {'license': {'name': 'MIT'}, 'contributing': None}},
        root + '/readme': {'size': 1200},
        root + '/contents': [{'name': 'package.json'}, {'name': 'docs'}],
        root + '/contents/.github': [{'name': 'workflows'}],
        root + '/contents/package.json': {'encoding': 'base64', 'content': base64.b64encode(b'{"name":"@scope/package"}').decode()},
    }
    return httpx.Response(200, json=data[path]) if path in data else httpx.Response(404)


async def test_full_collection_and_canonical_name():
    gh = GitHubClient(transport=httpx.MockTransport(github_handler))
    external = ExternalClient(httpx.MockTransport(external_handler))
    raw = await collect(gh, external, 'old', 'name', NOW)
    assert set(raw) == {'fetched_at', 'repo', 'commits_90d', 'commits_capped', 'commit_authors_90d', 'last_commit_at', 'contributors', 'releases', 'issues', 'old_issues', 'old_issues_unanswered', 'pulls', 'community', 'readme_size', 'root_files', 'github_dir', 'package', 'scorecard'}
    assert set(raw['repo']) == {'full_name', 'description', 'html_url', 'stars', 'forks', 'open_issues_count', 'archived', 'created_at', 'pushed_at', 'license', 'language', 'has_issues'}
    assert set(raw['package']) == {'ecosystem', 'name', 'version', 'vulns'}
    assert isinstance(raw['fetched_at'], str) and isinstance(raw['repo'], dict)
    assert isinstance(raw['commits_90d'], int) and isinstance(raw['commits_capped'], bool)
    assert isinstance(raw['commit_authors_90d'], dict) and isinstance(raw['last_commit_at'], str)
    assert all(isinstance(raw[key], list) for key in ('contributors', 'releases', 'issues', 'root_files', 'github_dir'))
    assert isinstance(raw['old_issues'], int) and isinstance(raw['old_issues_unanswered'], int)
    assert all(isinstance(raw[key], dict) for key in ('pulls', 'community', 'package', 'scorecard'))
    assert isinstance(raw['readme_size'], int) and isinstance(raw['package']['vulns'], list)
    assert all(isinstance(raw['package'][key], str) for key in ('ecosystem', 'name', 'version'))
    assert raw['repo']['full_name'] == 'owner/repo'
    assert raw['commits_90d'] == 2 and raw['commit_authors_90d'] == {'alice': 1, 'Bob': 1}
    assert len(raw['issues']) == 2 and raw['issues'][0]['first_response_at'] == '2026-10-02T00:00:00Z'
    assert (raw['old_issues'], raw['old_issues_unanswered']) == (2, 1)
    assert raw['pulls']['closed'] == 2 and len(raw['pulls']['merged']) == 1
    assert raw['readme_size'] == 1200 and raw['community']['license'] is True
    assert raw['package']['name'] == '@scope/package' and raw['package']['vulns'][0]['severity'] == 'CRITICAL'
    assert raw['scorecard']['score'] == 8.1
    await gh.close(); await external.close()


@pytest.mark.parametrize('readme_status,expected', [(404, 0), (500, None)])
async def test_missing_and_failed_subresources(readme_status, expected):
    def handler(request):
        if request.url.path == '/repos/a/b':
            return httpx.Response(200, json={'full_name': 'a/b', 'has_issues': False})
        if request.url.path.endswith('/readme'):
            return httpx.Response(readme_status)
        return httpx.Response(500)
    gh = GitHubClient(transport=httpx.MockTransport(handler))
    external = ExternalClient(httpx.MockTransport(lambda request: httpx.Response(500)))
    raw = await collect(gh, external, 'a', 'b', NOW)
    assert raw['readme_size'] == expected and raw['issues'] is None and raw['commits_90d'] is None
    await gh.close(); await external.close()


async def test_rate_limit_aborts_but_main_missing_is_404():
    def handler(request):
        if request.url.path == '/repos/a/b':
            return httpx.Response(200, json={'full_name': 'a/b'})
        return httpx.Response(429)
    gh = GitHubClient(transport=httpx.MockTransport(handler))
    external = ExternalClient(httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(RateLimited):
        await collect(gh, external, 'a', 'b', NOW)
    await gh.close(); await external.close()
    gh = GitHubClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    external = ExternalClient(httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(RepoNotFound):
        await collect(gh, external, 'a', 'b', NOW)
    await gh.close(); await external.close()


async def test_commit_cap_and_last_commit_fallback():
    mode = {'empty': False}
    def handler(request):
        path = request.url.path
        if path == '/repos/a/b':
            return httpx.Response(200, json={'full_name': 'a/b', 'has_issues': False})
        if path == '/repos/a/b/commits':
            if mode['empty']:
                return httpx.Response(200, json=[{'commit': {'committer': {'date': '2020-01-01T00:00:00Z'}}}] if request.url.params.get('per_page') == '1' else [])
            return httpx.Response(200, json=[{'commit': {'committer': {'date': '2026-10-30T00:00:00Z'}}}] * 100)
        return httpx.Response(404)
    gh = GitHubClient(transport=httpx.MockTransport(handler))
    external = ExternalClient(httpx.MockTransport(lambda request: httpx.Response(404)))
    raw = await collect(gh, external, 'a', 'b', NOW)
    assert raw['commits_90d'] == 300 and raw['commits_capped'] is True
    mode['empty'] = True
    raw = await collect(gh, external, 'a', 'b', NOW)
    assert raw['commits_90d'] == 0 and raw['last_commit_at'] == '2020-01-01T00:00:00Z'
    await gh.close()
    await external.close()


async def test_pyproject_candidate_requires_matching_repository():
    def handler(request):
        path = request.url.path
        if path == '/repos/a/b':
            return httpx.Response(200, json={'full_name': 'a/b'})
        if path == '/repos/a/b/contents':
            return httpx.Response(200, json=[{'name': 'pyproject.toml'}])
        if path == '/repos/a/b/contents/pyproject.toml':
            content = base64.b64encode(b"[project]\nname = 'my-package'\n").decode()
            return httpx.Response(200, json={'encoding': 'base64', 'content': content})
        return httpx.Response(404)
    def registry(request):
        if request.url.host == 'pypi.org' and '/my-package/' in request.url.path:
            return httpx.Response(200, json={'info': {'version': '1', 'home_page': 'https://github.com/other/project'}})
        return httpx.Response(404)
    gh = GitHubClient(transport=httpx.MockTransport(handler))
    external = ExternalClient(httpx.MockTransport(registry))
    raw = await collect(gh, external, 'a', 'b', NOW)
    assert raw['package'] is None
    await gh.close()
    await external.close()


async def test_malformed_subresources_do_not_abort():
    def handler(request):
        path = request.url.path
        if path == '/repos/a/b':
            return httpx.Response(200, json={'full_name': 'a/b', 'has_issues': True})
        values = {
            '/repos/a/b/commits': {'not': 'a list'},
            '/repos/a/b/contributors': [{'contributions': 7}],
            '/repos/a/b/issues': [{'number': 1, 'comments': 2, 'user': {'login': 'alice'}}],
            '/repos/a/b/pulls': ['wrong'],
            '/repos/a/b/releases': ['wrong'],
            '/repos/a/b/community/profile': {'files': []},
            '/repos/a/b/readme': {'size': 'not a number'},
            '/repos/a/b/contents': [{'wrong': 'key'}],
            '/repos/a/b/contents/.github': [None],
        }
        return httpx.Response(200, json=values[path]) if path in values else httpx.Response(404)
    gh = GitHubClient(transport=httpx.MockTransport(handler))
    external = ExternalClient(httpx.MockTransport(lambda request: httpx.Response(500)))
    raw = await collect(gh, external, 'a', 'b', NOW)
    for key in ('commits_90d', 'contributors', 'issues', 'old_issues', 'old_issues_unanswered', 'pulls', 'releases', 'community', 'readme_size', 'root_files', 'github_dir'):
        assert raw[key] is None, key
    assert raw['commit_authors_90d'] == {} and raw['commits_capped'] is False
    assert raw['repo']['full_name'] == 'a/b'
    await gh.close()
    await external.close()


async def test_malformed_comments_do_not_discard_issues():
    def handler(request):
        if request.url.path == '/repos/old/name':
            return github_handler(request)
        if request.url.path.endswith('/issues/1/comments'):
            return httpx.Response(200, json=[{'user': {'login': 'alice'}}])
        return github_handler(request)
    gh = GitHubClient(transport=httpx.MockTransport(handler))
    external = ExternalClient(httpx.MockTransport(external_handler))
    raw = await collect(gh, external, 'old', 'name', NOW)
    assert len(raw['issues']) == 2 and 'first_response_at' not in raw['issues'][0]
    await gh.close()
    await external.close()

