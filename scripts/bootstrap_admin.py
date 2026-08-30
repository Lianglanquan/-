"""Idempotently create one verified administrator for a local deployment.

Credentials are read from environment variables or hidden prompts. The
password is hashed immediately and is never printed or written to source.
Run once per administrator, then remove the temporary environment variables.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.audit.store import AuditStore
from backend.app.auth.service import hash_password, normalize_email


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or promote one verified administrator")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "derived" / "audit.sqlite3")
    args = parser.parse_args()
    raw_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip() or input("管理员邮箱: ").strip()
    email = normalize_email(raw_email)
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    if password is None:
        password = getpass.getpass("管理员密码（不会显示）: ")
    if not password:
        raise SystemExit("管理员密码不能为空")

    audit = AuditStore(args.database)
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    existing = audit.find_user_by_email_hash(email_hash)
    if existing:
        audit.update_user_role(existing["id"], "ADMIN")
        audit.update_user_active(existing["id"], True)
        audit.update_user_password(existing["id"], hash_password(password))
        audit.mark_user_verified(existing["id"])
        user_id = existing["id"]
        action = "updated"
    else:
        created = audit.create_user(email=email, email_hash=email_hash, password_hash=hash_password(password), role="ADMIN")
        audit.mark_user_verified(created["id"])
        user_id = created["id"]
        action = "created"
    print(f"管理员账号已{action}: {email} ({user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
