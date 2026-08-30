"""Safely clear local runtime audit data before publishing or a demo reset.

This intentionally requires ``--confirm`` and only accepts the repository's
``data/derived/audit.sqlite3`` by default. Raw research inputs are never
touched. The command is for local/runtime housekeeping, not a data-retention
policy or a substitute for an archival process.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "derived" / "audit.sqlite3"
DEFAULT_EXPORT = ROOT / "data" / "derived" / "adjudicated_dataset.jsonl"


def reset(path: Path, export_path: Path) -> None:
    expected_parent = ROOT / "data" / "derived"
    if path.parent.resolve() != expected_parent.resolve() or path.name != "audit.sqlite3":
        raise ValueError("refusing to clear a database outside data/derived/audit.sqlite3")
    if not path.exists():
        print(f"No runtime database found at {path}; nothing to clear.")
        return
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        # Delete children first so this remains valid if foreign-key checks are
        # enabled on a future schema revision.
        for table in ("reviews", "review_cases", "session_decisions", "events", "sessions"):
            connection.execute(f'DELETE FROM "{table}"')
    # Checkpoint and compact only after the delete transaction has committed;
    # SQLite rejects a WAL checkpoint while the same connection still owns a
    # write transaction.
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
    if export_path.resolve().parent == expected_parent.resolve() and export_path.exists():
        export_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    print(f"Cleared runtime audit data: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="confirm deletion of runtime audit records")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.confirm:
        parser.error("refusing to clear runtime data without --confirm")
    reset(args.db, DEFAULT_EXPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
