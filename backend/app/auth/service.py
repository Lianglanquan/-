"""Email/password authentication with server-side sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from backend.app.audit.store import AuditStore
from backend.app.config import env_list


class AuthError(ValueError):
    """A safe, user-facing authentication failure."""


class AuthMailer(Protocol):
    def send_verification_code(self, email: str, code: str) -> None: ...
    def send_password_reset_code(self, email: str, code: str) -> None: ...


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


def normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not EMAIL_RE.fullmatch(email) or len(email) > 320:
        raise AuthError("Enter a valid email address")
    return email


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise AuthError(f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters")
    return password


def hash_password(password: str) -> str:
    password = _validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.urlsafe_b64encode(salt).decode("ascii") + "$" + base64.urlsafe_b64encode(digest).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "email_verified": bool(row.get("email_verified_at")),
        "is_active": bool(row.get("is_active", 1)),
        "created_at": row.get("created_at"),
    }


class AuthService:
    def __init__(self, audit: AuditStore, *, mailer: AuthMailer, session_ttl_seconds: int = 60 * 60 * 24 * 14, challenge_ttl_seconds: int = 600) -> None:
        self.audit = audit
        self.mailer = mailer
        self.session_ttl_seconds = session_ttl_seconds
        self.challenge_ttl_seconds = challenge_ttl_seconds

    def register(self, email: str, password: str, password_confirmation: str) -> dict[str, Any]:
        normalized = normalize_email(email)
        password = _validate_password(password)
        if not isinstance(password_confirmation, str) or not hmac.compare_digest(password, password_confirmation):
            raise AuthError("Passwords do not match")
        email_hash = _digest(normalized)
        if self.audit.find_user_by_email_hash(email_hash):
            raise AuthError("Unable to create account")
        allowlist = {str(value).strip().lower() for value in env_list("ADMIN_EMAILS") if str(value).strip()}
        invitation = self.audit.consume_admin_invite(email_hash=email_hash, now=_iso(_now()))
        role = "ADMIN" if normalized in allowlist or invitation else "PARTICIPANT"
        user = self.audit.create_user(email=normalized, email_hash=email_hash, password_hash=hash_password(password), role=role)
        self.audit.mark_user_verified(user["id"])
        verified = self.audit.get_user(user["id"])
        if not verified:
            raise AuthError("Unable to create account")
        return _public_user(verified)

    def verify_email(self, email: str, code: str) -> dict[str, Any]:
        normalized = normalize_email(email)
        user = self.audit.find_user_by_email_hash(_digest(normalized))
        if not user:
            raise AuthError("Invalid verification code")
        challenge = self.audit.consume_auth_challenge(email_hash=_digest(normalized), purpose="VERIFY_EMAIL", code_hash=_digest(str(code).strip()), now=_iso(_now()))
        if not challenge or challenge.get("user_id") != user["id"]:
            raise AuthError("Invalid verification code")
        self.audit.mark_user_verified(user["id"])
        verified = self.audit.get_user(user["id"])
        if not verified:
            raise AuthError("Unable to verify account")
        return _public_user(verified)

    def resend_verification(self, email: str) -> None:
        normalized = normalize_email(email)
        user = self.audit.find_user_by_email_hash(_digest(normalized))
        if not user or user.get("email_verified_at") or not user.get("is_active", 1):
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.audit.create_auth_challenge(
            user_id=user["id"],
            email_hash=_digest(normalized),
            purpose="VERIFY_EMAIL",
            code_hash=_digest(code),
            expires_at=_iso(_now() + timedelta(seconds=self.challenge_ttl_seconds)),
        )
        self.mailer.send_verification_code(normalized, code)

    def login(self, email: str, password: str) -> tuple[dict[str, Any], str]:
        normalized = normalize_email(email)
        user = self.audit.find_user_by_email_hash(_digest(normalized))
        if not user or not verify_password(password, user.get("password_hash", "")):
            raise AuthError("Invalid email or password")
        if not user.get("email_verified_at"):
            raise AuthError("Verify your email before signing in")
        if not user.get("is_active", 1):
            raise AuthError("Account is disabled")
        token = secrets.token_urlsafe(32)
        self.audit.create_auth_session(user_id=user["id"], token_hash=_digest(token), expires_at=_iso(_now() + timedelta(seconds=self.session_ttl_seconds)))
        self.audit.mark_user_login(user["id"])
        return _public_user(user), token

    def request_password_reset(self, email: str) -> None:
        """Issue a reset code without revealing whether an account exists."""

        normalized = normalize_email(email)
        user = self.audit.find_user_by_email_hash(_digest(normalized))
        if not user or not user.get("is_active", 1):
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.audit.create_auth_challenge(
            user_id=user["id"],
            email_hash=_digest(normalized),
            purpose="RESET_PASSWORD",
            code_hash=_digest(code),
            expires_at=_iso(_now() + timedelta(seconds=self.challenge_ttl_seconds)),
        )
        self.mailer.send_password_reset_code(normalized, code)

    def reset_password(self, email: str, code: str, new_password: str) -> None:
        normalized = normalize_email(email)
        password = _validate_password(new_password)
        user = self.audit.find_user_by_email_hash(_digest(normalized))
        challenge = self.audit.consume_auth_challenge(
            email_hash=_digest(normalized),
            purpose="RESET_PASSWORD",
            code_hash=_digest(str(code).strip()),
            now=_iso(_now()),
        )
        if not user or not challenge or challenge.get("user_id") != user["id"]:
            raise AuthError("Invalid reset code")
        self.audit.update_user_password(user["id"], hash_password(password))
        self.audit.revoke_user_auth_sessions(user["id"])

    def current_user(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        row = self.audit.get_auth_session_user(token_hash=_digest(token), now=_iso(_now()))
        return _public_user(row) if row else None

    def logout(self, token: str | None) -> None:
        if token:
            self.audit.revoke_auth_session(_digest(token))

    def admin_set_role(self, actor_user_id: str, target_user_id: str, role: str) -> dict[str, Any]:
        role = str(role or "").strip().upper()
        if role not in {"ADMIN", "PARTICIPANT"}:
            raise AuthError("Invalid role")
        target = self.audit.get_user(target_user_id)
        if not target:
            raise AuthError("Account not found")
        if target.get("role") == "ADMIN" and role != "ADMIN" and target.get("is_active", 1) and self.audit.count_admins() <= 1:
            raise AuthError("At least one active administrator is required")
        updated = self.audit.update_user_role(target_user_id, role)
        if not updated:
            raise AuthError("Account not found")
        self.audit.record_admin_access(
            admin_user_id=actor_user_id,
            target_user_id=target_user_id,
            session_id=None,
            action="ROLE_CHANGE",
            resource=f"user_role:{role}",
        )
        return _public_user(updated)

    def admin_set_active(self, actor_user_id: str, target_user_id: str, is_active: bool) -> dict[str, Any]:
        target = self.audit.get_user(target_user_id)
        if not target:
            raise AuthError("Account not found")
        if target.get("role") == "ADMIN" and target.get("is_active", 1) and not is_active and self.audit.count_admins() <= 1:
            raise AuthError("At least one active administrator is required")
        updated = self.audit.update_user_active(target_user_id, is_active)
        if not updated:
            raise AuthError("Account not found")
        if not is_active:
            self.audit.revoke_user_auth_sessions(target_user_id)
        self.audit.record_admin_access(
            admin_user_id=actor_user_id,
            target_user_id=target_user_id,
            session_id=None,
            action="ACCOUNT_ACTIVATE" if is_active else "ACCOUNT_DEACTIVATE",
            resource="user_account",
        )
        return _public_user(updated)

    def admin_invite(self, actor_user_id: str, email: str) -> dict[str, Any]:
        normalized = normalize_email(email)
        existing = self.audit.find_user_by_email_hash(_digest(normalized))
        if existing:
            return self.admin_set_role(actor_user_id, existing["id"], "ADMIN")
        expires_at = _iso(_now() + timedelta(days=7))
        invite_id = self.audit.create_admin_invite(
            email=normalized,
            email_hash=_digest(normalized),
            invited_by=actor_user_id,
            expires_at=expires_at,
        )
        self.audit.record_admin_access(
            admin_user_id=actor_user_id,
            target_user_id=None,
            session_id=None,
            action="ADMIN_INVITE",
            resource=f"admin_invite:{invite_id}",
        )
        return {"id": invite_id, "email": normalized, "expires_at": expires_at, "status": "PENDING"}
