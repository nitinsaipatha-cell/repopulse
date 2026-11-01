"""GitHub REST client with bounded concurrency and explicit error mapping."""
import asyncio
import math
import time

import httpx


class GitHubError(Exception):
    status_code = 502


class RepoNotFound(GitHubError):
    status_code = 404

    def __init__(self):
        super().__init__("Repository not found. Check the name; it may also be private.")


class RateLimited(GitHubError):
    status_code = 429


class GitHubClient:
    def __init__(self, token: str = "", transport=None):
        self.token = token
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "repopulse"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(base_url="https://api.github.com", headers=headers, follow_redirects=True, timeout=25.0, transport=transport)
        self.semaphore = asyncio.Semaphore(8)

    async def close(self):
        await self.client.aclose()

    async def get(self, path: str, params=None, missing_ok: bool = False):
        try:
            async with self.semaphore:
                response = await self.client.get(path, params=params)
        except httpx.RequestError as exc:
            raise GitHubError("GitHub request failed. Please try again.") from exc
        if response.status_code == 404:
            if missing_ok:
                return None
            raise RepoNotFound()
        if response.status_code == 409:
            return None
        if response.status_code in (403, 429) and (response.status_code == 429 or response.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in response.text.lower()):
            try:
                minutes = max(0, math.ceil((int(response.headers.get("x-ratelimit-reset", "0")) - time.time()) / 60))
            except ValueError:
                minutes = 0
            message = f"GitHub API rate limit reached. Resets in about {minutes} min."
            if not self.token:
                message += " Add a GITHUB_TOKEN to raise the limit to 5,000/hour."
            raise RateLimited(message)
        if response.is_error:
            raise GitHubError(f"GitHub request failed (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError("GitHub returned an invalid response.") from exc

    async def paged(self, path: str, max_pages: int, params=None):
        result = []
        for page in range(1, max_pages + 1):
            data = await self.get(path, params={**(params or {}), "per_page": 100, "page": page})
            if data is None:
                return None
            if not isinstance(data, list):
                raise GitHubError("GitHub returned an invalid paginated response.")
            result.extend(data)
            if len(data) < 100:
                break
        return result
