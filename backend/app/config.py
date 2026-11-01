"""Environment configuration for the backend."""
from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Settings:
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "data/repopulse.db"))
    cache_ttl_hours: float = field(default_factory=lambda: float(os.getenv("CACHE_TTL_HOURS", "6")))
    max_scan_deps: int = field(default_factory=lambda: int(os.getenv("MAX_SCAN_DEPS", "50")))
    rate_limit_per_min: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MIN", "30")))
    cors_origins: list[str] = field(default_factory=lambda: [
        origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ])
