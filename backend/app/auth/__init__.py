"""Password-based email identity and session authentication."""

from .service import AuthError, AuthService, hash_password, normalize_email, verify_password

__all__ = ["AuthError", "AuthService", "hash_password", "normalize_email", "verify_password"]
