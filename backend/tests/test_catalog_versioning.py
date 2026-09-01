from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.audit.store import AuditStore
from backend.app.assessment.reporting import build_session_evidence_report
from backend.app.assessment.service import AssessmentStore
from backend.app.scoring.catalog import (
    ACTIVE_CATALOG_VERSION,
    ACTIVE_SEED_TOTAL,
    LEGACY_CATALOG_VERSION,
    load_catalog,
)
from backend.app.scoring.engine import load_active_rubrics
from backend.app.scoring.centroid import CentroidScorer


ROOT = Path(__file__).resolve().parents[2]


class CatalogVersioningTest(unittest.TestCase):
    def test_active_catalog_has_nineteen_items_and_two_public_dimensions(self) -> None:
        catalog = load_catalog(ROOT, ACTIVE_CATALOG_VERSION)
        self.assertEqual(catalog.version, ACTIVE_CATALOG_VERSION)
        self.assertEqual(catalog.seed_total, ACTIVE_SEED_TOTAL)
        self.assertEqual(list(catalog.rubrics), [f"Q{i:02d}" for i in range(1, 20)])
        self.assertNotIn("Q20", catalog.rubrics)
        self.assertEqual(catalog.rubrics["Q16"]["question"], "如果让我描述一下五年后的今天自己正在做什么，我心里下意识想到的是______。")
        self.assertEqual(catalog.rubrics["Q01"]["dimension"], "情绪状态与人际联结")
        self.assertEqual(catalog.rubrics["Q19"]["dimension"], "自我认知与绝望感")

    def test_legacy_catalog_preserves_removed_q16_and_q20(self) -> None:
        catalog = load_catalog(ROOT, LEGACY_CATALOG_VERSION)
        self.assertEqual(catalog.seed_total, 20)
        self.assertIn("Q16", catalog.rubrics)
        self.assertIn("Q20", catalog.rubrics)
        self.assertIn("牵挂", catalog.rubrics["Q16"]["question"])

    def test_new_session_report_uses_nineteen_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(load_active_rubrics(ROOT), audit=audit, root=ROOT)
            session = store.start()
            self.assertEqual(session["metadata"]["catalog_version"], ACTIVE_CATALOG_VERSION)
            self.assertEqual(session["metadata"]["seed_total"], 19)
            report = build_session_evidence_report(store.get(session["id"]), load_active_rubrics(ROOT))
            self.assertEqual(report["overview"]["seed_total"], 19)
            self.assertEqual(len(report["item_matrix"]), 19)

    def test_active_q19_keeps_legacy_q20_numeric_rule(self) -> None:
        model_path = ROOT / "models" / "supervised" / "char_centroid_v1.json"
        scorer = CentroidScorer(load_active_rubrics(ROOT), model_path)
        result = scorer.score("Q19", "8")
        self.assertEqual(result.preliminary_score, 1)
        self.assertEqual(result.score_status, "CONFIRMED")
        self.assertIn("Q20_NUMERIC_RULE", result.decision_reasons)

    def test_legacy_session_report_keeps_twenty_item_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(load_active_rubrics(ROOT), audit=audit, root=ROOT)
            session = audit.create_session(catalog_version=LEGACY_CATALOG_VERSION, seed_total=20)
            report = build_session_evidence_report(store.get(session["id"]), load_catalog(ROOT, LEGACY_CATALOG_VERSION).rubrics)
            self.assertEqual(report["overview"]["seed_total"], 20)
            self.assertEqual(len(report["item_matrix"]), 20)
            self.assertIn("牵挂", next(item for item in report["item_matrix"] if item["question_id"] == "Q16")["question"])


if __name__ == "__main__":
    unittest.main()
