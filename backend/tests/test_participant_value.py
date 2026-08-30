from __future__ import annotations

import unittest

from backend.app.assessment.intelligence import build_participant_handoff


class ParticipantValueTest(unittest.TestCase):
    def test_handoff_explains_evidence_open_questions_and_next_steps(self) -> None:
        state = {
            'seed_answered': 20,
            'seed_total': 20,
            'probe_count': 1,
            'next_action': {'type': 'CLARIFY_NOW', 'question_id': 'Q16'},
            'constructs': [
                {'id': '人际负性体验', 'label': '人际负性体验', 'answered': 5, 'evidence_density': 0.8, 'status': 'EVIDENCED'},
                {'id': '生存意愿与未来想象', 'label': '生存意愿与未来想象', 'answered': 4, 'evidence_density': 0.5, 'status': 'NEEDS_REVIEW'},
            ],
            'unresolved_gaps': [{'question_id': 'Q16', 'status': 'PROVISIONAL', 'target_gap': '方向还没有听清'}],
            'cross_item_links': [{'type': 'SUPPORT'}],
        }
        handoff = build_participant_handoff(state, {'session_summary': '有几处回答彼此照见。'})
        self.assertEqual(handoff['mode'], 'PARTICIPANT_HANDOFF')
        self.assertTrue(handoff['what_i_heard'])
        self.assertTrue(handoff['still_open'])
        self.assertTrue(handoff['next_steps'])
        self.assertNotIn('风险等级', str(handoff))
        self.assertNotIn('诊断', str(handoff))

    def test_safety_handoff_uses_professional_path_without_playful_steps(self) -> None:
        state = {
            'seed_answered': 20,
            'seed_total': 20,
            'probe_count': 0,
            'next_action': {'type': 'SAFETY_FLOW'},
            'constructs': [],
            'unresolved_gaps': [],
            'cross_item_links': [],
        }
        handoff = build_participant_handoff(state, {})
        self.assertEqual(handoff['mode'], 'PROFESSIONAL_FLOW')
        self.assertEqual(handoff['next_steps'], [])
        self.assertIn('专业', handoff['message'])

    def test_handoff_prefers_bounded_ai_construct_insight_when_available(self) -> None:
        state = {
            'seed_answered': 20,
            'seed_total': 20,
            'probe_count': 0,
            'next_action': {'type': 'COMPLETE'},
            'constructs': [
                {'id': '人际负性体验', 'label': '人际负性体验', 'answered': 5, 'evidence_density': 0.8, 'status': 'EVIDENCED'},
            ],
            'unresolved_gaps': [],
        }
        handoff = build_participant_handoff(state, {
            'session_summary': '这次回答里，关于被需要与求助的感受出现了几次相互呼应。',
            'construct_insights': [
                {'group': '人际负性体验', 'summary': '几次回答都提到担心给亲近的人添麻烦。', 'status': 'EVIDENCED'},
            ],
        })
        self.assertEqual(handoff['what_i_heard'][0]['detail'], '几次回答都提到担心给亲近的人添麻烦。')


if __name__ == '__main__':
    unittest.main()
