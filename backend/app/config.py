"""Application configuration loaded from the ignored local environment file."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_local_env() -> None:
    """Load missing values from ``.env.local`` without logging secrets."""

    path = ROOT / ".env.local"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: tuple[str, ...] = ()) -> list[str]:
    """Read a comma-separated environment value without exposing secrets.

    Keeping this tiny parser here avoids a dotenv dependency while making
    deployment-specific lists (for example CORS origins) explicit and easy to
    audit. Empty entries are ignored and values are trimmed.
    """

    value = os.getenv(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def runtime_data_root() -> Path:
    """Return the writable runtime directory, separate from release code.

    Production sets an absolute ``QIUZHENG_DATA_ROOT`` under the persistent
    server volume. Local development keeps the repository's historical
    ``data/derived`` default so existing scripts and tests remain compatible.
    """

    configured = os.getenv("QIUZHENG_DATA_ROOT", "").strip()
    if not configured:
        return ROOT / "data" / "derived"
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / path


load_local_env()
