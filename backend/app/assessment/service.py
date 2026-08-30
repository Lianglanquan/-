"""Persistent assessment orchestration for the research prototype."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from typing import Any

from backend.app.audit.store import AuditStore
from backend.app.assessment.intelligence import SessionAIAdvisor, apply_ai_planning
from backend.app.assessment.orchestrator import build_global_evidence_state, infer_probe_type
from backend.app.assessment.probes import default_cat_probe
from backend.app.safety.engine import screen
from backend.app.scoring.engine import CatProbe, ScoreResult, score_response
from backend.app.scoring.llm import score_with_configured_provider


class AssessmentStore:
    def __init__(
        self,
        rubrics: dict[str, dict[str, Any]],
        scorer: Any = None,
        *,
        audit: AuditStore | None = None,
        root: Path | None = None,
        ai_advisor: SessionAIAdvisor | None = None,
    ) -> None:
        self.rubrics = rubrics
        self.scorer = scorer
        workspace = root or Path(__file__).resolve().parents[3]
        self.audit = audit or AuditStore(workspace / "data" / "derived" / "audit.sqlite3")
        self.ai_advisor = ai_advisor or SessionAIAdvisor(scorer)

    def start(self) -> dict[str, Any]:
        return self.audit.create_session()

    def _latest_initial(self, session_id: str, question_id: str) -> dict[str, Any] | None:
        session = self.audit.get_session(session_id)
        if not session:
            return None
        for item in reversed(session["items"]):
            if item["question_id"] == question_id and item["event_type"] == "INITIAL":
                return item
        return None

    def _latest_item(self, session_id: str, question_id: str) -> dict[str, Any] | None:
        session = self.audit.get_session(session_id)
        if not session:
            return None
        for item in reversed(session["items"]):
            if item["question_id"] == question_id:
                return item
        return None

    def _score(self, question_id: str, response: str) -> tuple[ScoreResult, str]:
        return score_with_configured_provider(question_id, response, self.rubrics, self.scorer)

    def _fold_adjudications(self, session: dict[str, Any]) -> dict[str, Any]:
        """Expose expert decisions as a separate effective evidence layer.

        The original event score remains recoverable in ``original_*`` fields;
        an adjudication is never a destructive overwrite of a legacy label or
        the append-only event payload.
        """

        decisions = self.audit.session_adjudications(session["id"])
        latest_by_question = {}
        for item in session.get("items", []):
            latest_by_question[item.get("question_id")] = item.get("event_id")
        for item in session.get("items", []):
            decision = decisions.get(item.get("question_id"))
            if not decision:
                continue
            # A review case is item-level adjudication. Apply it to the latest
            # event for that question so a prior initial case still resolves
            # the node after a confirmation probe has been recorded.
            if latest_by_question.get(item.get("question_id")) != item.get("event_id"):
                continue
            item["adjudication"] = decision
            score = item.get("score")
            if not isinstance(score, dict):
                continue
            score.setdefault("original_preliminary_score", score.get("preliminary_score"))
            score.setdefault("original_score_status", score.get("score_status"))
            score.setdefault("original_evidence_sufficiency", score.get("evidence_sufficiency"))
            if decision.get("status") == "ADJUDICATED" and decision.get("adjudicated_score") in (0, 1, 2):
                score["adjudicated_score"] = decision["adjudicated_score"]
                score["adjudicated_evidence_sufficiency"] = decision.get("evidence_sufficiency")
                score["score_status"] = "CONFIRMED"
                score["evidence_sufficiency"] = "SUFFICIENT"
                score["decision_reasons"] = list(dict.fromkeys([*(score.get("decision_reasons") or []), "EXPERT_ADJUDICATED"]))
                score["review_recommended"] = False
            elif decision.get("status") == "UNRESOLVED":
                score["decision_reasons"] = list(dict.fromkeys([*(score.get("decision_reasons") or []), "EXPERT_UNRESOLVED"]))
        session["adjudications"] = decisions
        return session

    def _force_human_review(self, result: ScoreResult, reason: str) -> ScoreResult:
        reasons = list(result.decision_reasons)
        if reason not in reasons:
            reasons.append(reason)
        result.score_status = "HUMAN_REVIEW"
        result.clarification_question = None
        result.decision_reasons = reasons
        result.review_recommended = True
        return result

    def respond(
        self,
        session_id: str,
        question_id: str,
        response: str,
        clarification: bool = False,
        probe_type: str | None = None,
        probe_option_id: str | None = None,
        probe_action: str = "ANSWER",
    ) -> dict[str, Any]:
        if not self.audit.session_exists(session_id):
            raise KeyError(session_id)
        if not clarification and probe_type:
            raise ValueError("probe_type is only valid for an adaptive probe")
        if not clarification and (probe_option_id or probe_action != "ANSWER"):
            raise ValueError("probe options are only valid for an adaptive probe")
        probe_action = str(probe_action or "ANSWER").upper()
        if probe_action not in {"ANSWER", "PAUSE"}:
            raise ValueError("probe_action must be ANSWER or PAUSE")
        base = self._latest_initial(session_id, question_id)
        latest = self._latest_item(session_id, question_id)
        if clarification:
            if not base:
                raise ValueError("clarification requires an existing initial response")
            if latest and (latest.get("safety", {}) or {}).get("state") != "CLEAR":
                raise ValueError("safety-gated responses cannot use automatic clarification")
            before = self.audit.get_session(session_id)
            planned = build_global_evidence_state(
                items=before["items"] if before else [],
                rubrics=self.rubrics,
                current_question_id=question_id,
            )["next_action"]
            latest_score = (latest or {}).get("score") or {}
            if latest_score.get("score_status") not in {"PROVISIONAL", "HUMAN_REVIEW"}:
                raise ValueError("no adaptive probe is pending for this response")
            if planned.get("question_id") != question_id or planned.get("type") not in {"CLARIFY_NOW", "CONFIRM_NOW"}:
                raise ValueError("this probe is deferred until the orchestrator selects it")
            interaction = planned.get("interaction") or default_cat_probe(
                question_id=question_id,
                probe_type=str(planned.get("probe_type") or infer_probe_type(latest_score)),
                target_gap=latest_score.get("target_gap"),
                response=str(base.get("response", "")),
            )
            selected_option = None
            planned_probe_type = str(planned.get("probe_type") or infer_probe_type(latest_score))
            if probe_type and probe_type != planned_probe_type:
                raise ValueError("probe_type does not match the orchestrator's selected probe")
            if probe_option_id:
                selected_option = next((option for option in (interaction or {}).get("options", []) if option.get("id") == probe_option_id), None)
                if selected_option is None:
                    raise ValueError("probe_option_id is not available for the selected adaptive probe")
            if probe_action == "PAUSE" and probe_option_id != "not_ready":
                raise ValueError("pause requires the not_ready probe option")
            if probe_option_id == "not_ready" and probe_action != "PAUSE":
                raise ValueError("the not_ready probe option must pause the probe")
            if probe_option_id == "other" and (
                not response.strip()
                or response.strip() == str((selected_option or {}).get("label", "")).strip()
            ):
                raise ValueError("the other probe option requires a free-text explanation")
            previous_round = max((item["clarification_round"] for item in self.audit.get_session(session_id)["items"] if item["question_id"] == question_id), default=0)
            if previous_round >= 1:
                raise ValueError("only one adaptive clarification is allowed")
            latest_score = (latest or {}).get("score") or {}
            resolved_probe_type = probe_type or planned_probe_type
            supplement = response.strip()
            if selected_option and selected_option.get("id") == "other":
                # The UI sends only the participant's own words. Strip the
                # protocol label as well for clients that send
                # ``label；free text`` so that an instruction is never scored
                # as if it were evidence.
                label = str(selected_option.get("label") or "").strip()
                if label and supplement.startswith(label + "；"):
                    supplement = supplement[len(label) + 1 :].strip()
            elif selected_option and selected_option.get("label"):
                option_label = str(selected_option["label"])
                if not supplement:
                    supplement = option_label
                elif supplement != option_label and not supplement.startswith(option_label + "；"):
                    supplement = f"{option_label}；{supplement}"
            scoring_text = f"{base['response']}；补充：{supplement}" if supplement else base["response"]
            round_number = 1
            event_type = "PROBE_PAUSED" if probe_action == "PAUSE" else resolved_probe_type
        else:
            if latest and latest.get("event_type") == "INITIAL":
                latest_score = latest.get("score") or {}
                if latest_score.get("score_status") == "PROVISIONAL":
                    raise ValueError("clarification is required before submitting another initial response")
            scoring_text = response.strip()
            round_number = 0
            event_type = "INITIAL"
            resolved_probe_type = None
            selected_option = None
            interaction = None

        safety = screen(scoring_text)
        if clarification and probe_action == "PAUSE":
            # Pausing is a participant choice, not evidence. Keep the latest
            # item score intact and record the pause as a first-class event.
            result = ScoreResult.model_validate(latest_score)
            mode = "probe-paused"
        elif safety.state != "CLEAR":
            result, mode = score_response(question_id, scoring_text, self.rubrics), "safety-gated"
        else:
            result, mode = self._score(question_id, scoring_text)
        result.safety_state = safety.state
        result.clarification_round = round_number
        result.probe_type = resolved_probe_type
        if safety.state == "CLEAR" and not clarification and result.score_status in {"PROVISIONAL", "HUMAN_REVIEW"} and result.cat_probe is None:
            result.cat_probe = CatProbe.model_validate(default_cat_probe(
                question_id=question_id,
                probe_type=infer_probe_type(result.model_dump()),
                target_gap=result.target_gap,
                response=response,
            ))
        if safety.state != "CLEAR":
            result = self._force_human_review(result, "SAFETY_REVIEW")
            result.target_gap = "安全流程需要专业人员评估"
        elif clarification and result.score_status == "PROVISIONAL":
            result = self._force_human_review(result, "CLARIFICATION_UNRESOLVED")
        score_payload = result.model_dump()
        score_payload["provider"] = mode
        score_payload["model"] = _provider_model(self.scorer, mode)
        payload = {
            "score": score_payload,
            "safety": safety.model_dump(),
            "source_response": base["response"] if base else response,
            "clarification_response": response if clarification else None,
            "probe_type": resolved_probe_type,
            "probe_option_id": probe_option_id,
            "probe_action": probe_action,
            "probe_interaction": interaction,
        }
        event_id = self.audit.append_event(
            session_id=session_id,
            question_id=question_id,
            event_type=event_type,
            response=response.strip(),
            clarification_round=round_number,
            payload=payload,
        )
        session = self._fold_adjudications(self.audit.get_session(session_id))
        deterministic_evidence = build_global_evidence_state(
            items=session["items"] if session else [],
            rubrics=self.rubrics,
            current_question_id=question_id,
        )
        ai_analysis = self.ai_advisor.advise(
            items=session["items"] if session else [],
            rubrics=self.rubrics,
            state=deepcopy(deterministic_evidence),
        )
        global_evidence = apply_ai_planning(deepcopy(deterministic_evidence), ai_analysis)
        decision_id = self.audit.append_session_decision(
            session_id=session_id,
            event_id=event_id,
            deterministic_state=deterministic_evidence,
            ai_analysis={**ai_analysis, "decision_id": None},
        )
        ai_analysis = {**ai_analysis, "decision_id": decision_id}
        # Keep the latest snapshot easy to retrieve while the append-only
        # decision table preserves every prior AI recommendation for replay.
        self.audit.set_session_metadata(
            session_id,
            {
                "latest_global_evidence": global_evidence,
                "latest_ai_analysis": ai_analysis,
                "latest_event_id": event_id,
            },
        )
        next_action = global_evidence["next_action"]
        # A model-uncertain item may receive one confirmation probe before it
        # becomes a human-review case. Semantic gaps use clarification or
        # disambiguation; once a probe has already been used, the orchestrator
        # keeps the item in the expert queue.
        defer_current_probe = next_action.get("type") == "DEFER_CLARIFICATION" and next_action.get("question_id") == question_id and round_number == 0
        confirm_current_probe = next_action.get("type") == "CONFIRM_NOW" and next_action.get("question_id") == question_id and round_number == 0
        should_queue = result.score_status == "HUMAN_REVIEW" and not (defer_current_probe or confirm_current_probe)
        if should_queue:
            self.audit.upsert_review_case({
                "response_id": f"session:{session_id}:{question_id}",
                "source": "session",
                "session_id": session_id,
                "event_id": event_id,
                "question_id": question_id,
                "response": scoring_text,
                "preliminary_score": result.preliminary_score,
                "score_status": result.score_status,
                "evidence_sufficiency": result.evidence_sufficiency,
                "safety_state": result.safety_state,
                "reason_codes": result.decision_reasons,
                "payload": payload,
            })
        if session:
            if next_action["type"] in {"CLARIFY_NOW", "CONFIRM_NOW", "DEFER_CLARIFICATION"}:
                self.audit.set_session_status(session_id, "AWAITING_PROBE")
            elif next_action["type"] in {"HUMAN_REVIEW", "SAFETY_FLOW"}:
                self.audit.set_session_status(session_id, "AWAITING_REVIEW")
            elif next_action["type"] == "COMPLETE":
                self.audit.set_session_status(session_id, "COMPLETED")
            else:
                self.audit.set_session_status(session_id, "IN_PROGRESS")
            session = self.audit.get_session(session_id)
        return {
            "event_id": event_id,
            "question_id": question_id,
            "response": response,
            "clarification": clarification,
            "score": score_payload,
            "safety": safety.model_dump(),
            "session_status": session["status"] if session else "IN_PROGRESS",
            "global_evidence": global_evidence,
            "next_action": next_action,
            "session_intelligence": ai_analysis,
        }

    def get(self, session_id: str) -> dict[str, Any] | None:
        session = self.audit.get_session(session_id)
        if session is None:
            return None
        session = self._fold_adjudications(session)
        deterministic_evidence = build_global_evidence_state(items=session["items"], rubrics=self.rubrics)
        cached_ai = (session.get("metadata") or {}).get("latest_ai_analysis")
        if isinstance(cached_ai, dict):
            ai_analysis = cached_ai
        else:
            ai_analysis = self.ai_advisor.advise(items=session["items"], rubrics=self.rubrics, state=deepcopy(deterministic_evidence))
        global_evidence = apply_ai_planning(deepcopy(deterministic_evidence), ai_analysis)
        session["global_evidence"] = global_evidence
        session["next_action"] = global_evidence["next_action"]
        session["session_intelligence"] = ai_analysis
        action_type = global_evidence["next_action"].get("type")
        next_status = {
            "COMPLETE": "COMPLETED",
            "SAFETY_FLOW": "AWAITING_REVIEW",
            "HUMAN_REVIEW": "AWAITING_REVIEW",
            "CLARIFY_NOW": "AWAITING_PROBE",
            "CONFIRM_NOW": "AWAITING_PROBE",
            "DEFER_CLARIFICATION": "AWAITING_PROBE",
        }.get(action_type, "IN_PROGRESS")
        if session.get("status") != next_status:
            self.audit.set_session_status(session_id, next_status)
            session["status"] = next_status
        return session


def _provider_model(scorer: Any, mode: str) -> str:
    if mode == "llm":
        return str(getattr(scorer, "model", "configured-llm"))
    if mode == "centroid":
        return str(getattr(scorer, "model_name", "per-item-char-ngram-centroid"))
    if mode == "deterministic-fallback":
        return "deterministic-keyword-baseline"
    return str(getattr(scorer, "name", "deterministic-keyword-baseline"))
