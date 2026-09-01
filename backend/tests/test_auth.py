from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.app.audit.store import AuditStore
from backend.app.auth.service import AuthError, AuthService, hash_password, verify_password


class MemoryMailer:
    def __init__(self) -> None:
        self.verification_codes: dict[str, str] = {}
        self.reset_codes: dict[str, str] = {}

    def send_verification_code(self, email: str, code: str) -> None:
        self.verification_codes[email] = code

    def send_password_reset_code(self, email: str, code: str) -> None:
        self.reset_codes[email] = code


class AuthServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_admin_emails = os.environ.get("ADMIN_EMAILS")
        os.environ["ADMIN_EMAILS"] = "owner@example.com, second@example.com"
        self.directory = tempfile.TemporaryDirectory()
        self.audit = AuditStore(Path(self.directory.name) / "audit.sqlite3")
        self.mailer = MemoryMailer()
        self.auth = AuthService(self.audit, mailer=self.mailer, session_ttl_seconds=3600)

    def tearDown(self) -> None:
        if self.previous_admin_emails is None:
            os.environ.pop("ADMIN_EMAILS", None)
        else:
            os.environ["ADMIN_EMAILS"] = self.previous_admin_emails
        self.directory.cleanup()

    def test_password_hash_is_salted_and_verifiable(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertFalse(verify_password("wrong password", first))

    def test_register_normalizes_email_and_assigns_admin_from_allowlist(self) -> None:
        admin = self.auth.register(" Owner@Example.com ", "a-strong-password", "a-strong-password")
        participant = self.auth.register("person@example.com", "another-strong-password", "another-strong-password")

        self.assertEqual(admin["email"], "owner@example.com")
        self.assertEqual(admin["role"], "ADMIN")
        self.assertEqual(participant["role"], "PARTICIPANT")
        self.assertTrue(admin["email_verified"])
        self.assertTrue(participant["email_verified"])
        self.assertEqual(self.mailer.verification_codes, {})

    def test_register_rejects_mismatched_password_confirmation(self) -> None:
        with self.assertRaisesRegex(AuthError, "Passwords do not match"):
            self.auth.register("person@example.com", "another-strong-password", "different-password")

    def test_registration_creates_an_immediately_loginable_user_and_revocable_session(self) -> None:
        registered = self.auth.register("person@example.com", "another-strong-password", "another-strong-password")
        user, token = self.auth.login("PERSON@example.com", "another-strong-password")
        self.assertEqual(user["id"], registered["id"])
        self.assertEqual(self.auth.current_user(token)["id"], registered["id"])
        self.auth.logout(token)
        self.assertIsNone(self.auth.current_user(token))

    def test_wrong_password_does_not_create_session(self) -> None:
        registered = self.auth.register("person@example.com", "another-strong-password", "another-strong-password")
        user, token = self.auth.login(registered["email"], "another-strong-password")
        self.assertEqual(user["id"], registered["id"])
        self.auth.logout(token)
        with self.assertRaises(AuthError):
            self.auth.login(registered["email"], "wrong-password")

    def test_duplicate_registration_has_generic_auth_error(self) -> None:
        self.auth.register("person@example.com", "another-strong-password", "another-strong-password")
        with self.assertRaises(AuthError) as context:
            self.auth.register("PERSON@example.com", "another-strong-password", "another-strong-password")
        self.assertEqual(str(context.exception), "Unable to create account")


if __name__ == "__main__":
    unittest.main()
