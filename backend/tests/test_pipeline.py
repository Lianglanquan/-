from pathlib import Path
import os
import tempfile
import unittest

from backend.app.audit.store import AuditStore
from backend.app.assessment.orchestrator import build_global_evidence_state
from backend.app.assessment.intelligence import SessionAIAdvisor
from backend.app.assessment.probes import default_cat_probe, normalise_cat_probe
from backend.app.assessment.service import AssessmentStore
from backend.app.safety.engine import screen
from backend.app.scoring.centroid import CentroidScorer
from backend.app.scoring.engine import load_rubrics, score_response
from backend.app.scoring.providers import DeterministicBaseline
from backend.app.security import require_research_access


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rubrics = load_rubrics(Path(__file__).resolve().parents[2])

    def test_rubric_extraction_has_twenty_items(self) -> None:
        self.assertEqual(len(self.rubrics), 20)
        self.assertEqual(len(self.rubrics["Q01"]["criteria"]), 3)

    def test_ambiguous_response_is_provisional(self) -> None:
        result = score_response("Q16", "责任", self.rubrics)
        self.assertEqual(result.preliminary_score, 0)
        self.assertEqual(result.score_status, "PROVISIONAL")
        self.assertEqual(result.evidence_sufficiency, "INSUFFICIENT")
        self.assertTrue(result.clarification_question)

    def test_safety_is_independent(self) -> None:
        result = score_response("Q19", "我不想活了", self.rubrics)
        self.assertEqual(result.preliminary_score, 2)
        self.assertEqual(screen("我不想活了").state, "SAFETY_REVIEW")

    def test_short_adjective_item_is_not_globally_abstained(self) -> None:
        result = score_response("Q07", "困难", self.rubrics)
        self.assertEqual(result.score_status, "CONFIRMED")

    def test_numeric_item_requires_one_valid_number(self) -> None:
        self.assertEqual(score_response("Q20", "8", self.rubrics).score_status, "CONFIRMED")
        self.assertEqual(score_response("Q20", "不知道", self.rubrics).score_status, "PROVISIONAL")

    def test_centroid_model_is_auditable_and_local(self) -> None:
        model_path = Path(__file__).resolve().parents[2] / "models" / "supervised" / "char_centroid_v1.json"
        scorer = CentroidScorer(self.rubrics, model_path)
        result = scorer.score("Q16", "责任")
        self.assertEqual(result.evidence_sufficiency, "INSUFFICIENT")
        self.assertIn("per-item-char-ngram", scorer.model_name)

    def test_centroid_uncertainty_without_gap_goes_to_human_review(self) -> None:
        model_path = Path(__file__).resolve().parents[2] / "models" / "supervised" / "char_centroid_v1.json"
        scorer = CentroidScorer(self.rubrics, model_path)
        result = scorer.score("Q01", "今天")
        self.assertEqual(result.evidence_sufficiency, "SUFFICIENT")
        self.assertEqual(result.score_status, "HUMAN_REVIEW")
        self.assertTrue(result.review_recommended)

    def test_centroid_enforces_q20_numeric_rubric_rule(self) -> None:
        model_path = Path(__file__).resolve().parents[2] / "models" / "supervised" / "char_centroid_v1.json"
        scorer = CentroidScorer(self.rubrics, model_path)
        result = scorer.score("Q20", "8")
        self.assertEqual(result.preliminary_score, 1)
        self.assertEqual(result.score_status, "CONFIRMED")
        self.assertEqual(result.evidence_sufficiency, "SUFFICIENT")
        self.assertIn("Q20_NUMERIC_RULE", result.decision_reasons)

        chinese = scorer.score("Q20", "七分")
        self.assertEqual(chinese.preliminary_score, 1)
        self.assertEqual(chinese.score_status, "CONFIRMED")
        self.assertIn("Q20_NUMERIC_RULE", chinese.decision_reasons)

    def test_centroid_respects_unique_rubric_example(self) -> None:
        model_path = Path(__file__).resolve().parents[2] / "models" / "supervised" / "char_centroid_v1.json"
        scorer = CentroidScorer(self.rubrics, model_path)
        result = scorer.score("Q03", "感动")
        self.assertEqual(result.preliminary_score, 0)
        self.assertEqual(result.score_status, "CONFIRMED")
        self.assertIn("RUBRIC_EXACT_MATCH", result.decision_reasons)

    def test_audit_store_survives_reopen_and_records_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite3"
            first = AuditStore(path)
            session = first.create_session()
            first.append_event(session_id=session["id"], question_id="Q01", event_type="INITIAL", response="难过", clarification_round=0, payload={"score": {"preliminary_score": 1}})
            first.upsert_review_case({"response_id": "case-1", "source": "session", "question_id": "Q01", "response": "难过", "preliminary_score": 1, "score_status": "HUMAN_REVIEW", "evidence_sufficiency": "INSUFFICIENT", "reason_codes": ["TEST"], "payload": {}})
            reopened = AuditStore(path)
            self.assertEqual(len(reopened.get_session(session["id"])["items"]), 1)
            decision = reopened.record_review("case-1", adjudicated_score=1, evidence_sufficiency="SUFFICIENT", note="confirmed", reviewer="tester")
            self.assertEqual(decision["status"], "ADJUDICATED")
            self.assertEqual(reopened.get_review_case("case-1")["adjudicated_score"], 1)

    def test_research_access_requires_configured_token(self) -> None:
        previous = os.environ.get("RESEARCH_ACCESS_TOKEN")
        try:
            os.environ["RESEARCH_ACCESS_TOKEN"] = "unit-test-token"
            self.assertEqual(require_research_access("unit-test-token"), "researcher")
            with self.assertRaises(Exception):
                require_research_access("wrong-token")
        finally:
            if previous is None:
                os.environ.pop("RESEARCH_ACCESS_TOKEN", None)
            else:
                os.environ["RESEARCH_ACCESS_TOKEN"] = previous

    def test_assessment_cannot_skip_required_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            first = store.respond(session["id"], "Q16", "责任")
            self.assertEqual(first["score"]["score_status"], "PROVISIONAL")
            with self.assertRaises(ValueError):
                store.respond(session["id"], "Q16", "换一种说法", clarification=False)
            with self.assertRaises(ValueError):
                store.respond(session["id"], "Q16", "支持", clarification=True)

    def test_safety_gated_assessment_cannot_use_adaptive_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            first = store.respond(session["id"], "Q19", "我不想活了")
            self.assertEqual(first["score"]["safety_state"], "SAFETY_REVIEW")
            self.assertIsNone(first["score"].get("cat_probe"))
            with self.assertRaises(ValueError):
                store.respond(session["id"], "Q19", "我想补充", clarification=True)
            with self.assertRaises(ValueError):
                store.respond(session["id"], "Q20", "4")

    def test_session_orchestrator_defers_early_gap(self) -> None:
        items = [{
            "event_id": "e1", "question_id": "Q16", "event_type": "INITIAL", "response": "责任",
            "score": {"preliminary_score": 0, "score_status": "PROVISIONAL", "evidence_sufficiency": "INSUFFICIENT", "confidence": 0.48, "decision_reasons": ["ABSTRACT_OR_DIRECTION_UNKNOWN"], "target_gap": "方向不明确", "clarification_question": "更像支持还是负担？"},
            "safety": {"state": "CLEAR"},
        }]
        state = build_global_evidence_state(items=items, rubrics=self.rubrics, current_question_id="Q16")
        self.assertEqual(state["next_action"]["type"], "DEFER_CLARIFICATION")
        self.assertEqual(state["next_action"]["probe_type"], "DISAMBIGUATION")

    def test_session_orchestrator_prioritizes_cross_item_node(self) -> None:
        items = []
        for index, question_id in enumerate(("Q01", "Q02", "Q03", "Q05", "Q07"), start=1):
            score = 2 if question_id in {"Q03", "Q05", "Q07"} else 1
            items.append({
                "event_id": f"e{index}", "question_id": question_id, "event_type": "INITIAL", "response": "有语义证据",
                "score": {"preliminary_score": score, "score_status": "CONFIRMED", "evidence_sufficiency": "SUFFICIENT", "confidence": 0.8, "decision_reasons": []},
                "safety": {"state": "CLEAR"},
            })
        items.append({
            "event_id": "e6", "question_id": "Q16", "event_type": "INITIAL", "response": "责任",
            "score": {"preliminary_score": 0, "score_status": "PROVISIONAL", "evidence_sufficiency": "INSUFFICIENT", "confidence": 0.48, "decision_reasons": ["ABSTRACT_OR_DIRECTION_UNKNOWN"], "target_gap": "方向不明确", "clarification_question": "更像支持还是负担？"},
            "safety": {"state": "CLEAR"},
        })
        state = build_global_evidence_state(items=items, rubrics=self.rubrics, current_question_id="Q16")
        self.assertEqual(state["next_action"]["type"], "CLARIFY_NOW")
        self.assertEqual(state["next_action"]["question_id"], "Q16")
        q16 = next(node for node in state["nodes"] if node["question_id"] == "Q16")
        self.assertGreaterEqual(q16["conflict_count"], 1)
        self.assertIn("Q03", {link["target_question_id"] for link in state["cross_item_links"] if link["source_question_id"] == "Q16"})

    def test_session_orchestrator_uses_confirmation_for_high_priority_uncertainty(self) -> None:
        items = []
        for index, question_id in enumerate(("Q01", "Q02", "Q03", "Q05", "Q07"), start=1):
            items.append({
                "event_id": f"e{index}", "question_id": question_id, "event_type": "INITIAL", "response": "清楚的回答",
                "score": {"preliminary_score": 1, "score_status": "CONFIRMED", "evidence_sufficiency": "SUFFICIENT", "confidence": 0.8, "decision_reasons": []},
                "safety": {"state": "CLEAR"},
            })
        items.append({
            "event_id": "e6", "question_id": "Q19", "event_type": "INITIAL", "response": "害怕",
            "score": {"preliminary_score": 2, "score_status": "HUMAN_REVIEW", "evidence_sufficiency": "SUFFICIENT", "confidence": 0.4, "decision_reasons": ["MODEL_UNCERTAINTY"]},
            "safety": {"state": "CLEAR"},
        })
        state = build_global_evidence_state(items=items, rubrics=self.rubrics, current_question_id="Q19")
        self.assertEqual(state["next_action"]["type"], "CONFIRM_NOW")
        self.assertEqual(state["next_action"]["probe_type"], "CONFIRMATION")

    def test_session_ai_advisor_refines_only_pending_probe_and_is_auditable(self) -> None:
        class FakeSessionModel:
            name = "fake-session-model"
            model = "fake-session-v1"

            def analyze_session(self, snapshot, state):
                return {
                    "session_summary": "Q16 是当前关键未决节点。",
                    "construct_insights": [{
                        "group": "生存意愿与未来想象",
                        "summary": "Q16 需要澄清牵挂的方向。",
                        "status": "NEEDS_REVIEW",
                        "confidence": 0.82,
                        "evidence_question_ids": ["Q16", "Q03"],
                        "unresolved_question_ids": ["Q16"],
                    }],
                    "cross_item_hypotheses": [{
                        "question_ids": ["Q03", "Q16"], "type": "SUPPORT",
                        "rationale": "两题都涉及他人付出与牵挂。", "confidence": 0.8,
                    }],
                    "probe_recommendations": [{
                        "question_id": "Q16", "probe_type": "DISAMBIGUATION",
                        "question": "这份责任感更像支持、负担，还是两者都有？",
                        "rationale": "先澄清语义方向。", "confidence": 0.9,
                        "priority_adjustment": 0.08,
                    }, {
                        "question_id": "Q01", "probe_type": "CONFIRMATION",
                        "question": "不应被接受的探针。", "rationale": "invalid target", "confidence": 1.0,
                    }],
                    "recommended_action": {
                        "type": "CLARIFY_NOW", "question_id": "Q16", "probe_type": "DISAMBIGUATION",
                        "question": "这份责任感更像支持、负担，还是两者都有？",
                        "rationale": "Q16 是当前最值得求证的节点。", "confidence": 0.91,
                    },
                    "planning_notes": ["只参与规划，不改分。"],
                }

        items = []
        for index, question_id in enumerate(("Q01", "Q02", "Q03", "Q05", "Q07"), start=1):
            items.append({
                "event_id": f"e{index}", "question_id": question_id, "event_type": "INITIAL", "response": "清楚的回答",
                "score": {"preliminary_score": 2 if question_id in {"Q03", "Q05", "Q07"} else 1, "score_status": "CONFIRMED", "evidence_sufficiency": "SUFFICIENT", "confidence": 0.8, "decision_reasons": []},
                "safety": {"state": "CLEAR"},
            })
        items.append({
            "event_id": "e6", "question_id": "Q16", "event_type": "INITIAL", "response": "责任",
            "score": {"preliminary_score": 0, "score_status": "PROVISIONAL", "evidence_sufficiency": "INSUFFICIENT", "confidence": 0.48, "decision_reasons": ["ABSTRACT_OR_DIRECTION_UNKNOWN"], "target_gap": "方向不明确", "clarification_question": "牵挂更像支持还是负担？"},
            "safety": {"state": "CLEAR"},
        })
        deterministic = build_global_evidence_state(items=items, rubrics=self.rubrics, current_question_id="Q16")
        advisor = SessionAIAdvisor(FakeSessionModel())
        advice = advisor.advise(items=items, rubrics=self.rubrics, state=deterministic)
        self.assertEqual(advice["status"], "AI_ADVISORY")
        self.assertEqual(len(advice["probe_recommendations"]), 1)
        from backend.app.assessment.intelligence import apply_ai_planning
        enriched = apply_ai_planning(deterministic, advice)
        self.assertEqual(enriched["next_action"]["question_id"], "Q16")
        self.assertEqual(enriched["next_action"]["question"], "这份责任感更像支持、负担，还是两者都有？")
        self.assertTrue(enriched["decision_trace"]["ai_used"])
        self.assertEqual(next(node for node in enriched["nodes"] if node["question_id"] == "Q16")["preliminary_score"], 0)

    def test_assessment_persists_session_ai_decision_history(self) -> None:
        class FakeSessionModel:
            name = "fake-session-model"
            model = "fake-session-v1"

            def analyze_session(self, snapshot, state):
                return {
                    "session_summary": "已记录一次会话级规划。",
                    "probe_recommendations": [],
                    "cross_item_hypotheses": [],
                    "construct_insights": [],
                    "recommended_action": None,
                    "planning_notes": [],
                }

        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2], ai_advisor=SessionAIAdvisor(FakeSessionModel()))
            session = store.start()
            result = store.respond(session["id"], "Q16", "责任")
            self.assertEqual(result["session_intelligence"]["status"], "AI_ADVISORY")
            stored = audit.get_session(session["id"])
            self.assertEqual(len(stored["decision_history"]), 1)
            self.assertEqual(stored["metadata"]["latest_ai_analysis"]["model"], "fake-session-v1")

    def test_session_get_is_json_serializable_after_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            store.respond(session["id"], "Q16", "责任")
            value = store.get(session["id"])
            self.assertIsNotNone(value)
            encoded = __import__("json").dumps(value, ensure_ascii=False)
            self.assertIn("session_intelligence", encoded)

    def test_expert_adjudication_folds_into_effective_session_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            event_id = audit.append_event(
                session_id=session["id"], question_id="Q01", event_type="INITIAL", response="今天",
                clarification_round=0, payload={"score": {"preliminary_score": 0, "score_status": "HUMAN_REVIEW", "evidence_sufficiency": "SUFFICIENT", "confidence": 0.4, "decision_reasons": ["MODEL_UNCERTAINTY"]}, "safety": {"state": "CLEAR"}},
            )
            audit.upsert_review_case({
                "response_id": f"session:{session['id']}:Q01", "source": "session", "session_id": session["id"], "event_id": event_id,
                "question_id": "Q01", "response": "今天", "preliminary_score": 0, "score_status": "HUMAN_REVIEW",
                "evidence_sufficiency": "SUFFICIENT", "reason_codes": ["MODEL_UNCERTAINTY"], "payload": {},
            })
            decision = audit.record_review(f"session:{session['id']}:Q01", adjudicated_score=1, evidence_sufficiency="SUFFICIENT", note="明确为中度", reviewer="expert")
            self.assertEqual(decision["status"], "ADJUDICATED")
            value = store.get(session["id"])
            item = next(item for item in value["items"] if item["question_id"] == "Q01")
            self.assertEqual(item["score"]["original_preliminary_score"], 0)
            self.assertEqual(item["score"]["adjudicated_score"], 1)
            node = next(node for node in value["global_evidence"]["nodes"] if node["question_id"] == "Q01")
            self.assertEqual(node["status"], "CONFIRMED")
            self.assertEqual(node["preliminary_score"], 0)
            self.assertEqual(node["effective_score"], 1)

    def test_adjudicated_dataset_export_contains_only_confirmed_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            session = audit.create_session()
            audit.upsert_review_case({
                "response_id": "case-1", "source": "session", "session_id": session["id"], "question_id": "Q01", "response": "清楚",
                "preliminary_score": 0, "score_status": "HUMAN_REVIEW", "evidence_sufficiency": "SUFFICIENT", "reason_codes": [],
                "payload": {"score": {"rubric_version": "1.0.0"}},
            })
            audit.record_review("case-1", adjudicated_score=0, evidence_sufficiency="SUFFICIENT", note="ok", reviewer="expert")
            path = Path(directory) / "adjudicated_dataset.jsonl"
            report = audit.export_adjudicated_dataset(path)
            self.assertEqual(report["records"], 1)
            row = __import__("json").loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["adjudicated_score"], 0)
            self.assertEqual(row["preliminary_score"], 0)

    def test_cat_probe_is_warm_neutral_and_has_exit_paths(self) -> None:
        probe = default_cat_probe(question_id="Q16", probe_type="DISAMBIGUATION", target_gap="牵挂的正负方向还不明确", response="责任")
        self.assertEqual(probe["version"], "cat-companion-probe-v1")
        self.assertIn("轻轻放在这里", probe["cat_reflection"])
        self.assertIn("也可能是我听偏了", probe["cat_humility"])
        ids = {option["id"] for option in probe["options"]}
        self.assertIn("other", ids)
        self.assertIn("not_ready", ids)
        self.assertTrue(probe["response_optional"])

    def test_every_seed_probe_has_real_semantic_cat_paths(self) -> None:
        for question_id in self.rubrics:
            probe = default_cat_probe(
                question_id=question_id,
                probe_type="DISAMBIGUATION",
                target_gap="方向还不明确",
                response="几个字",
            )
            ids = {option["id"] for option in probe["options"]}
            self.assertGreaterEqual(len(ids - {"other", "not_ready"}), 2, question_id)
            self.assertIn("other", ids, question_id)
            self.assertIn("not_ready", ids, question_id)

    def test_cat_probe_rejects_scoring_or_risk_language_in_ai_options(self) -> None:
        probe = normalise_cat_probe({
            "options": [
                {"id": "score2", "label": "2分明显高风险"},
                {"id": "okay", "label": "我想自己说"},
            ],
        }, question_id="Q16", probe_type="DISAMBIGUATION", target_gap="方向不明确", response="责任")
        labels = {option["id"] for option in probe["options"]}
        self.assertNotIn("score2", labels)
        self.assertIn("other", labels)
        self.assertIn("not_ready", labels)

    def test_cat_probe_rejects_scoring_language_in_companion_copy(self) -> None:
        probe = normalise_cat_probe({
            "cat_reflection": "这看起来是 2 分，属于高风险。",
            "cat_tentative_understanding": "我先替你判断风险等级。",
            "cat_humility": "也许我听偏了。",
        }, question_id="Q16", probe_type="DISAMBIGUATION", target_gap="方向不明确", response="责任")
        self.assertNotIn("2 分", probe["cat_reflection"])
        self.assertNotIn("风险等级", probe["cat_tentative_understanding"])
        self.assertIn("轻轻放在这里", probe["cat_reflection"])

    def test_ai_authored_cat_probe_is_forwarded_to_participant_action(self) -> None:
        class FakeSessionModel:
            name = "fake-session-model"
            model = "fake-session-v1"

            def analyze_session(self, snapshot, state):
                return {
                    "session_summary": "Q16 需要被温柔地再确认一次。",
                    "construct_insights": [],
                    "cross_item_hypotheses": [],
                    "probe_recommendations": [{
                        "question_id": "Q16", "probe_type": "DISAMBIGUATION",
                        "question": "你愿意说说它更靠近哪一种感受吗？",
                        "rationale": "给语义留一点空间。", "confidence": 0.9,
                        "priority_adjustment": 0.0,
                        "cat_probe": {
                            "cat_reflection": "我把这句话放在这里，陪你一起看。",
                            "cat_tentative_understanding": "我还没想替你把它定成一个方向。",
                            "cat_humility": "如果我听错了，你可以把我带回来。",
                            "cat_invitation": "你想从哪一边开始说？",
                            "options": [
                                {"id": "near", "label": "更靠近第一种感觉"},
                                {"id": "far", "label": "更靠近另一种感觉"},
                            ],
                        },
                    }],
                    "recommended_action": {
                        "type": "CLARIFY_NOW", "question_id": "Q16", "probe_type": "DISAMBIGUATION",
                        "question": "你愿意说说它更靠近哪一种感受吗？",
                        "rationale": "给语义留一点空间。", "confidence": 0.9,
                    },
                    "planning_notes": [],
                }

        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(
                self.rubrics,
                scorer=DeterministicBaseline(self.rubrics),
                audit=audit,
                root=Path(__file__).resolve().parents[2],
                ai_advisor=SessionAIAdvisor(FakeSessionModel()),
            )
            session = store.start()
            first = store.respond(session["id"], "Q16", "责任")
            self.assertEqual(first["next_action"]["type"], "DEFER_CLARIFICATION")
            # Supply enough seed context for the same pending node to become
            # eligible immediately, then verify the AI companion copy reaches
            # the action without changing the item score.
            for question_id, response in (("Q01", "平静"), ("Q02", "很开心"), ("Q03", "心疼他们"), ("Q05", "离开我")):
                store.respond(session["id"], question_id, response)
            current = store.get(session["id"])
            self.assertEqual(current["next_action"]["question_id"], "Q16")
            self.assertEqual(current["next_action"]["interaction"]["cat_reflection"], "我把这句话放在这里，陪你一起看。")
            q16 = next(node for node in current["global_evidence"]["nodes"] if node["question_id"] == "Q16")
            self.assertEqual(q16["preliminary_score"], 0)

    def test_probe_protocol_rejects_mismatched_probe_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            first = store.respond(session["id"], "Q16", "责任")
            with self.assertRaises(ValueError):
                store.respond(
                    session["id"], "Q16", "我想补充",
                    clarification=True,
                    probe_type="CONFIRMATION",
                    probe_option_id="other",
                )

    def test_other_probe_option_requires_participant_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            store.respond(session["id"], "Q16", "责任")
            for question_id, response in (("Q01", "平静"), ("Q02", "很开心"), ("Q03", "心疼他们"), ("Q05", "离开我")):
                store.respond(session["id"], question_id, response)
            action = store.get(session["id"])["next_action"]
            self.assertEqual(action["question_id"], "Q16")
            with self.assertRaises(ValueError):
                store.respond(
                    session["id"], "Q16", "",
                    clarification=True,
                    probe_type=action["probe_type"],
                    probe_option_id="other",
                )

    def test_reserved_probe_exits_keep_protocol_meaning(self) -> None:
        probe = normalise_cat_probe({
            "options": [
                {"id": "other", "label": "请按我的理解打分"},
                {"id": "not_ready", "label": "我现在很危险"},
                {"id": "one", "label": "一种可能"},
                {"id": "two", "label": "另一种可能"},
            ],
        }, question_id="Q16", probe_type="DISAMBIGUATION", target_gap="方向不明确", response="责任")
        by_id = {option["id"]: option["label"] for option in probe["options"]}
        self.assertEqual(by_id["other"], "都不太像，我想自己说")
        self.assertEqual(by_id["not_ready"], "今天先放在这里")

    def test_pausing_an_adaptive_probe_records_choice_without_rescoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = AuditStore(Path(directory) / "audit.sqlite3")
            store = AssessmentStore(self.rubrics, audit=audit, root=Path(__file__).resolve().parents[2])
            session = store.start()
            first = store.respond(session["id"], "Q16", "责任")
            # Make the action immediately eligible without requiring five seed answers.
            for question_id, response in (("Q01", "平静"), ("Q02", "很开心"), ("Q03", "心疼他们"), ("Q05", "离开我")):
                store.respond(session["id"], question_id, response)
            state = store.get(session["id"])
            action = state["next_action"]
            target = action["question_id"]
            if target != "Q16":
                # The deterministic policy may select a higher-priority model
                # uncertainty; create a fresh session with the intended Q16
                # context instead of weakening the production guardrail.
                session = store.start()
                store.respond(session["id"], "Q01", "平静")
                store.respond(session["id"], "Q02", "很开心")
                store.respond(session["id"], "Q03", "心疼他们")
                store.respond(session["id"], "Q05", "离开我")
                store.respond(session["id"], "Q07", "困难")
                store.respond(session["id"], "Q16", "责任")
                state = store.get(session["id"])
                action = state["next_action"]
                target = action["question_id"]
            self.assertEqual(target, "Q16")
            paused = store.respond(session["id"], "Q16", "今天先放在这里", clarification=True, probe_type=action["probe_type"], probe_option_id="not_ready", probe_action="PAUSE")
            self.assertEqual(paused["clarification"], True)
            stored = audit.get_session(session["id"])
            self.assertEqual(stored["items"][-1]["event_type"], "PROBE_PAUSED")
            self.assertEqual(stored["items"][-1]["probe_option_id"], "not_ready")


if __name__ == "__main__":
    unittest.main()
