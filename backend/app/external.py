"""Failure-tolerant clients for public package and security services."""
from urllib.parse import quote

import httpx

from app.utils import extract_github_repo


class ExternalClient:
    def __init__(self, transport=None):
        self.client = httpx.AsyncClient(timeout=10.0, follow_redirects=True, transport=transport)

    async def close(self):
        await self.client.aclose()

    async def _json(self, method, url, **kwargs):
        try:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    async def registry(self, ecosystem, name):
        if ecosystem == "npm":
            data = await self._json("GET", f"https://registry.npmjs.org/{quote(name, safe='@')}/latest")
            if not isinstance(data, dict):
                return None
            repository = data.get("repository")
            if isinstance(repository, dict):
                repository = repository.get("url")
            repo = extract_github_repo(repository) or extract_github_repo(data.get("homepage"))
            version = data.get("version")
        elif ecosystem == "PyPI":
            data = await self._json("GET", f"https://pypi.org/pypi/{quote(name, safe='')}/json")
            if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
                return None
            info = data["info"]
            urls = info.get("project_urls") or {}
            candidates = list(urls.values()) if isinstance(urls, dict) else []
            candidates += [info.get("home_page"), info.get("download_url")]
            repo = next((repo for url in candidates if (repo := extract_github_repo(url))), None)
            version = info.get("version")
        else:
            return None
        return {"name": name, "ecosystem": ecosystem, "version": version, "repo": repo}

    async def vulnerabilities(self, ecosystem, name, version):
        if not version:
            return []
        data = await self._json("POST", "https://api.osv.dev/v1/query", json={"package": {"name": name, "ecosystem": ecosystem}, "version": version})
        if not isinstance(data, dict) or not isinstance(data.get("vulns", []), list):
            return []
        result = []
        for vuln in data.get("vulns", []):
            if not isinstance(vuln, dict) or vuln.get("withdrawn"):
                continue
            specific = vuln.get("database_specific") or {}
            severity = specific.get("severity") if isinstance(specific, dict) else None
            result.append({"id": vuln.get("id"), "severity": severity.upper() if isinstance(severity, str) else None, "summary": (vuln.get("summary") or "")[:140]})
        return result

    async def scorecard(self, full_name):
        data = await self._json("GET", f"https://api.securityscorecards.dev/projects/github.com/{full_name}", timeout=10.0)
        if not isinstance(data, dict):
            return None
        checks = data.get("checks")
        if not isinstance(checks, list):
            return None
        return {"score": data.get("score"), "date": data.get("date"), "checks": [{"name": item.get("name"), "score": item.get("score")} for item in checks if isinstance(item, dict)]}
