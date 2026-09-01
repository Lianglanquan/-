"""Session-level adaptive assessment orchestration.

The item scorer remains rubric-local.  This module only consumes persisted
item results to maintain a global evidence state and choose the next
assessment action.  Cross-item signals are therefore planning signals, never
additional evidence for an item's 0/1/2 score.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.app.assessment.probes import default_cat_probe


ORCHESTRATOR_VERSION = "session-orchestrator-v1"
TOTAL_SEED_PROBES = 20
MAX_SESSION_PROBES = 3

# These are research-priority weights, not clinical risk weights. They must be
# reviewed by the psychology team before being used as production policy.
GROUP_PRIORITIES = {
    "自我认知与绝望感": 0.90,
    "情绪状态与人际联结": 0.84,
    "生存意愿与未来想象": 1.00,
    "人际负性体验": 0.88,
    "负性认知加工": 0.78,
    "情绪调节与应对效能": 0.76,
    "触发与情绪": 0.70,
}

# The links are semantic planning relations only. They do not alter item
# scores. Pairs are intentionally explicit so the research team can inspect
# and revise the session policy.
RELATED_PAIRS = (
    ("Q02", "Q03", "interpersonal-context"),
    ("Q02", "Q04", "interpersonal-context"),
    ("Q03", "Q05", "interpersonal-context"),
    ("Q03", "Q07", "support-seeking"),
    ("Q05", "Q07", "support-seeking"),
    ("Q06", "Q07", "support-seeking"),
    ("Q08", "Q09", "self-appraisal"),
    ("Q08", "Q10", "self-appraisal"),
    ("Q09", "Q10", "self-appraisal"),
    ("Q09", "Q13", "cognitive-processing"),
    ("Q10", "Q14", "self-appraisal"),
    ("Q12", "Q15", "coping-efficacy"),
    ("Q16", "Q17", "future-support"),
    ("Q16", "Q18", "future-support"),
    ("Q17", "Q18", "survival-response"),
    ("Q18", "Q19", "distress-impact"),
)

LEGACY_RELATED_PAIRS = (
    ("Q03", "Q16", "interpersonal-future"),
)

CONFIRMATION_PROBES = {
    "Q01": "如果换一个相近的独处时刻，你的感受仍然更接近刚才的方向吗？可以说说原因。",
    "Q02": "如果换一个相近的聚会场景，你通常仍会有刚才说的感受吗？",
    "Q03": "当别人再次为你付出时，你的直接感受仍然更接近刚才的方向吗？",
    "Q04": "如果再向信任的人袒露一次，你更预期关系会靠近、保持距离，还是发生别的变化？",
    "Q05": "如果低谷持续一段时间，你仍预计亲近的人会这样回应吗？",
    "Q06": "遇到下一次类似麻烦时，你仍会采用刚才说的求助方式吗？",
    "Q07": "在另一个相近的困扰上，你仍会觉得倾诉是刚才说的难易程度吗？",
    "Q08": "如果下一次事情没有达到预期，你还会用刚才的方式评价它吗？",
    "Q09": "如果再遇到类似失败，你的判断仍主要针对这件事，还是会扩展到自己？",
    "Q10": "如果再看到别人做到这件事，你对自己的判断仍会停留在刚才的范围吗？",
    "Q11": "如果调整后仍未成功，你下一步通常还会按刚才的方式处理吗？",
    "Q12": "如果问题过一阵子仍未解决，你还会继续寻找办法吗？",
    "Q13": "当消极想法再次出现时，你仍能按刚才的方式和它相处吗？",
    "Q14": "如果对方之后仍然冷淡，你还会按刚才的方式理解这件事吗？",
    "Q15": "如果事情继续超出掌控，你仍会处理自己能处理的部分吗？",
    "Q16": "如果把时间点换成更近的未来，你想到的画面仍有类似的内容和期待吗？",
    "Q17": "如果危险情境换一个类似场景，你仍会先采取刚才说的行动吗？",
    "Q18": "如果再想一遍那个瞬间，最先出现的感受仍然是刚才说的方向吗？",
    "Q19": "如果只回想最近两周的整体状态，你仍会给出刚才这个 0 到 10 的数字吗？",
}

SEMANTIC_GAP_REASONS = {
    "NO_SEMANTIC_CONTENT",
    "ABSTRACT_OR_DIRECTION_UNKNOWN",
    "MINIMAL_CONTEXT",
    "INVALID_NUMERIC_RESPONSE",
}


def _group(rubric: dict[str, Any] | None) -> str:
    dimension = str((rubric or {}).get("construct") or (rubric or {}).get("dimension", "未分类"))
    return dimension.split("-", 1)[0].strip()


def _latest_items(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in items:
        latest[item["question_id"]] = item
    return latest


def _probe_count(items: list[dict[str, Any]], question_id: str) -> int:
    return sum(1 for item in items if item["question_id"] == question_id and item.get("event_type") != "INITIAL")


def _score_payload(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("score") or {}


def _effective_score(score: dict[str, Any]) -> int | None:
    """Use an expert adjudication for planning while preserving the initial score."""

    adjudicated = score.get("adjudicated_score")
    if isinstance(adjudicated, int) and adjudicated in (0, 1, 2):
        return adjudicated
    preliminary = score.get("preliminary_score")
    return preliminary if isinstance(preliminary, int) else None


def _is_safety(item: dict[str, Any]) -> bool:
    safety = item.get("safety") or {}
    return str(safety.get("state", "CLEAR")) != "CLEAR"


def _is_pending(item: dict[str, Any], all_items: list[dict[str, Any]] | None = None) -> bool:
    if item.get("event_type") == "PROBE_PAUSED":
        return False
    score = _score_payload(item)
    status = str(score.get("score_status", ""))
    sufficiency = str(score.get("evidence_sufficiency", ""))
    reasons = set(score.get("decision_reasons") or [])
    if _is_safety(item):
        return False
    if status == "PROVISIONAL" and sufficiency == "INSUFFICIENT":
        return True
    return status == "HUMAN_REVIEW" and "MODEL_UNCERTAINTY" in reasons and _probe_count(all_items or [], item["question_id"]) == 0


def _infer_probe_type(score: dict[str, Any]) -> str:
    reasons = set(score.get("decision_reasons") or [])
    if "MODEL_UNCERTAINTY" in reasons and not (reasons & SEMANTIC_GAP_REASONS):
        return "CONFIRMATION"
    if reasons & {"ABSTRACT_OR_DIRECTION_UNKNOWN", "MINIMAL_CONTEXT", "INVALID_NUMERIC_RESPONSE"}:
        return "DISAMBIGUATION"
    return "CLARIFICATION"


def _probe_question(question_id: str, probe_type: str, score: dict[str, Any]) -> str | None:
    if probe_type == "CONFIRMATION":
        return CONFIRMATION_PROBES.get(question_id)
    return score.get("clarification_question") or None


def _probe_interaction(question_id: str, probe_type: str, item: dict[str, Any]) -> dict[str, Any] | None:
    score = _score_payload(item)
    existing = score.get("cat_probe")
    if isinstance(existing, dict):
        return existing
    return default_cat_probe(
        question_id=question_id,
        probe_type=probe_type,
        target_gap=score.get("target_gap"),
        response=str(item.get("response", "")),
    )


def _related_signal(question_id: str, latest: dict[str, dict[str, Any]], related_pairs: tuple[tuple[str, str, str], ...] = RELATED_PAIRS) -> dict[str, Any]:
    support = 0
    conflict = 0
    links: list[dict[str, Any]] = []
    for left, right, relation in related_pairs:
        if question_id not in {left, right}:
            continue
        other_id = right if question_id == left else left
        current = latest.get(question_id)
        other = latest.get(other_id)
        if not current or not other:
            continue
        current_score = _score_payload(current)
        other_score = _score_payload(other)
        current_effective = _effective_score(current_score)
        other_effective = _effective_score(other_score)
        if current_effective is None or other_effective is None:
            continue
        # The current node may itself be provisional: that is exactly when
        # cross-item context should help decide whether to probe it. An
        # unresolved neighbouring node is not strong enough to form a link.
        if other_score.get("score_status") == "PROVISIONAL":
            continue
        delta = abs(current_effective - other_effective)
        if delta >= 2:
            conflict += 1
            link_type = "CONFLICT"
            rationale = f"{question_id} 与 {other_id} 的题内评分方向明显不一致，需确认是否存在情境差异或表达矛盾。"
        else:
            support += 1
            link_type = "SUPPORT"
            rationale = f"{question_id} 与 {other_id} 在相关构念上提供了方向相近的会话证据。"
        links.append({"source_question_id": question_id, "target_question_id": other_id, "relation": relation, "type": link_type, "rationale": rationale, "score_delta": delta})
    return {"support": support, "conflict": conflict, "links": links}


def _priority(node: dict[str, Any], signal: dict[str, Any]) -> float:
    score = node.get("effective_score", node.get("preliminary_score"))
    confidence = node.get("confidence")
    priority = 0.32 * float(node.get("group_priority", 0.7))
    if node.get("status") == "PROVISIONAL":
        priority += 0.22
    if node.get("status") == "HUMAN_REVIEW":
        priority += 0.18
    if node.get("semantic_gap"):
        # An actionable semantic gap is more useful to resolve than a generic
        # model disagreement. This is what lets a context-poor Q16 become the
        # next probe when Q03/Q05/Q07 make it a consequential node.
        priority += 0.12
    if isinstance(score, int):
        priority += 0.10 * (score / 2)
    if isinstance(confidence, (int, float)):
        priority += 0.16 * (1 - float(confidence))
    priority += min(0.16, signal["support"] * 0.05)
    priority += min(0.24, signal["conflict"] * 0.12)
    return round(min(1.0, priority), 4)


def _action(
    *,
    nodes: list[dict[str, Any]],
    latest: dict[str, dict[str, Any]],
    all_items: list[dict[str, Any]],
    current_question_id: str | None,
    seed_total: int,
) -> dict[str, Any]:
    safety_items = [item for item in latest.values() if _is_safety(item)]
    if safety_items:
        return {
            "type": "SAFETY_FLOW",
            "question_id": safety_items[-1]["question_id"],
            "probe_type": None,
            "question": None,
            "priority": 1.0,
            "rationale": "安全引擎已触发，停止自动追问并进入预定义专业流程。",
        }

    pending = [node for node in nodes if node.get("pending")]
    pending.sort(key=lambda node: (float(node.get("priority", 0)), node["question_id"]), reverse=True)
    answered_seed = len({item["question_id"] for item in all_items if item.get("event_type") == "INITIAL"})
    used_probes = sum(1 for item in all_items if item.get("event_type") != "INITIAL")
    current = next((node for node in pending if node["question_id"] == current_question_id), None)
    top = pending[0] if pending else None
    if top:
        if used_probes >= MAX_SESSION_PROBES:
            return {
                "type": "HUMAN_REVIEW",
                "question_id": top["question_id"],
                "probe_type": None,
                "question": None,
                "priority": top["priority"],
                "rationale": "本次会话已达到自动探针负担上限，剩余不确定性转交专家复核。",
            }
        probes = int(top.get("probe_count", 0))
        if probes >= 1:
            return {
                "type": "HUMAN_REVIEW",
                "question_id": top["question_id"],
                "probe_type": None,
                "question": None,
                "priority": top["priority"],
                "rationale": "该节点已经完成一次自动探针，仍无法形成稳定证据，转交专家复核。",
            }
        probe_type = str(top.get("probe_type") or "CLARIFICATION")
        # Early ambiguity is recorded and deferred so the rest of the seed
        # probes can naturally supply context. A high-priority unresolved node
        # is asked immediately once enough session context exists.
        high_context_priority = top["priority"] >= 0.72 and (int(top.get("conflict_count", 0)) >= 1 or int(top.get("support_count", 0)) >= 2)
        if answered_seed >= 5 and top["priority"] >= 0.58 and (current or high_context_priority):
            action_type = "CONFIRM_NOW" if probe_type == "CONFIRMATION" else "CLARIFY_NOW"
            return {
                "type": action_type,
                "question_id": top["question_id"],
                "probe_type": probe_type,
                "question": _probe_question(top["question_id"], probe_type, _score_payload(latest[top["question_id"]])),
                "interaction": _probe_interaction(top["question_id"], probe_type, latest[top["question_id"]]),
                "priority": top["priority"],
                "rationale": "当前节点在会话证据图中优先级较高，先补充最小必要证据。" if current else "后续回答使此前暂缓的节点成为关键未决位置，现在回到该节点做一次最小求证。",
            }
        if answered_seed < seed_total:
            return {
                "type": "DEFER_CLARIFICATION",
                "question_id": top["question_id"],
                "probe_type": probe_type,
                "question": _probe_question(top["question_id"], probe_type, _score_payload(latest[top["question_id"]])),
                "interaction": None,
                "priority": top["priority"],
                "rationale": "当前信息缺口已记录，但先完成剩余 Seed Probes，避免过早打断会话。",
            }
        return {
            "type": "CLARIFY_NOW" if probe_type != "CONFIRMATION" else "CONFIRM_NOW",
            "question_id": top["question_id"],
            "probe_type": probe_type,
            "question": _probe_question(top["question_id"], probe_type, _score_payload(latest[top["question_id"]])),
            "interaction": _probe_interaction(top["question_id"], probe_type, latest[top["question_id"]]),
            "priority": top["priority"],
            "rationale": "Seed Probes 已完成，回到会话中优先级最高的未解决节点。",
        }
    terminal_review = [
        node
        for node in nodes
        if node.get("status") == "HUMAN_REVIEW" and not node.get("pending")
    ]
    if terminal_review:
        terminal_review.sort(key=lambda node: (float(node.get("priority", 0)), node["question_id"]), reverse=True)
        review_node = terminal_review[0]
        return {
            "type": "HUMAN_REVIEW",
            "question_id": review_node["question_id"],
            "probe_type": None,
            "question": None,
            "priority": review_node["priority"],
            "rationale": "该节点的自动评分仍存在不可消解的不确定性，交给专家复核。",
        }
    if answered_seed < seed_total:
        return {
            "type": "CONTINUE_SEED",
            "question_id": None,
            "probe_type": None,
            "question": None,
            "priority": 0.0,
            "rationale": "当前没有需要立即求证的节点，继续完成 Seed Probes。",
        }
    return {
        "type": "COMPLETE",
        "question_id": None,
        "probe_type": None,
        "question": None,
        "priority": 0.0,
        "rationale": "Seed Probes 已完成，当前没有开放的自动探针。",
    }


def build_global_evidence_state(
    *,
    items: list[dict[str, Any]],
    rubrics: dict[str, dict[str, Any]],
    current_question_id: str | None = None,
    seed_total: int | None = None,
) -> dict[str, Any]:
    latest = _latest_items(items)
    enriched_items = []
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    related_pairs = RELATED_PAIRS
    legacy_q16 = rubrics.get("Q16", {}).get("source_id") == "Q16"
    if legacy_q16:
        related_pairs = LEGACY_RELATED_PAIRS + RELATED_PAIRS
    for question_id in sorted(rubrics):
        rubric = rubrics[question_id]
        item = latest.get(question_id)
        if not item:
            node = {
                "question_id": question_id,
                "dimension": rubric.get("dimension", ""),
                "group": _group(rubric),
                "status": "UNANSWERED",
                "preliminary_score": None,
                "adjudicated_score": None,
                "effective_score": None,
                "evidence_sufficiency": "UNASSESSED",
                "confidence": None,
                "evidence_density": 0.0,
                "probe_count": 0,
                "pending": False,
                "priority": 0.0,
                "group_priority": GROUP_PRIORITIES.get(_group(rubric), 0.7),
                "decision_reasons": [],
                "semantic_gap": False,
                "target_gap": None,
            }
        else:
            score = _score_payload(item)
            reasons = list(score.get("decision_reasons") or [])
            status = str(score.get("score_status", "UNKNOWN"))
            sufficiency = str(score.get("evidence_sufficiency", "UNASSESSED"))
            spans = score.get("evidence_spans") or []
            evidence_density = min(1.0, len(spans) / 3) if spans else (0.35 if sufficiency == "SUFFICIENT" else 0.0)
            probe_count = _probe_count(items, question_id)
            node = {
                "question_id": question_id,
                "dimension": rubric.get("dimension", ""),
                "group": _group(rubric),
                "status": status,
                "preliminary_score": score.get("preliminary_score"),
                "adjudicated_score": score.get("adjudicated_score"),
                "effective_score": _effective_score(score),
                "evidence_sufficiency": sufficiency,
                "confidence": score.get("confidence"),
                "evidence_density": round(evidence_density, 4),
                "probe_count": probe_count,
                "pending": False,
                "priority": 0.0,
                "group_priority": GROUP_PRIORITIES.get(_group(rubric), 0.7),
                "decision_reasons": reasons,
                "semantic_gap": bool(set(reasons) & SEMANTIC_GAP_REASONS),
                "target_gap": score.get("target_gap"),
                "clarified": probe_count > 0,
                "source_event_id": item.get("event_id"),
            }
            node["pending"] = _is_pending(item, items)
            node["probe_type"] = _infer_probe_type(score) if node["pending"] else None
        signal = _related_signal(question_id, latest, related_pairs)
        node["support_count"] = signal["support"]
        node["conflict_count"] = signal["conflict"]
        node["priority"] = _priority(node, signal) if node.get("pending") else 0.0
        nodes.append(node)
        groups[node["group"]].append(node)
        links.extend(signal["links"])

    construct_map = []
    for group, group_nodes in sorted(groups.items()):
        answered = [node for node in group_nodes if node["status"] != "UNANSWERED"]
        scores = [node["effective_score"] for node in answered if isinstance(node.get("effective_score"), int)]
        construct_map.append({
            "id": group,
            "label": group,
            "question_ids": [node["question_id"] for node in group_nodes],
            "answered": len(answered),
            "score_mean": round(sum(scores) / len(scores), 3) if scores else None,
            "evidence_density": round(sum(node["evidence_density"] for node in answered) / len(answered), 3) if answered else 0.0,
            "confirmed": sum(node["status"] == "CONFIRMED" for node in group_nodes),
            "provisional": sum(node["status"] == "PROVISIONAL" for node in group_nodes),
            "human_review": sum(node["status"] == "HUMAN_REVIEW" for node in group_nodes),
            "conflicts": sum(node["conflict_count"] for node in group_nodes),
            "status": "UNANSWERED" if not answered else "NEEDS_REVIEW" if any(node["status"] in {"PROVISIONAL", "HUMAN_REVIEW"} for node in group_nodes) else "EVIDENCED",
        })

    resolved_seed_total = int(seed_total or len(rubrics) or TOTAL_SEED_PROBES)
    action = _action(nodes=nodes, latest=latest, all_items=items, current_question_id=current_question_id, seed_total=resolved_seed_total)
    unresolved = [
        {
            "question_id": node["question_id"],
            "dimension": node["dimension"],
            "status": node["status"],
            "probe_type": node.get("probe_type"),
            "priority": node["priority"],
            "target_gap": (_score_payload(latest[node["question_id"]]).get("target_gap") if node["question_id"] in latest else None),
            "clarification_question": (_score_payload(latest[node["question_id"]]).get("clarification_question") if node["question_id"] in latest else None),
            "probe_question": (_probe_question(node["question_id"], str(node.get("probe_type") or ""), _score_payload(latest[node["question_id"]])) if node["question_id"] in latest else None),
            "support_count": node["support_count"],
            "conflict_count": node["conflict_count"],
            "probe_count": node["probe_count"],
        }
        for node in sorted(nodes, key=lambda value: value["priority"], reverse=True)
        if node.get("pending") or node.get("status") == "HUMAN_REVIEW"
    ]
    return {
        "version": ORCHESTRATOR_VERSION,
        "seed_total": resolved_seed_total,
        "seed_answered": len({item["question_id"] for item in items if item.get("event_type") == "INITIAL"}),
        "probe_count": sum(1 for item in items if item.get("event_type") != "INITIAL"),
        "burden": {
            "max_session_probes": MAX_SESSION_PROBES,
            "used_probes": sum(1 for item in items if item.get("event_type") != "INITIAL"),
            "remaining_probe_budget": max(0, MAX_SESSION_PROBES - sum(1 for item in items if item.get("event_type") != "INITIAL")),
            "interruption_rate": round(sum(1 for item in items if item.get("event_type") != "INITIAL") / max(1, len({item["question_id"] for item in items if item.get("event_type") == "INITIAL"})), 4),
        },
        "constructs": construct_map,
        "nodes": nodes,
        "cross_item_links": links,
        "unresolved_gaps": unresolved,
        "next_action": action,
        "policy_notes": [
            "跨题信号只用于决定下一步评估策略，不进入单题 0/1/2 评分。",
            "优先级是研究编排策略，不是临床风险权重。",
            "每个题目最多自动探针一次，仍不稳定则进入 HUMAN_REVIEW。",
            f"每场会话最多 {MAX_SESSION_PROBES} 个自动探针，超过上限不再增加参与者负担。",
        ],
    }


def infer_probe_type(score: dict[str, Any]) -> str:
    """Public helper used by the assessment service for a pending item."""

    return _infer_probe_type(score)
