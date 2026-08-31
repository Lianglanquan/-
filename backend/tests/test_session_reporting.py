from __future__ import annotations

import unittest

from backend.app.assessment.reporting import (
    build_population_summary,
    build_session_admin_report,
    build_session_evidence_report,
)


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

    def test_evidence_report_keeps_item_scores_local_and_exposes_session_planning(self) -> None:
        rubrics = {
            'Q03': {'question': '看到亲近的人为我付出时，我会______。', 'dimension': '人际负性体验 · 人际累赘感', 'version': '3.0.0'},
            'Q16': {'question': '牵挂更像是______。', 'dimension': '生存意愿与未来想象 · 生存理由丰富度', 'version': '3.0.0'},
        }
        session = {
            'id': 'session-1',
            'user_id': 'user-1',
            'status': 'AWAITING_REVIEW',
            'created_at': '2026-08-31T09:00:00+00:00',
            'updated_at': '2026-08-31T09:03:00+00:00',
            'items': [
                {
                    'event_id': 'event-1', 'question_id': 'Q03', 'event_type': 'INITIAL',
                    'response': '总觉得自己拖累他们', 'created_at': '2026-08-31T09:01:00+00:00',
                    'score': {
                        'preliminary_score': 2, 'score_status': 'CONFIRMED',
                        'evidence_sufficiency': 'SUFFICIENT', 'confidence': 0.88,
                        'evidence_spans': [{'text': '拖累', 'start': 5, 'end': 7, 'rule': '累赘感'}],
                        'rubric_version': '3.0.0',
                    },
                    'safety': {'state': 'CLEAR'},
                },
                {
                    'event_id': 'event-2', 'question_id': 'Q16', 'event_type': 'INITIAL',
                    'response': '责任', 'created_at': '2026-08-31T09:02:00+00:00',
                    'score': {
                        'preliminary_score': 1, 'score_status': 'PROVISIONAL',
                        'evidence_sufficiency': 'INSUFFICIENT', 'confidence': 0.42,
                        'target_gap': '方向还没有听清', 'rubric_version': '3.0.0',
                    },
                    'safety': {'state': 'CLEAR'},
                },
                {
                    'event_id': 'event-3', 'question_id': 'Q16', 'event_type': 'DISAMBIGUATION',
                    'probe_type': 'DISAMBIGUATION', 'response': '更像是必须承担的负担',
                    'created_at': '2026-08-31T09:03:00+00:00',
                    'score': {
                        'preliminary_score': 2, 'adjudicated_score': 1,
                        'original_preliminary_score': 2, 'score_status': 'CONFIRMED',
                        'evidence_sufficiency': 'SUFFICIENT', 'confidence': 0.77,
                        'rubric_version': '3.0.0',
                    },
                    'safety': {'state': 'CLEAR'},
                },
            ],
            'global_evidence': {
                'version': 'session-orchestrator-v1', 'seed_total': 2, 'seed_answered': 2,
                'probe_count': 1, 'next_action': {'type': 'HUMAN_REVIEW', 'question_id': 'Q16'},
                'constructs': [
                    {'id': '人际负性体验', 'label': '人际负性体验', 'score_mean': 2.0, 'evidence_density': 0.8, 'status': 'EVIDENCED', 'answered': 1},
                    {'id': '生存意愿与未来想象', 'label': '生存意愿与未来想象', 'score_mean': 1.0, 'evidence_density': 0.45, 'status': 'NEEDS_REVIEW', 'answered': 1},
                ],
                'nodes': [
                    {'question_id': 'Q03', 'support_count': 1, 'conflict_count': 0, 'priority': 0},
                    {'question_id': 'Q16', 'support_count': 1, 'conflict_count': 1, 'priority': 0.91, 'target_gap': '方向还没有听清'},
                ],
                'cross_item_links': [{'source': 'Q03', 'target': 'Q16', 'type': 'SUPPORT'}],
                'unresolved_gaps': [{'question_id': 'Q16', 'priority': 0.91, 'target_gap': '方向还没有听清', 'conflict_count': 1}],
            },
            'session_intelligence': {'model': 'session-advisor', 'session_summary': '人际体验与生存理由之间存在一处值得复核的张力。'},
            'decision_history': [
                {
                    'id': 'decision-1', 'event_id': 'event-2', 'created_at': '2026-08-31T09:02:01+00:00',
                    'deterministic_state': {'next_action': {'type': 'DEFER_CLARIFICATION', 'question_id': 'Q16'}},
                    'ai_analysis': {'planning_notes': ['先让后续回答自然补充。']},
                },
            ],
            'adjudications': {'Q16': {'status': 'ADJUDICATED', 'adjudicated_score': 1, 'evidence_sufficiency': 'SUFFICIENT'}},
        }

        report = build_session_evidence_report(session, rubrics)

        self.assertEqual(report['session_id'], 'session-1')
        self.assertEqual(len(report['item_matrix']), 2)
        q03 = next(row for row in report['item_matrix'] if row['question_id'] == 'Q03')
        q16 = next(row for row in report['item_matrix'] if row['question_id'] == 'Q16')
        self.assertEqual(q03['score']['effective'], 2)
        self.assertEqual(q16['score']['preliminary'], 2)
        self.assertEqual(q16['score']['effective'], 1)
        self.assertEqual(q16['relationships'], {'support_count': 1, 'conflict_count': 1})
        self.assertIn('不改变单题评分', q16['scoring_boundary'])
        self.assertEqual(report['constructs'][0]['pattern_level'], 'ELEVATED')
        self.assertEqual(report['constructs'][0]['evidence_quality'], 'HIGH')
        self.assertTrue(any(event['kind'] == 'PROBE' and event['question_id'] == 'Q16' for event in report['timeline']))
        self.assertTrue(any(event['kind'] == 'AI_PLAN' and event['action'] == 'DEFER_CLARIFICATION' for event in report['timeline']))
        self.assertEqual(report['probe_summary']['total'], 1)
        self.assertEqual(report['uncertainty']['conflict_links'], 1)
        self.assertEqual(report['review_queue'][0]['question_id'], 'Q16')
        self.assertEqual(report['versions']['orchestrator'], 'session-orchestrator-v1')
        self.assertEqual(report['versions']['rubric'], ['3.0.0'])


if __name__ == '__main__':
    unittest.main()
