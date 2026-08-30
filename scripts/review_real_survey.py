"""Run the filtered real-survey answers through the project runtime.

This runner uses the same locally configured item scorer and the same
session-level orchestrator used by the backend.  It creates one in-memory
Assessment Session per participant, but does not write to the production audit
database.  The CSV is a research review artifact: it contains opaque
participant ids, answer text, item-level score/evidence fields, safety state,
and the session-level next action (including the cat-probe contract when one
is selected).

The source workbook is never changed.  The four participants removed by the
Q20 quality rule are not present in the derived input and therefore cannot be
scored here.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.assessment.intelligence import SessionAIAdvisor, apply_ai_planning
from backend.app.assessment.orchestrator import build_global_evidence_state
from backend.app.safety.engine import screen
from backend.app.scoring.engine import load_rubrics, score_response
from backend.app.scoring.llm import score_with_configured_provider, configured_scorer


CSV_FIELDS = [
    "participant_id",
    "question_id",
    "response",
    "provider_mode",
    "provider_model",
    "rubric_version",
    "preliminary_score",
    "score_status",
    "evidence_sufficiency",
    "confidence",
    "model_margin",
    "evidence_span_count",
    "decision_reasons",
    "target_gap",
    "clarification_question",
    "item_probe_type",
    "item_pending",
    "item_priority",
    "support_count",
    "conflict_count",
    "safety_state",
    "safety_matched_terms",
    "review_recommended",
    "session_seed_answered",
    "session_unresolved_count",
    "session_human_review_count",
    "session_safety_state",
    "session_next_action_type",
    "session_next_action_question_id",
    "session_next_action_probe_type",
    "session_next_action_priority",
    "session_next_action_rationale",
    "session_cat_probe",
    "review_flags",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _score_item(question_id: str, response: str, rubrics: dict[str, dict[str, Any]], scorer: Any) -> tuple[Any, str, Any]:
    """Mirror the backend's participant score route, including safety gating."""

    safety = screen(response)
    if safety.state != "CLEAR":
        result = score_response(question_id, response, rubrics)
        result.safety_state = safety.state
        result.score_status = "HUMAN_REVIEW"
        result.clarification_question = None
        result.decision_reasons = list(dict.fromkeys([*result.decision_reasons, "SAFETY_REVIEW"]))
        result.review_recommended = True
        return result, "safety-gated", safety
    result, mode = score_with_configured_provider(question_id, response, rubrics, scorer)
    result.safety_state = safety.state
    return result, mode, safety


def _provider_model(scorer: Any, mode: str) -> str:
    if mode == "centroid":
        return str(getattr(scorer, "model_name", "per-item-char-ngram-centroid"))
    if mode == "llm":
        return str(getattr(scorer, "model", "configured-llm"))
    if mode == "safety-gated":
        return "deterministic-keyword-baseline"
    return "deterministic-keyword-baseline"


def _session_state(items: list[dict[str, Any]], rubrics: dict[str, dict[str, Any]], scorer: Any) -> dict[str, Any]:
    deterministic = build_global_evidence_state(items=items, rubrics=rubrics)
    advice = SessionAIAdvisor(scorer).advise(items=items, rubrics=rubrics, state=deterministic)
    return apply_ai_planning(deterministic, advice)


def build_review_rows(records: list[dict[str, Any]], rubrics: dict[str, dict[str, Any]], scorer: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_participant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_participant[record["participant_id"]].append(record)

    output: list[dict[str, Any]] = []
    aggregate_status = Counter()
    aggregate_safety = Counter()
    aggregate_actions = Counter()
    aggregate_reasons = Counter()
    aggregate_next_questions = Counter()
    provider_modes = Counter()

    for participant_id in sorted(by_participant):
        source_records = sorted(by_participant[participant_id], key=lambda value: value["question_id"])
        items: list[dict[str, Any]] = []
        scored: list[tuple[dict[str, Any], Any, str, Any]] = []
        for record in source_records:
            result, mode, safety = _score_item(record["question_id"], record["response"], rubrics, scorer)
            payload = result.model_dump()
            payload["provider"] = mode
            payload["model"] = _provider_model(scorer, mode)
            item = {
                "event_id": f"review:{participant_id}:{record['question_id']}",
                "question_id": record["question_id"],
                "event_type": "INITIAL",
                "response": record["response"],
                "clarification_round": 0,
                "score": payload,
                "safety": safety.model_dump(),
            }
            items.append(item)
            scored.append((record, result, mode, safety))
            aggregate_status[result.score_status] += 1
            aggregate_safety[safety.state] += 1
            provider_modes[mode] += 1
            aggregate_reasons.update(result.decision_reasons)

        state = _session_state(items, rubrics, scorer)
        action = state.get("next_action") or {}
        action_type = str(action.get("type") or "")
        aggregate_actions[action_type] += 1
        if action.get("question_id"):
            aggregate_next_questions[str(action["question_id"])] += 1
        latest_by_question = {node["question_id"]: node for node in state.get("nodes", [])}
        unresolved_count = len(state.get("unresolved_gaps") or [])
        human_review_count = sum(node.get("status") == "HUMAN_REVIEW" for node in state.get("nodes", []))
        session_safety = "SAFETY_REVIEW" if action_type == "SAFETY_FLOW" else "CLEAR"
        cat_probe = action.get("interaction") if action_type in {"CLARIFY_NOW", "CONFIRM_NOW"} else None
        session_flags = []
        if action_type == "SAFETY_FLOW":
            session_flags.append("SAFETY_FLOW")
        if unresolved_count:
            session_flags.append("UNRESOLVED_ITEMS")
        if human_review_count:
            session_flags.append("HUMAN_REVIEW_BURDEN")

        for record, result, mode, safety in scored:
            node = latest_by_question.get(record["question_id"], {})
            flags: list[str] = []
            if result.score_status == "PROVISIONAL":
                flags.append("SEMANTIC_GAP")
            if "MODEL_UNCERTAINTY" in result.decision_reasons:
                flags.append("MODEL_UNCERTAINTY")
            if safety.state != "CLEAR":
                flags.append("SAFETY_REVIEW")
            if record["question_id"] == "Q20" and record["response"].strip():
                flags.append("Q20_VALID_INCLUDED")
            if node.get("pending"):
                flags.append("PENDING_PROBE")
            if result.review_recommended:
                flags.append("REVIEW_RECOMMENDED")
            if not flags:
                flags.append("NO_FLAG")
            output.append({
                "participant_id": participant_id,
                "question_id": record["question_id"],
                "response": record["response"],
                "provider_mode": mode,
                "provider_model": _provider_model(scorer, mode),
                "rubric_version": result.rubric_version,
                "preliminary_score": result.preliminary_score,
                "score_status": result.score_status,
                "evidence_sufficiency": result.evidence_sufficiency,
                "confidence": result.confidence,
                "model_margin": result.model_margin,
                "evidence_span_count": len(result.evidence_spans),
                "decision_reasons": _json(result.decision_reasons),
                "target_gap": result.target_gap or "",
                "clarification_question": result.clarification_question or "",
                "item_probe_type": node.get("probe_type") or "",
                "item_pending": bool(node.get("pending")),
                "item_priority": node.get("priority", 0.0),
                "support_count": node.get("support_count", 0),
                "conflict_count": node.get("conflict_count", 0),
                "safety_state": safety.state,
                "safety_matched_terms": _json(safety.matched_terms),
                "review_recommended": bool(result.review_recommended),
                "session_seed_answered": state.get("seed_answered", 0),
                "session_unresolved_count": unresolved_count,
                "session_human_review_count": human_review_count,
                "session_safety_state": session_safety,
                "session_next_action_type": action_type,
                "session_next_action_question_id": action.get("question_id") or "",
                "session_next_action_probe_type": action.get("probe_type") or "",
                "session_next_action_priority": action.get("priority", 0.0),
                "session_next_action_rationale": action.get("rationale") or "",
                "session_cat_probe": _json(cat_probe) if cat_probe else "",
                "review_flags": _json(flags + [flag for flag in session_flags if flag not in flags]),
            })

    summary = {
        "participants": len(by_participant),
        "responses": len(output),
        "provider_modes": dict(provider_modes),
        "score_status": dict(aggregate_status),
        "safety_state": dict(aggregate_safety),
        "session_next_actions": dict(aggregate_actions),
        "session_next_questions": dict(aggregate_next_questions),
        "decision_reasons": dict(aggregate_reasons),
        "q20_out_of_range_in_input": sum(
            1 for record in records
            if record["question_id"] == "Q20" and record["response"].strip() in {"30", "70", "80"}
        ),
        "note": "No legacy or expert labels exist for this answer-only survey; score correctness requires subsequent expert adjudication.",
    }
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/derived/real_survey/responses.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("data/derived/real_survey/project_review.csv"))
    args = parser.parse_args()
    records = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    rubrics = load_rubrics(ROOT)
    scorer, mode = configured_scorer(rubrics)
    rows, summary = build_review_rows(records, rubrics, scorer)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary["configured_mode"] = mode
    summary["csv"] = str(args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
