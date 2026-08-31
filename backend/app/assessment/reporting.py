"""Administrative and descriptive reporting derived from persisted scores.

The values in this module are research operations, not a clinical instrument.
Item scores remain rubric-local; this layer only aggregates already-recorded
scores for an administrator's review and for descriptive population statistics.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


RISK_RULE_VERSION = "research-band-v1"
RISK_THRESHOLDS = {"low_max": 11, "moderate_max": 23}
EVIDENCE_REPORT_VERSION = "evidence-report-v1"


def _effective_score(score: dict[str, Any]) -> int | None:
    value = score.get("adjudicated_score", score.get("preliminary_score"))
    return int(value) if isinstance(value, int) and value in (0, 1, 2) else None


def _latest_by_question(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in items:
        question_id = str(item.get("question_id", ""))
        if question_id:
            latest[question_id] = item
    return latest


def classify_risk_level(*, total_score: int, answered: int, seed_total: int, safety_triggered: bool = False) -> str:
    """Return a transparent research band for admin triage.

    Incomplete sessions are never assigned a low/moderate/high band. Safety
    signals always take precedence over the aggregate score.
    """

    if safety_triggered:
        return "SAFETY_REVIEW"
    if answered < seed_total:
        return "INCOMPLETE"
    if total_score <= RISK_THRESHOLDS["low_max"]:
        return "LOW"
    if total_score <= RISK_THRESHOLDS["moderate_max"]:
        return "MODERATE"
    return "HIGH"


def _recommendation(*, risk_level: str, needs_review: bool, answered: int, seed_total: int) -> str:
    if risk_level == "SAFETY_REVIEW":
        return "停止自动流程，按专业安全流程由专业人员接住并评估。"
    if needs_review:
        return "优先人工复核未决节点，再决定是否需要进一步访谈或支持。"
    if answered < seed_total:
        return "当前会话尚未完成；暂不做分层结论，等待剩余回答。"
    if risk_level == "HIGH":
        return "建议尽快安排专业人员复核整场证据，并结合情境决定后续支持。"
    if risk_level == "MODERATE":
        return "建议保留证据地图，必要时安排后续访谈或专业复核。"
    return "当前没有触发研究规则下的优先提醒；仍应结合原话与专业判断。"


def build_session_admin_report(items: list[dict[str, Any]], *, seed_total: int = 20) -> dict[str, Any]:
    latest = _latest_by_question(items)
    scored = []
    score_counts = {"0": 0, "1": 0, "2": 0}
    status_counts: dict[str, int] = defaultdict(int)
    safety_triggered = False
    for item in latest.values():
        score = item.get("score") or {}
        value = _effective_score(score)
        if value is not None:
            scored.append(value)
            score_counts[str(value)] += 1
        status_counts[str(score.get("score_status") or "UNASSESSED")] += 1
        if str((item.get("safety") or {}).get("state", "CLEAR")) != "CLEAR":
            safety_triggered = True
    answered = len(latest)
    total_score = sum(scored)
    risk_level = classify_risk_level(total_score=total_score, answered=answered, seed_total=seed_total, safety_triggered=safety_triggered)
    needs_review = any(status in {"PROVISIONAL", "HUMAN_REVIEW"} for status in status_counts)
    recommendation = _recommendation(risk_level=risk_level, needs_review=needs_review, answered=answered, seed_total=seed_total)
    return {
        "version": RISK_RULE_VERSION,
        "answered": answered,
        "seed_total": seed_total,
        "total_score": total_score if scored else None,
        "max_score": seed_total * 2,
        "mean_score": round(total_score / len(scored), 3) if scored else None,
        "score_counts": score_counts,
        "status_counts": dict(status_counts),
        "safety_triggered": safety_triggered,
        "risk_level": risk_level,
        "support_recommendation": recommendation,
        # Kept for older clients. New administrator surfaces use the less
        # directive ``support_recommendation`` label.
        "intervention_recommendation": recommendation,
        "disclaimer": "研究规则分层，仅供管理员分流与描述性统计；不是临床诊断或单独的干预决定。",
    }


def _construct_pattern_level(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "UNASSESSED"
    if value >= 1.34:
        return "ELEVATED"
    if value >= 0.67:
        return "MIXED"
    return "LOW"


def _evidence_quality(value: Any) -> str:
    density = float(value) if isinstance(value, (int, float)) else 0.0
    if density >= 0.75:
        return "HIGH"
    if density >= 0.45:
        return "MEDIUM"
    return "LOW"


def _dimension_group(rubric: dict[str, Any]) -> str:
    dimension = str(rubric.get("dimension") or "未分类")
    return dimension.split("·", 1)[0].strip() or "未分类"


def build_session_evidence_report(
    session: dict[str, Any],
    rubrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build a stable, administrator-only evidence report.

    Cross-item signals are copied into the planning/relationship fields only.
    Every effective item score still comes exclusively from that item's latest
    score payload plus an explicit expert adjudication.
    """

    items = list(session.get("items") or [])
    state = session.get("global_evidence") or (session.get("metadata") or {}).get("latest_global_evidence") or {}
    intelligence = session.get("session_intelligence") or (session.get("metadata") or {}).get("latest_ai_analysis") or {}
    latest = _latest_by_question(items)
    first_seed: dict[str, dict[str, Any]] = {}
    event_counts: dict[str, int] = defaultdict(int)
    probe_counts: dict[str, int] = defaultdict(int)
    for item in items:
        question_id = str(item.get("question_id") or "")
        if not question_id:
            continue
        event_counts[question_id] += 1
        if item.get("event_type") == "INITIAL" and question_id not in first_seed:
            first_seed[question_id] = item
        elif item.get("event_type") != "INITIAL":
            probe_counts[question_id] += 1

    nodes = {str(node.get("question_id")): node for node in (state.get("nodes") or []) if node.get("question_id")}
    adjudications = session.get("adjudications") or {}
    item_matrix = []
    rubric_versions: set[str] = set()
    for question_id in sorted(rubrics):
        rubric = rubrics[question_id]
        item = latest.get(question_id)
        score = (item or {}).get("score") or {}
        node = nodes.get(question_id) or {}
        adjudication = adjudications.get(question_id) or (item or {}).get("adjudication") or {}
        preliminary = score.get("original_preliminary_score", score.get("preliminary_score"))
        adjudicated = score.get("adjudicated_score", adjudication.get("adjudicated_score"))
        effective = adjudicated if adjudicated in (0, 1, 2) else preliminary if preliminary in (0, 1, 2) else None
        rubric_version = str(score.get("rubric_version") or rubric.get("version") or "").strip()
        if rubric_version:
            rubric_versions.add(rubric_version)
        sufficiency = str(score.get("evidence_sufficiency") or "UNASSESSED")
        spans = list(score.get("evidence_spans") or [])
        density = node.get("evidence_density")
        if not isinstance(density, (int, float)):
            density = min(1.0, len(spans) / 3) if spans else (0.35 if sufficiency == "SUFFICIENT" else 0.0)
        review_status = str(adjudication.get("status") or ("OPEN" if score.get("score_status") in {"PROVISIONAL", "HUMAN_REVIEW"} else "NOT_REQUIRED"))
        item_matrix.append({
            "question_id": question_id,
            "question": str(rubric.get("question") or ""),
            "dimension": str(rubric.get("dimension") or ""),
            "group": str(node.get("group") or _dimension_group(rubric)),
            "original_response": str((first_seed.get(question_id) or {}).get("response") or ""),
            "latest_response": str((item or {}).get("response") or ""),
            "event_count": event_counts.get(question_id, 0),
            "score": {
                "preliminary": preliminary,
                "adjudicated": adjudicated if adjudicated in (0, 1, 2) else None,
                "effective": effective,
                "status": str(score.get("score_status") or "UNASSESSED"),
            },
            "evidence": {
                "sufficiency": sufficiency,
                "confidence": score.get("confidence"),
                "density": round(float(density), 4),
                "spans": spans,
                "rationale": str(score.get("rationale") or ""),
                "target_gap": score.get("target_gap") or node.get("target_gap"),
            },
            "probe": {
                "used": probe_counts.get(question_id, 0) > 0,
                "count": probe_counts.get(question_id, 0),
                "type": (item or {}).get("probe_type") or node.get("probe_type"),
            },
            "review": {
                "recommended": bool(score.get("review_recommended") or score.get("score_status") in {"PROVISIONAL", "HUMAN_REVIEW"}),
                "status": review_status,
            },
            "relationships": {
                "support_count": int(node.get("support_count") or 0),
                "conflict_count": int(node.get("conflict_count") or 0),
            },
            "scoring_boundary": "跨题信号只用于评估规划，不改变单题评分。",
        })

    constructs = [{
        **construct,
        "pattern_level": _construct_pattern_level(construct.get("score_mean")),
        "evidence_quality": _evidence_quality(construct.get("evidence_density")),
    } for construct in (state.get("constructs") or [])]

    timeline = []
    for item in items:
        event_type = str(item.get("event_type") or "INITIAL")
        is_probe = event_type != "INITIAL"
        safety_state = str(((item.get("safety") or {}).get("state") or "CLEAR"))
        timeline.append({
            "id": item.get("event_id"),
            "created_at": item.get("created_at"),
            "kind": "SAFETY" if safety_state != "CLEAR" else "PROBE" if is_probe else "SEED",
            "question_id": item.get("question_id"),
            "title": "进入专业安全流程" if safety_state != "CLEAR" else "用户补充了说明" if is_probe else "记录 Seed 回答",
            "description": str(item.get("response") or ""),
            "probe_type": item.get("probe_type"),
        })
    ai_decisions = []
    for decision in session.get("decision_history") or []:
        deterministic = decision.get("deterministic_state") or {}
        action = deterministic.get("next_action") or {}
        ai_analysis = decision.get("ai_analysis") or {}
        entry = {
            "id": decision.get("id"),
            "event_id": decision.get("event_id"),
            "created_at": decision.get("created_at"),
            "action": action.get("type"),
            "question_id": action.get("question_id"),
            "rationale": action.get("rationale"),
            "planning_notes": list(ai_analysis.get("planning_notes") or []),
        }
        ai_decisions.append(entry)
        timeline.append({
            "id": decision.get("id"),
            "created_at": decision.get("created_at"),
            "kind": "AI_PLAN",
            "question_id": action.get("question_id"),
            "action": action.get("type"),
            "title": "AI 调整评估路径",
            "description": action.get("rationale") or (entry["planning_notes"][0] if entry["planning_notes"] else "记录本轮会话级判断。"),
        })
    timeline.sort(key=lambda entry: str(entry.get("created_at") or ""))

    unresolved = list(state.get("unresolved_gaps") or [])
    review_queue = [{
        "question_id": gap.get("question_id"),
        "priority": gap.get("priority", 0),
        "target_gap": gap.get("target_gap") or gap.get("clarification_question"),
        "status": (adjudications.get(str(gap.get("question_id"))) or {}).get("status") or "OPEN",
        "support_count": int(gap.get("support_count") or 0),
        "conflict_count": int(gap.get("conflict_count") or 0),
    } for gap in sorted(unresolved, key=lambda value: float(value.get("priority") or 0), reverse=True)]
    explicit_conflicts = sum(str(link.get("type") or "").upper() == "CONFLICT" for link in (state.get("cross_item_links") or []))
    node_conflicts = sum(int(node.get("conflict_count") or 0) for node in nodes.values())
    conflict_links = max(explicit_conflicts, (node_conflicts + 1) // 2)
    admin_summary = build_session_admin_report(items, seed_total=int(state.get("seed_total") or len(rubrics) or 20))
    status_counts = admin_summary.get("status_counts") or {}
    return {
        "session_id": session.get("id"),
        "overview": {
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "seed_answered": int(state.get("seed_answered") or 0),
            "seed_total": int(state.get("seed_total") or len(rubrics) or 20),
            "confirmed_items": int(status_counts.get("CONFIRMED") or 0),
            "open_items": len(unresolved),
            "safety_state": "PROFESSIONAL_FLOW" if admin_summary.get("safety_triggered") else "CLEAR",
            "research_band": admin_summary.get("risk_level"),
            "support_recommendation": admin_summary.get("support_recommendation"),
            "disclaimer": admin_summary.get("disclaimer"),
            "session_summary": intelligence.get("session_summary"),
        },
        "constructs": constructs,
        "item_matrix": item_matrix,
        "timeline": timeline,
        "probe_summary": {
            "total": sum(probe_counts.values()),
            "questions_touched": sum(count > 0 for count in probe_counts.values()),
            "by_type": dict(sorted({
                str(item.get("probe_type") or item.get("event_type")): sum(
                    1 for candidate in items
                    if candidate.get("event_type") != "INITIAL"
                    and str(candidate.get("probe_type") or candidate.get("event_type")) == str(item.get("probe_type") or item.get("event_type"))
                )
                for item in items if item.get("event_type") != "INITIAL"
            }.items())),
        },
        "uncertainty": {
            "open_nodes": len(unresolved),
            "provisional_items": int(status_counts.get("PROVISIONAL") or 0),
            "human_review_items": int(status_counts.get("HUMAN_REVIEW") or 0),
            "support_links": sum(str(link.get("type") or "").upper() == "SUPPORT" for link in (state.get("cross_item_links") or [])),
            "conflict_links": conflict_links,
        },
        "ai_decisions": ai_decisions,
        "review_queue": review_queue,
        "versions": {
            "report": EVIDENCE_REPORT_VERSION,
            "orchestrator": state.get("version"),
            "rubric": sorted(rubric_versions),
            "research_band": admin_summary.get("version"),
            "session_model": intelligence.get("model"),
        },
    }


def build_population_summary(records: Iterable[dict[str, Any]], *, seed_total: int = 20) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_scores: list[int] = []
    question_scores: dict[str, list[int]] = defaultdict(list)
    for record in records:
        participant_id = str(record.get("participant_id") or "")
        if not participant_id:
            continue
        grouped[participant_id].append(record)
        value = record.get("legacy_score")
        if isinstance(value, int) and value in (0, 1, 2):
            all_scores.append(value)
            question_scores[str(record.get("question_id") or "")].append(value)
    risk_counts = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "INCOMPLETE": 0, "SAFETY_REVIEW": 0}
    participant_reports = []
    for participant_id, rows in grouped.items():
        latest = _latest_by_question([{
            "question_id": row.get("question_id"),
            "score": {"preliminary_score": row.get("legacy_score"), "score_status": "CONFIRMED"},
            "safety": {"state": "CLEAR"},
        } for row in rows])
        scores = [_effective_score((item.get("score") or {})) for item in latest.values()]
        valid = [score for score in scores if score is not None]
        level = classify_risk_level(total_score=sum(valid), answered=len(latest), seed_total=seed_total)
        risk_counts[level] += 1
        participant_reports.append({"participant_id": participant_id, "answered": len(latest), "total_score": sum(valid), "risk_level": level})
    return {
        "participants": len(grouped),
        "responses": len(all_scores),
        "overall_mean_score": round(sum(all_scores) / len(all_scores), 3) if all_scores else None,
        "question_means": {question_id: round(sum(values) / len(values), 3) for question_id, values in sorted(question_scores.items()) if question_id},
        "risk_counts": risk_counts,
        "risk_rule_version": RISK_RULE_VERSION,
        "disclaimer": "研究规则分层，仅用于群体描述性统计，不代表临床风险率。",
        "participant_reports": participant_reports,
    }
