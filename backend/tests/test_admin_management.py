from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.app.audit.store import AuditStore
from backend.app.auth.service import AuthError, AuthService


class MemoryMailer:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    def send_verification_code(self, email: str, code: str) -> None:
        self.codes[email] = code

    def send_password_reset_code(self, email: str, code: str) -> None:
        self.codes[email + ':reset'] = code


class AdminManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = os.environ.get('ADMIN_EMAILS')
        os.environ['ADMIN_EMAILS'] = ''
        self.directory = tempfile.TemporaryDirectory()
        self.audit = AuditStore(Path(self.directory.name) / 'audit.sqlite3')
        self.mailer = MemoryMailer()
        self.auth = AuthService(self.audit, mailer=self.mailer)
        self.admin = self._register('first@example.com', admin=True)
        self.other_admin = self._register('second@example.com', admin=False)
        self.auth.admin_set_role(self.admin['id'], self.other_admin['id'], 'ADMIN')

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop('ADMIN_EMAILS', None)
        else:
            os.environ['ADMIN_EMAILS'] = self.previous
        self.directory.cleanup()

    def _register(self, email: str, *, admin: bool) -> dict[str, object]:
        user = self.auth.register(email, 'strong-pass', 'strong-pass')
        if admin:
            self.audit.update_user_role(user['id'], 'ADMIN')
        return self.audit.get_user(user['id']) or {}

    def test_admin_can_promote_and_demote_but_last_admin_is_protected(self) -> None:
        participant = self._register('person@example.com', admin=False)
        promoted = self.auth.admin_set_role(self.admin['id'], participant['id'], 'ADMIN')
        self.assertEqual(promoted['role'], 'ADMIN')
        demoted = self.auth.admin_set_role(self.admin['id'], participant['id'], 'PARTICIPANT')
        self.assertEqual(demoted['role'], 'PARTICIPANT')
        self.auth.admin_set_role(self.admin['id'], self.other_admin['id'], 'PARTICIPANT')
        with self.assertRaises(AuthError):
            self.auth.admin_set_role(self.admin['id'], self.admin['id'], 'PARTICIPANT')

    def test_invited_email_becomes_admin_after_registration(self) -> None:
        invite = self.auth.admin_invite(self.admin['id'], 'new-admin@example.com')
        self.assertEqual(invite['email'], 'new-admin@example.com')
        registered = self.auth.register('NEW-ADMIN@example.com', 'strong-pass', 'strong-pass')
        self.assertEqual(registered['role'], 'ADMIN')
        self.assertTrue(self.audit.invitation_consumed('new-admin@example.com'))

    def test_admin_can_deactivate_and_last_admin_cannot_be_deactivated(self) -> None:
        participant = self._register('inactive@example.com', admin=False)
        updated = self.auth.admin_set_active(self.admin['id'], participant['id'], False)
        self.assertFalse(updated['is_active'])
        self.auth.admin_set_active(self.admin['id'], self.other_admin['id'], False)
        with self.assertRaises(AuthError):
            self.auth.admin_set_active(self.admin['id'], self.admin['id'], False)

    def test_admin_actions_are_audited(self) -> None:
        participant = self._register('audited@example.com', admin=False)
        self.auth.admin_set_role(self.admin['id'], participant['id'], 'ADMIN')
        logs = self.audit.list_admin_access_logs(self.admin['id'])
        self.assertEqual(logs[-1]['action'], 'ROLE_CHANGE')
        self.assertEqual(logs[-1]['target_user_id'], participant['id'])


if __name__ == '__main__':
    unittest.main()
