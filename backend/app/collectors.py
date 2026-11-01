"""Collect GitHub measurements while preserving unavailable data as null."""
import asyncio
import base64
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.github_client import GitHubError, RateLimited, RepoNotFound
from app.utils import utc_now


def _safe_parse(parser, value):
    if value is None:
        return None
    try:
        return parser(value)
    except RateLimited:
        raise
    except Exception:
        return None


def _list(value):
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return value


def _commits(value):
    commits = _list(value)
    authors = Counter()
    for item in commits:
        commit = item["commit"]
        committer = commit.get("committer") or {}
        if not isinstance(committer, dict):
            raise ValueError("Invalid committer")
        author = item.get("author") or {}
        git_author = commit.get("author") or {}
        login = author.get("login") or git_author.get("name")
        if login:
            if not isinstance(login, str):
                raise ValueError("Invalid author")
            authors[login] += 1
    date = ((commits[0]["commit"].get("committer") or {}).get("date")) if commits else None
    if date is not None and not isinstance(date, str):
        raise ValueError("Invalid date")
    return {"count": len(commits), "authors": dict(authors), "date": date}


def _contributors(value):
    result = []
    for item in _list(value):
        login, contributions = item["login"], item["contributions"]
        if not isinstance(login, str) or not isinstance(contributions, int):
            raise ValueError("Invalid contributor")
        result.append({"login": login, "contributions": contributions})
    return result


def _releases(value):
    result = []
    for item in _list(value):
        date = item.get("published_at")
        if date is not None and not isinstance(date, str):
            raise ValueError("Invalid release")
        if date:
            result.append(date)
    return result


def _issues(value, now):
    rows = []
    old_count = unanswered = 0
    for item in _list(value):
        if "pull_request" in item:
            continue
        number, created, comments = item["number"], item["created_at"], item["comments"]
        author = item["user"]["login"]
        closed = item.get("closed_at")
        if not isinstance(number, int) or not isinstance(comments, int) or not isinstance(author, str) or (closed is not None and not isinstance(closed, str)):
            raise ValueError("Invalid issue")
        date = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("Issue date has no timezone")
        if now - date > timedelta(days=14):
            old_count += 1
            unanswered += comments == 0
        rows.append({"number": number, "created_at": created, "closed_at": closed, "comments": comments, "author": author})
    return rows, old_count, unanswered


def _pulls(value):
    pulls = _list(value)
    merged = []
    for item in pulls:
        merged_at = item.get("merged_at")
        if merged_at:
            created = item["created_at"]
            if not isinstance(created, str) or not isinstance(merged_at, str):
                raise ValueError("Invalid pull request")
            merged.append({"created_at": created, "merged_at": merged_at})
    return {"closed": len(pulls), "merged": merged}


def _community(value):
    files = value["files"]
    if not isinstance(files, dict):
        raise ValueError("Invalid community profile")
    return {key: bool(files.get(key)) for key in ("code_of_conduct", "contributing", "license", "issue_template", "pull_request_template")}


def _names(value):
    names = []
    for item in _list(value):
        name = item["name"]
        if not isinstance(name, str):
            raise ValueError("Invalid filename")
        names.append(name)
    return names


def _readme(value):
    if value is False:
        return 0
    size = value["size"]
    if not isinstance(size, int) or size < 0:
        raise ValueError("Invalid README size")
    return size


def _first_response(value, author):
    for comment in _list(value):
        user = comment["user"]
        login, user_type = user["login"], user["type"]
        if not isinstance(login, str) or not isinstance(user_type, str):
            raise ValueError("Invalid comment author")
        if login != author and user_type != "Bot":
            date = comment["created_at"]
            if not isinstance(date, str):
                raise ValueError("Invalid comment date")
            return date
    return None


async def collect(github, external, owner, repo, now=None):
    now = now or utc_now()
    main = await github.get(f"/repos/{owner}/{repo}")
    if not isinstance(main, dict) or not isinstance(main.get("full_name"), str) or "/" not in main["full_name"]:
        raise GitHubError("GitHub returned an invalid repository response.")
    full_name = main["full_name"]
    root = f"/repos/{full_name}"

    async def optional(call):
        try:
            return await call
        except RateLimited:
            raise
        except Exception:
            return None

    async def readme_info():
        try:
            return await github.get(f"{root}/readme")
        except RateLimited:
            raise
        except RepoNotFound:
            return False
        except Exception:
            return None

    since = (now - timedelta(days=90)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    calls = [
        optional(github.paged(f"{root}/commits", 3, {"since": since})),
        optional(github.get(f"{root}/contributors", {"per_page": 100, "anon": "false"})),
        optional(github.get(f"{root}/releases", {"per_page": 30})),
        optional(github.get(f"{root}/issues", {"state": "all", "per_page": 100, "sort": "created", "direction": "desc"})) if main.get("has_issues", True) else asyncio.sleep(0, result=None),
        optional(github.get(f"{root}/pulls", {"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"})),
        optional(github.get(f"{root}/community/profile")), readme_info(),
        optional(github.get(f"{root}/contents")), optional(github.get(f"{root}/contents/.github", missing_ok=True)),
        optional(external.scorecard(full_name)),
    ]
    commits, contributors, releases, issues, pulls, community, readme, root_files, github_dir, scorecard = await asyncio.gather(*calls)
    commit_info = _safe_parse(_commits, commits)
    last_commit_at = commit_info["date"] if commit_info is not None else None
    if commit_info is not None and commit_info["count"] == 0:
        latest = _safe_parse(_commits, await optional(github.get(f"{root}/commits", {"per_page": 1})))
        last_commit_at = latest["date"] if latest else None
    issue_info = _safe_parse(lambda value: _issues(value, now), issues)
    issue_rows, old_count, unanswered = issue_info if issue_info is not None else (None, None, None)
    if issue_rows is not None:
        async def response_for(item):
            comments = await optional(github.get(f"{root}/issues/{item['number']}/comments", {"per_page": 5}))
            date = _safe_parse(lambda value: _first_response(value, item["author"]), comments)
            if date is not None:
                item["first_response_at"] = date
        await asyncio.gather(*(response_for(item) for item in [i for i in issue_rows if i["comments"]][:12]))

    root_names = _safe_parse(_names, root_files)
    github_names = _safe_parse(_names, github_dir)
    candidates = []

    async def file_text(name):
        result = await optional(github.get(f"{root}/contents/{name}", missing_ok=True))
        def decode(value):
            if value["encoding"] != "base64":
                raise ValueError("Unsupported encoding")
            return base64.b64decode(value["content"]).decode("utf-8")
        return _safe_parse(decode, result)

    if root_names is not None:
        if "package.json" in root_names:
            package_name = _safe_parse(lambda text: json.loads(text)["name"], await file_text("package.json"))
            if isinstance(package_name, str) and package_name:
                candidates.append(("npm", package_name))
        if "pyproject.toml" in root_names:
            text = await file_text("pyproject.toml")
            match = re.search(r'^\s*name\s*=\s*[\'"]([^\'"]+)[\'"]', text or "", re.MULTILINE)
            if match:
                candidates.append(("PyPI", match.group(1)))
    candidates.extend([("npm", full_name.split("/", 1)[1]), ("PyPI", full_name.split("/", 1)[1])])
    package = None
    seen = set()
    for ecosystem, name in candidates:
        key = (ecosystem, name.lower())
        if key in seen:
            continue
        seen.add(key)
        found = await optional(external.registry(ecosystem, name))
        linked = _safe_parse(lambda item: item["repo"].lower(), found)
        if linked == full_name.lower():
            version = _safe_parse(lambda item: item["version"], found)
            vulns = await optional(external.vulnerabilities(ecosystem, name, version))
            if not isinstance(vulns, list):
                vulns = []
            package = {"ecosystem": ecosystem, "name": name, "version": version, "vulns": vulns}
            break
    license_info = main.get("license") or {}
    return {
        "fetched_at": now.isoformat(),
        "repo": {"full_name": full_name, "description": main.get("description"), "html_url": main.get("html_url"), "stars": main.get("stargazers_count"), "forks": main.get("forks_count"), "open_issues_count": main.get("open_issues_count"), "archived": main.get("archived"), "created_at": main.get("created_at"), "pushed_at": main.get("pushed_at"), "license": license_info.get("spdx_id") if isinstance(license_info, dict) else None, "language": main.get("language"), "has_issues": main.get("has_issues", True)},
        "commits_90d": commit_info["count"] if commit_info is not None else None,
        "commits_capped": commit_info is not None and commit_info["count"] >= 300,
        "commit_authors_90d": commit_info["authors"] if commit_info is not None else {},
        "last_commit_at": last_commit_at,
        "contributors": _safe_parse(_contributors, contributors), "releases": _safe_parse(_releases, releases),
        "issues": issue_rows, "old_issues": old_count, "old_issues_unanswered": unanswered,
        "pulls": _safe_parse(_pulls, pulls), "community": _safe_parse(_community, community),
        "readme_size": _safe_parse(_readme, readme), "root_files": root_names, "github_dir": github_names,
        "package": package, "scorecard": scorecard,
    }
