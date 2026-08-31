from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api import routes
from backend.app.audit.store import AuditStore
from backend.app.auth.service import AuthService
from backend.app.main import app
from backend.app.assessment.service import AssessmentStore


class MemoryMailer:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    def send_verification_code(self, email: str, code: str) -> None:
        self.codes[email] = code

    def send_password_reset_code(self, email: str, code: str) -> None:
        self.codes[email + ':reset'] = code


class AdminApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_admins = os.environ.get('ADMIN_EMAILS')
        os.environ['ADMIN_EMAILS'] = 'owner@example.com'
        self.directory = tempfile.TemporaryDirectory()
        self.audit = AuditStore(Path(self.directory.name) / 'audit.sqlite3')
        self.mailer = MemoryMailer()
        self.auth = AuthService(self.audit, mailer=self.mailer)
        self.previous_routes = (routes.AUDIT, routes.AUTH, routes.STORE)
        routes.AUDIT = self.audit
        routes.AUTH = self.auth
        routes.STORE = AssessmentStore(routes.RUBRICS, scorer=routes.SCORER, audit=self.audit, root=routes.ROOT)
        import backend.app.security as security
        self.previous_security = (security._AUDIT, security._AUTH)
        security._AUDIT = self.audit
        security._AUTH = self.auth
        self.client = TestClient(app)

    def tearDown(self) -> None:
        routes.AUDIT, routes.AUTH, routes.STORE = self.previous_routes
        import backend.app.security as security
        security._AUDIT, security._AUTH = self.previous_security
        if self.previous_admins is None:
            os.environ.pop('ADMIN_EMAILS', None)
        else:
            os.environ['ADMIN_EMAILS'] = self.previous_admins
        self.directory.cleanup()

    def _register(self, email: str, password: str = 'strong-pass') -> dict[str, object]:
        response = self.client.post('/api/auth/register', json={'email': email, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)
        code = self.mailer.codes[email]
        self.assertEqual(self.client.post('/api/auth/verify-email', json={'email': email, 'code': code}).status_code, 200)
        return response.json()

    def _login(self, email: str, password: str = 'strong-pass') -> None:
        response = self.client.post('/api/auth/login', json={'email': email, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)

    def test_participant_is_denied_and_admin_can_change_role(self) -> None:
        self._register('owner@example.com')
        person = self._register('person@example.com')
        self._login('person@example.com')
        self.assertEqual(self.client.get('/api/admin/users').status_code, 403)
        self.client.post('/api/auth/logout')
        self._login('owner@example.com')
        response = self.client.post(f"/api/admin/users/{person['id']}/role", json={'role': 'ADMIN'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_admin_can_invite_email_and_audit_endpoint_is_available(self) -> None:
        self._register('owner@example.com')
        self._login('owner@example.com')
        invite = self.client.post('/api/admin/invites', json={'email': 'new@example.com'})
        self.assertEqual(invite.status_code, 200, invite.text)
        registered = self._register('new@example.com')
        self.assertEqual(registered['role'], 'ADMIN')
        audit = self.client.get('/api/admin/audit')
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertTrue(any(row['action'] == 'ADMIN_INVITE' for row in audit.json()))

    def test_admin_can_list_and_open_participant_session_with_ai_trace(self) -> None:
        self._register('owner@example.com')
        participant = self._register('person@example.com')
        self._login('person@example.com')
        started = self.client.post('/api/assessment/start')
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()['id']
        submitted = self.client.post(
            f'/api/assessment/{session_id}/responses',
            json={'question_id': 'Q01', 'response': '有一点难过'},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.client.post('/api/auth/logout')
        self._login('owner@example.com')

        sessions = self.client.get('/api/admin/sessions')
        self.assertEqual(sessions.status_code, 200, sessions.text)
        self.assertTrue(any(item['id'] == session_id and item['user_id'] == participant['id'] for item in sessions.json()))
        detail = self.client.get(f'/api/admin/sessions/{session_id}')
        self.assertEqual(detail.status_code, 200, detail.text)
        payload = detail.json()
        self.assertEqual(payload['email'], 'person@example.com')
        self.assertEqual(payload['items'][0]['question_id'], 'Q01')
        self.assertIn('session_intelligence', payload)
        self.assertIn('participant_handoff', payload)
        self.assertIn('admin_report', payload)
        admin_audit = self.client.get('/api/admin/audit').json()
        self.client.post('/api/auth/logout')
        self._login('person@example.com')
        participant_detail = self.client.get(f'/api/assessment/{session_id}')
        self.assertEqual(participant_detail.status_code, 200, participant_detail.text)
        self.assertNotIn('admin_report', participant_detail.json())
        self.assertNotIn('latest_admin_report', participant_detail.json().get('metadata', {}))
        self.assertTrue(any(row['action'] == 'READ' and row['session_id'] == session_id for row in admin_audit))

    def test_admin_overview_and_evidence_report_expose_review_priorities(self) -> None:
        self._register('owner@example.com')
        participant = self._register('person@example.com')
        self._login('person@example.com')
        started = self.client.post('/api/assessment/start')
        session_id = started.json()['id']
        submitted = self.client.post(
            f'/api/assessment/{session_id}/responses',
            json={'question_id': 'Q16', 'response': '责任'},
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(self.client.get('/api/admin/overview').status_code, 403)
        self.assertEqual(self.client.get(f'/api/admin/sessions/{session_id}/report').status_code, 403)

        # Make this seeded session an explicit expert-work example without
        # changing its item score or event history.
        self.audit.set_session_status(session_id, 'AWAITING_REVIEW')
        self.client.post('/api/auth/logout')
        self._login('owner@example.com')

        overview_response = self.client.get('/api/admin/overview')
        self.assertEqual(overview_response.status_code, 200, overview_response.text)
        overview = overview_response.json()
        self.assertEqual(overview['counts']['sessions'], 1)
        self.assertEqual(overview['counts']['awaiting_review'], 1)
        self.assertEqual(overview['recent_sessions'][0]['email'], 'person@example.com')
        self.assertEqual(overview['recent_sessions'][0]['user_id'], participant['id'])
        self.assertTrue(any(item['session_id'] == session_id and item['question_id'] == 'Q16' for item in overview['review_priorities']))

        report_response = self.client.get(f'/api/admin/sessions/{session_id}/report')
        self.assertEqual(report_response.status_code, 200, report_response.text)
        report = report_response.json()
        self.assertEqual(report['session_id'], session_id)
        self.assertEqual(len(report['item_matrix']), 20)
        self.assertIn('constructs', report)
        self.assertIn('timeline', report)
        self.assertIn('review_queue', report)
        self.assertEqual(next(row for row in report['item_matrix'] if row['question_id'] == 'Q16')['score']['preliminary'], submitted.json()['score']['preliminary_score'])
        audit = self.client.get('/api/admin/audit').json()
        self.assertTrue(any(row['resource'] == 'assessment_report' and row['session_id'] == session_id for row in audit))


if __name__ == '__main__':
    unittest.main()
