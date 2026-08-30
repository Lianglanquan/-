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
        "intervention_recommendation": _recommendation(risk_level=risk_level, needs_review=needs_review, answered=answered, seed_total=seed_total),
        "disclaimer": "研究规则分层，仅供管理员分流与描述性统计；不是临床诊断或单独的干预决定。",
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
