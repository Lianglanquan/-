import unittest

from backend.app.scoring.engine import ScoreResult
from scripts.run_debug_experiment import compute_consistency_summary, score_record


class FakeScorer:
    name = "fake-provider"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = []

    def score(self, question_id: str, response: str) -> ScoreResult:
        self.calls.append((question_id, response))
        return ScoreResult(
            question_id=question_id,
            response=response,
            preliminary_score=0,
            score_status="CONFIRMED",
            evidence_sufficiency="SUFFICIENT",
            rationale="按题目规则，回答指向具体可行的调整。",
            evidence_spans=[],
            confidence=0.9,
            rubric_version="1.0.0",
        )


class DebugExperimentTest(unittest.TestCase):
    def test_score_record_keeps_legacy_annotations_out_of_provider_input(self) -> None:
        scorer = FakeScorer()
        row = score_record(
            {
                "response_id": "p1:A1",
                "participant_id": "p1",
                "question_id": "Q09",
                "source_question_code": "A1",
                "response": "这次方法没用对，下次换一种方式。",
                "legacy_score": 0,
                "legacy_rationale": "历史人工理由，不应传入模型",
            },
            {},
            scorer,
        )
        self.assertEqual(scorer.calls, [("Q09", "这次方法没用对，下次换一种方式。")])
        self.assertEqual(row["legacy_score"], 0)
        self.assertEqual(row["ai_score"], 0)
        self.assertEqual(row["agreement"], "一致")

    def test_consistency_summary_reports_accuracy_and_confusion(self) -> None:
        summary = compute_consistency_summary([
            {"question_id": "Q01", "legacy_score": 0, "ai_score": 0, "ai_score_status": "CONFIRMED", "ai_evidence_sufficiency": "SUFFICIENT", "safety_state": "CLEAR"},
            {"question_id": "Q01", "legacy_score": 1, "ai_score": 0, "ai_score_status": "PROVISIONAL", "ai_evidence_sufficiency": "INSUFFICIENT", "safety_state": "CLEAR"},
            {"question_id": "Q02", "legacy_score": 2, "ai_score": 2, "ai_score_status": "CONFIRMED", "ai_evidence_sufficiency": "SUFFICIENT", "safety_state": "CLEAR"},
        ])
        self.assertEqual(summary["n"], 3)
        self.assertAlmostEqual(summary["accuracy"], 2 / 3)
        self.assertEqual(summary["confusion"]["1->0"], 1)
        self.assertEqual(summary["selective"]["covered"], 2)


if __name__ == "__main__":
    unittest.main()
