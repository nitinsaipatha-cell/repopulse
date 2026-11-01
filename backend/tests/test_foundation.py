import httpx
import pytest

from app.config import Settings
from app.db import Database
from app.github_client import GitHubClient, GitHubError, RateLimited, RepoNotFound
from app.utils import extract_github_repo, parse_repo_ref


@pytest.mark.parametrize("reference,expected", [
    ("pallets/flask", "pallets/flask"),
    ("https://github.com/pallets/flask/tree/main/src", "pallets/flask"),
    ("git+https://github.com/pallets/flask.git", "pallets/flask"),
    ("github:pallets/flask", "pallets/flask"),
    ("owner/repo.name_1-2", "owner/repo.name_1-2"),
])
def test_repository_references(reference, expected):
    assert parse_repo_ref(reference) == expected


@pytest.mark.parametrize("reference", ["", "owner", "owner/repo/extra", "https://notgithub.com/a/b", "a/b c", "github:a/", "../repo"])
def test_invalid_repository_references(reference):
    with pytest.raises(ValueError, match="is not a GitHub repository"):
        parse_repo_ref(reference)


@pytest.mark.parametrize("url,expected", [
    ("git+https://github.com/owner/repo.git", "owner/repo"),
    ("git@github.com:owner/repo.git", "owner/repo"),
    ("https://example.com", None),
])
def test_extract_github_repo(url, expected):
    assert extract_github_repo(url) == expected


def test_settings_defaults_and_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://a.example, http://localhost:5173, ")
    settings = Settings()
    assert settings.cors_origins == ["https://a.example", "http://localhost:5173"]
    assert settings.cache_ttl_hours == 6
    assert settings.max_scan_deps == 50


def test_database_round_trip():
    db = Database(":memory:")
    with db.lock:
        indexes = db.connection.execute("PRAGMA index_list(history)").fetchall()
        index_columns = [
            [column["name"] for column in db.connection.execute(
                'PRAGMA index_info("' + index["name"].replace('"', '""') + '")'
            ).fetchall()]
            for index in indexes
        ]
    assert ["full_name", "ts"] in index_columns
    db.put_cache("Owner/Repo", "2026-01-01", {"repo": "value"})
    assert db.get_cache("owner/REPO")["raw"] == {"repo": "value"}
    db.add_history("Owner/Repo", "2026-01-02", 90, "Low", {"activity": 80})
    db.add_history("owner/repo", "2026-01-01", 70, "Medium", {})
    assert [r["score"] for r in db.get_history("OWNER/REPO")] == [70, 90]
    db.save_scan("abc", "2026-01-01", "running", 2, 1, {"rows": []})
    assert db.get_scan("abc")["payload"] == {"rows": []}
    assert db.get_scan("missing") is None
    db.close()


async def test_github_headers_redirects_and_pagination():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/redirect":
            return httpx.Response(301, headers={"location": "/repos/new/name"})
        if request.url.path == "/repos/new/name":
            return httpx.Response(200, json={"full_name": "new/name"})
        page = int(request.url.params["page"])
        return httpx.Response(200, json=list(range(100 if page == 1 else 3)))
    client = GitHubClient("secret", httpx.MockTransport(handler))
    assert (await client.get("/redirect"))["full_name"] == "new/name"
    assert len(await client.paged("/items", 3, {"state": "all"})) == 103
    assert requests[0].headers["authorization"] == "Bearer secret"
    assert requests[0].headers["x-github-api-version"] == "2022-11-28"
    assert requests[-1].url.params["per_page"] == "100"
    await client.close()


@pytest.mark.parametrize("status,headers,body,error", [
    (404, {}, "missing", RepoNotFound),
    (403, {}, "forbidden", GitHubError),
    (403, {"x-ratelimit-remaining": "0"}, "forbidden", RateLimited),
    (403, {}, "API rate limit exceeded", RateLimited),
    (429, {}, "slow down", RateLimited),
    (500, {}, "server error", GitHubError),
])
async def test_github_errors(status, headers, body, error):
    client = GitHubClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, headers=headers, text=body)))
    with pytest.raises(error) as exc:
        await client.get("/repo")
    if error is RateLimited:
        assert "Add a GITHUB_TOKEN" in str(exc.value)
    await client.close()


@pytest.mark.parametrize("status", [404, 409])
async def test_github_missing_optional(status):
    client = GitHubClient(transport=httpx.MockTransport(lambda request: httpx.Response(status)))
    assert await client.get("/missing", missing_ok=True) is None
    await client.close()


async def test_network_error():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)
    client = GitHubClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubError):
        await client.get("/repo")
    await client.close()
