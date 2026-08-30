from __future__ import annotations

import unittest

from backend.app.assessment.reporting import build_population_summary, build_session_admin_report


class SessionReportingTest(unittest.TestCase):
    def test_session_report_has_total_score_risk_band_and_reviewable_recommendation(self) -> None:
        items = [
            {'question_id': 'Q01', 'event_type': 'INITIAL', 'score': {'preliminary_score': 2, 'score_status': 'CONFIRMED', 'confidence': 0.8}, 'safety': {'state': 'CLEAR'}},
            {'question_id': 'Q02', 'event_type': 'INITIAL', 'score': {'preliminary_score': 1, 'score_status': 'PROVISIONAL', 'confidence': 0.4}, 'safety': {'state': 'CLEAR'}},
            {'question_id': 'Q02', 'event_type': 'CLARIFICATION', 'score': {'preliminary_score': 2, 'score_status': 'HUMAN_REVIEW', 'confidence': 0.3}, 'safety': {'state': 'CLEAR'}},
        ]
        report = build_session_admin_report(items, seed_total=20)
        self.assertEqual(report['total_score'], 4)
        self.assertEqual(report['answered'], 2)
        self.assertEqual(report['score_counts'], {'0': 0, '1': 0, '2': 2})
        self.assertEqual(report['risk_level'], 'INCOMPLETE')
        self.assertIn('人工', report['intervention_recommendation'])
        self.assertIn('研究规则', report['disclaimer'])

    def test_safety_session_is_always_promoted_to_safety_review(self) -> None:
        report = build_session_admin_report([
            {'question_id': 'Q19', 'event_type': 'INITIAL', 'score': {'preliminary_score': 0, 'score_status': 'HUMAN_REVIEW', 'confidence': 0.9}, 'safety': {'state': 'SAFETY_REVIEW'}},
        ], seed_total=20)
        self.assertEqual(report['risk_level'], 'SAFETY_REVIEW')
        self.assertIn('专业', report['intervention_recommendation'])

    def test_population_summary_counts_participants_by_rule_band(self) -> None:
        records = [
            *({'participant_id': 'a', 'question_id': f'Q{i:02d}', 'legacy_score': 0} for i in range(1, 21)),
            *({'participant_id': 'b', 'question_id': f'Q{i:02d}', 'legacy_score': 2} for i in range(1, 21)),
        ]
        summary = build_population_summary(records, seed_total=20)
        self.assertEqual(summary['participants'], 2)
        self.assertEqual(summary['risk_counts']['LOW'], 1)
        self.assertEqual(summary['risk_counts']['HIGH'], 1)
        self.assertEqual(summary['overall_mean_score'], 1.0)


if __name__ == '__main__':
    unittest.main()
