"""Utilities shared by collection, API, and dependency parsing."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_URL = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)


def parse_repo_ref(value: str) -> str:
    """Return owner/repo from a supported repository reference."""
    original = value
    value = value.strip()
    if value.lower().startswith("github:"):
        path = value[7:]
    elif re.match(r"^(?:git\+)?https?://", value, re.IGNORECASE):
        url = urlsplit(re.sub(r"^git\+", "", value, flags=re.IGNORECASE))
        if (url.hostname or "").lower() != "github.com" or url.username or url.password or url.port:
            raise ValueError(f"'{original}' is not a GitHub repository. Use owner/repo or a github.com URL.")
        parts = url.path.strip("/").split("/")
        path = "/".join(parts[:2]) if len(parts) >= 2 else ""
    else:
        path = value
    parts = path.split("/")
    if len(parts) == 2 and parts[1].lower().endswith(".git"):
        parts[1] = parts[1][:-4]
    if len(parts) != 2 or not all(_NAME.fullmatch(part) and part not in {".", ".."} for part in parts):
        raise ValueError(f"'{original}' is not a GitHub repository. Use owner/repo or a github.com URL.")
    return "/".join(parts)


def extract_github_repo(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    match = _GITHUB_URL.search(value)
    if not match:
        return None
    owner, repo = match.groups()
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    return f"{owner}/{repo}" if owner not in {".", ".."} and repo not in {"", ".", ".."} else None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
