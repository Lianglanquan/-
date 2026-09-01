"""Versioned assessment catalogs.

The active catalog is the questionnaire participants see today. Legacy
catalogs are immutable snapshots used to interpret sessions created before a
question was removed or renumbered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTIVE_CATALOG_VERSION = "2.0.0"
LEGACY_CATALOG_VERSION = "1.0.0"
ACTIVE_SEED_TOTAL = 19
LEGACY_SEED_TOTAL = 20


@dataclass(frozen=True)
class RubricCatalog:
    version: str
    seed_total: int
    rubrics: dict[str, dict[str, Any]]


def _read_rubric_dir(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return result
    for rubric_path in sorted(path.glob("Q*.json")):
        try:
            value = json.loads(rubric_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("id"):
                result[str(value["id"])] = value
        except (OSError, json.JSONDecodeError):
            continue
    return result


def load_catalog(root: Path, version: str = ACTIVE_CATALOG_VERSION) -> RubricCatalog:
    rubrics_root = root / "rubrics"
    if version == LEGACY_CATALOG_VERSION:
        return RubricCatalog(version, LEGACY_SEED_TOTAL, _read_rubric_dir(rubrics_root / "legacy-v1"))
    if version != ACTIVE_CATALOG_VERSION:
        raise ValueError(f"unknown rubric catalog version: {version}")
    return RubricCatalog(version, ACTIVE_SEED_TOTAL, _read_rubric_dir(rubrics_root))


def load_active_catalog(root: Path) -> RubricCatalog:
    return load_catalog(root, ACTIVE_CATALOG_VERSION)


def catalog_for_session(session: dict[str, Any] | None, root: Path) -> RubricCatalog:
    """Resolve a session's catalog without guessing from renumbered items."""

    metadata = (session or {}).get("metadata") or {}
    version = str(metadata.get("catalog_version") or "").strip()
    if version:
        try:
            return load_catalog(root, version)
        except ValueError:
            pass
    # Rows created before catalog metadata was introduced are legacy. New
    # sessions always carry an explicit active version, even before the first
    # answer is submitted.
    return load_catalog(root, LEGACY_CATALOG_VERSION)
