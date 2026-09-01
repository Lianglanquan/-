"""Bounded session-level AI assistance.

The item scorer owns every 0/1/2 decision.  This module gives an optional
provider-backed model a different contract: it may synthesize the current
session, surface cross-item hypotheses, and propose a probe.  Its output is
validated and treated as planning advice only.  Deterministic guardrails in
``orchestrator.py`` remain the final authority for safety, allowed actions,
and probe eligibility.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.scoring.llm import LLMUnavailable
from backend.app.assessment.probes import normalise_cat_probe


AI_SESSION_VERSION = "session-ai-v1"
VALID_ACTIONS = {
    "CONTINUE_SEED",
    "DEFER_CLARIFICATION",
    "CLARIFY_NOW",
    "CONFIRM_NOW",
    "HUMAN_REVIEW",
    "SAFETY_FLOW",
    "COMPLETE",
}
VALID_PROBE_TYPES = {"CLARIFICATION", "DISAMBIGUATION", "CONFIRMATION"}
VALID_LINK_TYPES = {"SUPPORT", "CONFLICT"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_name(provider: Any) -> str:
    if provider is None:
        return "rule-fallback"
    return str(getattr(provider, "name", provider.__class__.__name__))


def _provider_model(provider: Any) -> str:
    if provider is None:
        return "deterministic-session-policy"
    return str(getattr(provider, "model", getattr(provider, "model_name", "configured-provider")))


def _safe_text(value: Any, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text[:limit]


def build_session_snapshot(items: list[dict[str, Any]], rubrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a provider input with only session evidence and rubric context.

    Legacy labels, participant identifiers, and internal review metadata are
    intentionally excluded.  Responses are still sensitive and are sent to a
    provider only when the caller explicitly enables external scoring.
    """

    snapshot: list[dict[str, Any]] = []
    for item in items:
        question_id = str(item.get("question_id", ""))
        rubric = rubrics.get(question_id, {})
        score = item.get("score") or {}
        snapshot.append(
            {
                "question_id": question_id,
                "event_type": str(item.get("event_type", "INITIAL")),
                "probe_type": item.get("probe_type"),
                "clarification_round": int(item.get("clarification_round", 0) or 0),
                "question": _safe_text(rubric.get("question", ""), limit=320),
                "dimension": _safe_text(rubric.get("dimension", ""), limit=160),
                "response": _safe_text(item.get("response", ""), limit=1200),
                "score": {
                    "preliminary_score": score.get("preliminary_score"),
                    "score_status": score.get("score_status"),
                    "evidence_sufficiency": score.get("evidence_sufficiency"),
                    "confidence": score.get("confidence"),
                    "decision_reasons": list(score.get("decision_reasons") or [])[:8],
                    "target_gap": score.get("target_gap"),
                },
                "safety_state": str((item.get("safety") or {}).get("state", "CLEAR")),
            }
        )
    return snapshot


def _fallback_advice(state: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    constructs = state.get("constructs") or []
    unresolved = state.get("unresolved_gaps") or []
    action = state.get("next_action") or {}
    construct_insights = []
    for construct in constructs:
        status = str(construct.get("status", "UNANSWERED"))
        if status == "UNANSWERED":
            summary = "当前尚无该构念的会话证据。"
        elif status == "NEEDS_REVIEW":
            summary = "已有回答，但至少一个节点仍需澄清或专家复核。"
        else:
            summary = "当前构念已有可回放的题内证据，仍不替代专家解释。"
        construct_insights.append(
            {
                "group": str(construct.get("id", "")),
                "summary": summary,
                "status": status,
                "confidence": round(float(construct.get("evidence_density", 0.0) or 0.0), 3),
                "evidence_question_ids": list(construct.get("question_ids") or []),
                "unresolved_question_ids": [item.get("question_id") for item in unresolved if item.get("question_id") in (construct.get("question_ids") or [])],
            }
        )
    planning_notes = [
        "当前使用规则护栏完成会话编排；跨题信号仅用于规划，不改变单题评分。",
        "安全状态、探针次数上限和评分 Rubric 由确定性组件掌管。",
    ]
    if reason:
        planning_notes.append(f"会话级 AI 未提供可用建议：{reason}")
    return {
        "version": AI_SESSION_VERSION,
        "status": "RULE_FALLBACK",
        "provider": "rule-fallback",
        "model": "deterministic-session-policy",
        "generated_at": _now(),
        "session_summary": f"已回答 {state.get('seed_answered', 0)}/{state.get('seed_total', 20)} 道 Seed Probes；当前下一步为 {action.get('type', 'CONTINUE_SEED')}。",
        "construct_insights": construct_insights,
        "cross_item_hypotheses": [],
        "probe_recommendations": [],
        "recommended_action": None,
        "planning_notes": planning_notes,
        "guardrail_result": "AI 未覆盖确定性安全与 Rubric 规则。",
    }


def build_participant_handoff(state: dict[str, Any], advice: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn the evidence map into a useful, non-diagnostic participant handoff.

    This is intentionally separate from scoring. It tells a participant what
    the session made visible, where the evidence is still open, and what they
    may choose to do next. It never emits a risk label, diagnosis, or clinical
    conclusion.
    """

    action = state.get("next_action") or {}
    if str(action.get("type", "")).upper() == "SAFETY_FLOW":
        return {
            "version": "participant-handoff-v1",
            "mode": "PROFESSIONAL_FLOW",
            "title": "先停在这里",
            "message": "这次对话里有一句话需要专业人员接住。自动流程会先停下，不继续替你解释。",
            "what_i_heard": [],
            "still_open": [],
            "next_steps": [],
            "takeaways": ["你的原话已经被保留，后续可以交给专业人员一起看。"],
        }

    constructs = state.get("constructs") if isinstance(state.get("constructs"), list) else []
    insight_by_group: dict[str, str] = {}
    for insight in (advice or {}).get("construct_insights", []) if isinstance((advice or {}).get("construct_insights"), list) else []:
        if not isinstance(insight, dict):
            continue
        group = _safe_text(insight.get("group"), limit=120)
        summary = _safe_text(insight.get("summary"), limit=360)
        # AI wording is advisory. Keep participant copy concrete, short, and
        # free of diagnostic or risk-label language before it reaches UI.
        if group and summary and not any(term in summary for term in ("风险等级", "风险评估", "诊断", "自杀风险", "你是")):
            insight_by_group[group] = summary
    what_i_heard = []
    for construct in constructs:
        if not isinstance(construct, dict) or int(construct.get("answered", 0) or 0) <= 0:
            continue
        status = str(construct.get("status", "EVIDENCED"))
        group = str(construct.get("label") or construct.get("id") or "一组回答")
        detail = insight_by_group.get(group)
        if not detail:
            if status == "EVIDENCED":
                detail = f"这里有 {int(construct.get('answered', 0) or 0)} 道回答彼此照见，形成了一条可以回看的线索。"
            else:
                detail = f"这里已经留下 {int(construct.get('answered', 0) or 0)} 道回答，但仍有一处没有急着替你定论。"
        what_i_heard.append({
            "group": group,
            "detail": detail,
            "answered": int(construct.get("answered", 0) or 0),
            "evidence_density": round(float(construct.get("evidence_density", 0.0) or 0.0), 3),
            "status": status,
        })

    unresolved = state.get("unresolved_gaps") if isinstance(state.get("unresolved_gaps"), list) else []
    still_open = []
    for item in unresolved[:6]:
        if not isinstance(item, dict):
            continue
        still_open.append({
            "question_id": str(item.get("question_id") or ""),
            "detail": str(item.get("target_gap") or "这部分还可以再听清一点，但现在不需要急着下结论。"),
            "status": str(item.get("status") or "OPEN"),
        })

    next_steps = [
        {"id": "VIEW_MAP", "label": "回看这张地图", "detail": "看看哪些回答已经彼此照见，哪些地方仍保留着空间。"},
        {"id": "SAVE_SESSION", "label": "先把这次收好", "detail": "不需要现在解释完自己；这份记录会留在你的私密会话里。"},
    ]
    if unresolved and str(action.get("type", "")).upper() in {"CLARIFY_NOW", "CONFIRM_NOW"}:
        next_steps.insert(1, {"id": "CONTINUE_PROBE", "label": "继续靠近一处", "detail": "如果愿意，只挑当前最想说清的一处，不必重新回答全部问题。"})

    summary = _safe_text((advice or {}).get("session_summary"), limit=420)
    if not summary:
        summary = f"这次共留下 {state.get('seed_answered', 0)}/{state.get('seed_total', 20)} 道回答；它们组成了一张可以回看的证据地图。"
    return {
        "version": "participant-handoff-v1",
        "mode": "PARTICIPANT_HANDOFF",
        "title": "这一次，你留下了什么",
        "message": summary,
        "what_i_heard": what_i_heard[:8],
        "still_open": still_open,
        "next_steps": next_steps,
        "takeaways": [
            "你得到的不是一个给你下定义的分数，而是一张能回到原话的证据地图。",
            "已经说清的地方被看见，还没说清的地方被保留下来。",
            "下一步由你选择：回看、继续靠近，或先把这次收好。",
        ],
    }


def _normalise_advice(raw: dict[str, Any], state: dict[str, Any], provider: Any) -> dict[str, Any]:
    """Validate and bound provider output before it can reach the UI."""

    allowed_ids = {str(node.get("question_id")) for node in state.get("nodes", [])}
    unresolved_ids = {str(node.get("question_id")) for node in state.get("nodes", []) if node.get("pending") or node.get("status") == "HUMAN_REVIEW"}
    constructs = []
    for value in raw.get("construct_insights", []) if isinstance(raw.get("construct_insights"), list) else []:
        if not isinstance(value, dict):
            continue
        constructs.append(
            {
                "group": _safe_text(value.get("group"), limit=120),
                "summary": _safe_text(value.get("summary"), limit=500),
                "status": _safe_text(value.get("status"), limit=40),
                "confidence": max(0.0, min(1.0, float(value.get("confidence", 0.0) or 0.0))),
                "evidence_question_ids": [str(qid) for qid in value.get("evidence_question_ids", []) if str(qid) in allowed_ids][:20],
                "unresolved_question_ids": [str(qid) for qid in value.get("unresolved_question_ids", []) if str(qid) in unresolved_ids][:20],
            }
        )
    links = []
    for value in raw.get("cross_item_hypotheses", []) if isinstance(raw.get("cross_item_hypotheses"), list) else []:
        if not isinstance(value, dict):
            continue
        qids = [str(qid) for qid in value.get("question_ids", []) if str(qid) in allowed_ids]
        link_type = str(value.get("type", "")).upper()
        if len(qids) < 2 or link_type not in VALID_LINK_TYPES:
            continue
        links.append(
            {
                "question_ids": qids[:8],
                "type": link_type,
                "rationale": _safe_text(value.get("rationale"), limit=500),
                "confidence": max(0.0, min(1.0, float(value.get("confidence", 0.0) or 0.0))),
            }
        )
    probes = []
    for value in raw.get("probe_recommendations", []) if isinstance(raw.get("probe_recommendations"), list) else []:
        if not isinstance(value, dict):
            continue
        question_id = str(value.get("question_id", ""))
        probe_type = str(value.get("probe_type", "")).upper()
        if question_id not in unresolved_ids or probe_type not in VALID_PROBE_TYPES:
            continue
        probes.append(
            {
                "question_id": question_id,
                "probe_type": probe_type,
                "question": _safe_text(value.get("question"), limit=500),
                "rationale": _safe_text(value.get("rationale"), limit=500),
                "confidence": max(0.0, min(1.0, float(value.get("confidence", 0.0) or 0.0))),
                "priority_adjustment": max(-0.12, min(0.12, float(value.get("priority_adjustment", 0.0) or 0.0))),
                "cat_probe": normalise_cat_probe(
                    value.get("cat_probe"),
                    question_id=question_id,
                    probe_type=probe_type,
                    target_gap=next((node.get("target_gap") for node in state.get("nodes", []) if node.get("question_id") == question_id), None),
                ),
            }
        )
    recommended = raw.get("recommended_action") if isinstance(raw.get("recommended_action"), dict) else None
    if recommended:
        rec_type = str(recommended.get("type", "")).upper()
        rec_qid = str(recommended.get("question_id", "")) if recommended.get("question_id") else None
        rec_probe = str(recommended.get("probe_type", "")).upper() if recommended.get("probe_type") else None
        if rec_type not in VALID_ACTIONS or (rec_qid and rec_qid not in unresolved_ids) or (rec_probe and rec_probe not in VALID_PROBE_TYPES):
            recommended = None
        else:
            recommended = {
                "type": rec_type,
                "question_id": rec_qid,
                "probe_type": rec_probe,
                "question": _safe_text(recommended.get("question"), limit=500),
                "rationale": _safe_text(recommended.get("rationale"), limit=500),
                "confidence": max(0.0, min(1.0, float(recommended.get("confidence", 0.0) or 0.0))),
            }
    return {
        "version": AI_SESSION_VERSION,
        "status": "AI_ADVISORY",
        "provider": _provider_name(provider),
        "model": _provider_model(provider),
        "generated_at": _now(),
        "session_summary": _safe_text(raw.get("session_summary"), limit=1200),
        "construct_insights": constructs[:20],
        "cross_item_hypotheses": links[:30],
        "probe_recommendations": probes[:20],
        "recommended_action": recommended,
        "planning_notes": [_safe_text(value, limit=500) for value in raw.get("planning_notes", [])[:12]] if isinstance(raw.get("planning_notes"), list) else [],
        "guardrail_result": "已通过题目集合、未决节点、探针类型和动作白名单校验；不会覆盖单题分数或安全状态。",
    }


class SessionAIAdvisor:
    """Optional provider-backed session analyst with a deterministic fallback."""

    def __init__(self, provider: Any = None) -> None:
        self.provider = provider if callable(getattr(provider, "analyze_session", None)) else None

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def advise(self, *, items: list[dict[str, Any]], rubrics: dict[str, dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        if self.provider is None:
            return _fallback_advice(state)
        try:
            raw = self.provider.analyze_session(
                build_session_snapshot(items, rubrics),
                state,
            )
            if not isinstance(raw, dict):
                raise LLMUnavailable("session analyst returned a non-object")
            return _normalise_advice(raw, state, self.provider)
        except (LLMUnavailable, OSError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            return _fallback_advice(state, reason=exc.__class__.__name__)


def apply_ai_planning(state: dict[str, Any], advice: dict[str, Any]) -> dict[str, Any]:
    """Merge AI advice without allowing it to bypass deterministic policy.

    The model can refine a probe question and modestly reprioritise an already
    pending node.  It cannot create a probe for an answered/safe node, change a
    score, or override HUMAN_REVIEW/SAFETY_FLOW/COMPLETE guardrails.
    """

    state["session_intelligence"] = advice
    base_action = dict(state.get("next_action") or {})
    deterministic_action = dict(base_action)
    nodes = {str(node.get("question_id")): node for node in state.get("nodes", [])}
    for recommendation in advice.get("probe_recommendations", []):
        node = nodes.get(str(recommendation.get("question_id")))
        if not node or not node.get("pending"):
            continue
        node["ai_priority_adjustment"] = recommendation.get("priority_adjustment", 0.0)
        node["priority"] = round(max(0.0, min(1.0, float(node.get("priority", 0.0)) + float(recommendation.get("priority_adjustment", 0.0)))), 4)

    recommendation = advice.get("recommended_action") or {}
    selected_qid = base_action.get("question_id")
    if selected_qid and recommendation.get("question_id") == selected_qid:
        if base_action.get("type") in {"CLARIFY_NOW", "CONFIRM_NOW", "DEFER_CLARIFICATION"}:
            # A probe recommendation may carry AI-authored companion language.
            # Only apply it to the deterministic target and matching probe
            # type; the model cannot redirect the session or create a new gap.
            matching_probe = next(
                (
                    probe for probe in advice.get("probe_recommendations", [])
                    if probe.get("question_id") == selected_qid
                    and probe.get("probe_type") == base_action.get("probe_type")
                ),
                None,
            )
            # The deterministic scorer can leave a semantic gap classified as
            # generic CLARIFICATION while the session analyst distinguishes it
            # more precisely (for example DISAMBIGUATION).  The recommendation
            # is still bounded to the already-selected pending node; carrying
            # its validated probe type keeps the participant payload and
            # follow-up validation in sync.
            if matching_probe is None and recommendation.get("probe_type") in VALID_PROBE_TYPES:
                matching_probe = next(
                    (
                        probe for probe in advice.get("probe_recommendations", [])
                        if probe.get("question_id") == selected_qid
                        and probe.get("probe_type") == recommendation.get("probe_type")
                    ),
                    None,
                )
                if matching_probe:
                    base_action["probe_type"] = recommendation["probe_type"]
            if recommendation.get("question"):
                base_action["question"] = recommendation["question"]
            if recommendation.get("rationale"):
                base_action["rationale"] = f"{base_action.get('rationale', '')} AI 会话建议：{recommendation['rationale']}"
            if matching_probe and matching_probe.get("cat_probe") and base_action.get("type") in {"CLARIFY_NOW", "CONFIRM_NOW", "DEFER_CLARIFICATION"}:
                base_action["interaction"] = matching_probe["cat_probe"]

    # Re-sort unresolved gaps after bounded AI priority adjustments, but keep
    # the deterministic action type and safety gates as the authority.
    unresolved = state.get("unresolved_gaps") or []
    for item in unresolved:
        if str(item.get("question_id")) in nodes:
            item["priority"] = nodes[str(item.get("question_id"))].get("priority", item.get("priority", 0.0))
    unresolved.sort(key=lambda value: float(value.get("priority", 0.0)), reverse=True)
    if base_action.get("question_id") in nodes:
        base_action["priority"] = nodes[str(base_action["question_id"])].get("priority", base_action.get("priority", 0.0))
    state["next_action"] = base_action
    state["decision_trace"] = {
        "deterministic_action": deterministic_action,
        "ai_recommendation": recommendation or None,
        "final_action": dict(base_action),
        "final_action_source": "deterministic_guardrail_with_ai_probe_refinement" if advice.get("status") == "AI_ADVISORY" else "deterministic_policy",
        "ai_used": advice.get("status") == "AI_ADVISORY",
    }
    return state
