"""Settings from environment variables (no extra dependency; `.env` files are not loaded — set variables in the shell/service).

P2E_DB_URL        database URL (default sqlite:///data/p2e.db); on Vercel the Neon integration's DATABASE_URL is used
P2E_UPLOAD_DIR    raw upload store (default data/uploads)
P2E_GLOSSARY      project vocabulary used by the extractors (default data/synthetic/glossary.json)
P2E_API_KEYS      "role:key,role:key" with role in supervisor|planner|admin; keys >= 16 characters. Unset = writes disabled.
P2E_LLM_ENDPOINT  optional self-hosted text-generation endpoint for the Phase 3 tie-breaker (unset = off; non-private
                  hosts refused unless P2E_LLM_ALLOW_REMOTE=1)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def db_url_from_env(default: str) -> str:
    """P2E_DB_URL, else DATABASE_URL (Vercel / Neon). postgres:// URLs are pointed at the psycopg 3 driver."""
    url = os.environ.get("P2E_DB_URL") or os.environ.get("DATABASE_URL") or default
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    db_url: str
    synthetic_dir: Path
    upload_dir: Path
    glossary_path: Path
    api_keys_spec: str | None


def get_settings() -> Settings:
    synthetic = Path(os.environ.get("P2E_SYNTHETIC_DIR", REPO_ROOT / "data" / "synthetic"))
    return Settings(
        db_url=db_url_from_env(f"sqlite:///{(REPO_ROOT / 'data' / 'p2e.db').as_posix()}"),
        synthetic_dir=synthetic,
        upload_dir=Path(os.environ.get("P2E_UPLOAD_DIR", REPO_ROOT / "data" / "uploads")),
        glossary_path=Path(os.environ.get("P2E_GLOSSARY", synthetic / "glossary.json")),
        api_keys_spec=os.environ.get("P2E_API_KEYS"),
    )
