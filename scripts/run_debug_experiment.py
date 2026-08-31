"""Run the configured scorer over the labeled debug workbook.

The workbook's legacy score and rationale are retained for agreement analysis,
but only ``question_id`` and ``response`` are sent to the scorer.  Results are
checkpointed as JSONL so a transient provider failure or process interruption
does not discard completed calls.  The final JSON/CSV artifacts are local
research outputs and must not be committed because they contain response text.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.assessment.intelligence import SessionAIAdvisor, apply_ai_planning
from backend.app.assessment.orchestrator import build_global_evidence_state
from backend.app.safety.engine import screen
from backend.app.scoring.engine import ScoreResult, load_rubrics, score_response
from backend.app.scoring.llm import configured_scorer, score_with_configured_provider
from scripts.parse_excel import parse_workbook


RESULT_FIELDS = [
    "response_id",
    "participant_id",
    "question_id",
    "source_question_code",
    "response",
    "legacy_score",
    "legacy_rationale",
    "ai_score",
    "ai_rationale",
    "ai_evidence_spans",
    "ai_evidence_sufficiency",
    "ai_score_status",
    "ai_confidence",
    "ai_model_margin",
    "ai_target_gap",
    "ai_clarification_question",
    "ai_decision_reasons",
    "ai_review_recommended",
    "provider_mode",
    "provider_model",
    "rubric_version",
    "safety_state",
    "safety_matched_terms",
    "agreement",
    "score_difference",
    "needs_human_review",
    "historical_rationale_score_mismatch",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _provider_model(scorer: Any, mode: str) -> str:
    if mode == "llm":
        return str(getattr(scorer, "model", "configured-llm"))
    if mode == "centroid":
        return str(getattr(scorer, "model_name", "per-item-char-ngram-centroid"))
    if mode == "safety-gated":
        return "deterministic-keyword-baseline"
    return "deterministic-keyword-baseline"


def _historical_rationale_mismatch(record: dict[str, Any]) -> bool:
    rationale = str(record.get("legacy_rationale") or "")
    mentioned = {int(value) for value in __import__("re").findall(r"(?<!\d)([012])\s*分", rationale)}
    legacy = record.get("legacy_score")
    return bool(mentioned and legacy in (0, 1, 2) and legacy not in mentioned)


def _score_for_record(record: dict[str, Any], rubrics: dict[str, dict[str, Any]], scorer: Any) -> tuple[ScoreResult, str, Any]:
    """Mirror the API score route without sending legacy annotations."""

    question_id = str(record["question_id"])
    response = str(record.get("response") or "")
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


def score_record(record: dict[str, Any], rubrics: dict[str, dict[str, Any]], scorer: Any) -> dict[str, Any]:
    """Score one row and return a flat, spreadsheet-friendly audit record."""

    result, mode, safety = _score_for_record(record, rubrics, scorer)
    legacy_score = record.get("legacy_score")
    ai_score = result.preliminary_score
    comparable = legacy_score in (0, 1, 2)
    status = result.score_status
    needs_review = bool(result.review_recommended or status == "HUMAN_REVIEW" or result.evidence_sufficiency != "SUFFICIENT")
    return {
        "response_id": record.get("response_id", ""),
        "participant_id": record.get("participant_id", ""),
        "question_id": record.get("question_id", ""),
        "source_question_code": record.get("source_question_code", ""),
        "response": record.get("response", ""),
        "legacy_score": legacy_score,
        "legacy_rationale": record.get("legacy_rationale", ""),
        "ai_score": ai_score,
        "ai_rationale": result.rationale,
        "ai_evidence_spans": _json([span.model_dump() for span in result.evidence_spans]),
        "ai_evidence_sufficiency": result.evidence_sufficiency,
        "ai_score_status": status,
        "ai_confidence": result.confidence,
        "ai_model_margin": result.model_margin,
        "ai_target_gap": result.target_gap or "",
        "ai_clarification_question": result.clarification_question or "",
        "ai_decision_reasons": _json(result.decision_reasons),
        "ai_review_recommended": bool(result.review_recommended),
        "provider_mode": mode,
        "provider_model": _provider_model(scorer, mode),
        "rubric_version": result.rubric_version,
        "safety_state": safety.state,
        "safety_matched_terms": _json(safety.matched_terms),
        "agreement": ("一致" if comparable and ai_score == legacy_score else "不一致") if comparable else "未比较",
        "score_difference": (ai_score - legacy_score) if comparable else None,
        "needs_human_review": needs_review,
        "historical_rationale_score_mismatch": _historical_rationale_mismatch(record),
    }


def _kappa(rows: list[dict[str, Any]], weighted: bool = False) -> float | None:
    pairs = [(int(row["legacy_score"]), int(row["ai_score"])) for row in rows if row.get("legacy_score") in (0, 1, 2) and row.get("ai_score") in (0, 1, 2)]
    if not pairs:
        return None
    labels = (0, 1, 2)
    total = len(pairs)
    observed = sum((1.0 if actual == predicted else 0.0) if not weighted else (1.0 - abs(actual - predicted) / 2.0) for actual, predicted in pairs) / total
    actual_counts = Counter(actual for actual, _ in pairs)
    predicted_counts = Counter(predicted for _, predicted in pairs)
    expected = sum(
        ((1.0 if actual == predicted else 0.0) if not weighted else (1.0 - abs(actual - predicted) / 2.0))
        * actual_counts[actual] * predicted_counts[predicted]
        for actual in labels
        for predicted in labels
    ) / (total * total)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def _metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = [row for row in rows if row.get("legacy_score") in (0, 1, 2) and row.get("ai_score") in (0, 1, 2)]
    n = len(comparable)
    confusion = {f"{actual}->{predicted}": 0 for actual in (0, 1, 2) for predicted in (0, 1, 2)}
    for row in comparable:
        confusion[f"{row['legacy_score']}->{row['ai_score']}"] += 1
    f1s: list[float] = []
    recalls: list[float] = []
    per_class: dict[str, dict[str, float]] = {}
    for label in (0, 1, 2):
        tp = confusion[f"{label}->{label}"]
        fp = sum(confusion[f"{actual}->{label}"] for actual in (0, 1, 2) if actual != label)
        fn = sum(confusion[f"{label}->{predicted}"] for predicted in (0, 1, 2) if predicted != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[str(label)] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
        f1s.append(f1)
        recalls.append(recall)
    covered = [row for row in comparable if row.get("ai_score_status") == "CONFIRMED" and row.get("ai_evidence_sufficiency") == "SUFFICIENT" and row.get("safety_state") == "CLEAR"]
    selective_accuracy = sum(row["legacy_score"] == row["ai_score"] for row in covered) / len(covered) if covered else None
    return {
        "n": n,
        "accuracy": sum(row["legacy_score"] == row["ai_score"] for row in comparable) / n if n else None,
        "macro_f1": sum(f1s) / 3 if n else None,
        "balanced_accuracy": sum(recalls) / 3 if n else None,
        "cohen_kappa": _kappa(comparable),
        "weighted_kappa": _kappa(comparable, weighted=True),
        "per_class": per_class,
        "confusion": confusion,
        "selective": {
            "covered": len(covered),
            "coverage": len(covered) / n if n else None,
            "accuracy_on_covered": selective_accuracy,
            "risk_on_covered": (1.0 - selective_accuracy) if selective_accuracy is not None else None,
        },
    }


def compute_consistency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_question: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_question[str(row.get("question_id", ""))].append(row)
    status = Counter(str(row.get("ai_score_status", "")) for row in rows)
    provider_modes = Counter(str(row.get("provider_mode", "")) for row in rows)
    provisional_by_legacy = Counter(str(row["legacy_score"]) for row in rows if row.get("ai_score_status") == "PROVISIONAL" and row.get("legacy_score") in (0, 1, 2))
    return {
        **_metric_block(rows),
        "participants": len({row.get("participant_id") for row in rows}),
        "responses": len(rows),
        "provider_modes": dict(provider_modes),
        "score_status": dict(status),
        "provisional_by_legacy_score": dict(provisional_by_legacy),
        "historical_rationale_score_mismatch_candidates": sum(bool(row.get("historical_rationale_score_mismatch")) for row in rows),
        "by_question": {question_id: _metric_block(subset) for question_id, subset in sorted(by_question.items()) if question_id},
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _session_summary(rows: list[dict[str, Any]], rubrics: dict[str, dict[str, Any]], scorer: Any) -> dict[str, Any]:
    participant_id = str(rows[0]["participant_id"])
    items = []
    for row in sorted(rows, key=lambda value: value["question_id"]):
        items.append({
            "event_id": f"experiment:{participant_id}:{row['question_id']}",
            "question_id": row["question_id"],
            "event_type": "INITIAL",
            "response": row["response"],
            "clarification_round": 0,
            "score": {
                "preliminary_score": row["ai_score"],
                "score_status": row["ai_score_status"],
                "evidence_sufficiency": row["ai_evidence_sufficiency"],
                "confidence": row["ai_confidence"],
                "decision_reasons": json.loads(row["ai_decision_reasons"] or "[]"),
                "target_gap": row["ai_target_gap"] or None,
                "clarification_question": row["ai_clarification_question"] or None,
            },
            "safety": {"state": row["safety_state"]},
        })
    deterministic = build_global_evidence_state(items=items, rubrics=rubrics)
    advice = SessionAIAdvisor(scorer).advise(items=items, rubrics=rubrics, state=deterministic)
    state = apply_ai_planning(deterministic, advice)
    action = state.get("next_action") or {}
    intelligence = state.get("session_intelligence") or {}
    return {
        "participant_id": participant_id,
        "seed_answered": state.get("seed_answered", 0),
        "seed_total": state.get("seed_total", 20),
        "unresolved_count": len(state.get("unresolved_gaps") or []),
        "human_review_count": sum(node.get("status") == "HUMAN_REVIEW" for node in state.get("nodes", [])),
        "next_action_type": action.get("type", ""),
        "next_action_question_id": action.get("question_id", ""),
        "next_action_probe_type": action.get("probe_type", ""),
        "next_action_rationale": action.get("rationale", ""),
        "session_ai_status": intelligence.get("status", ""),
        "session_ai_provider": intelligence.get("provider", ""),
        "session_ai_model": intelligence.get("model", ""),
        "session_summary": intelligence.get("session_summary", ""),
        "session_planning_notes": _json(intelligence.get("planning_notes") or []),
        "session_cat_probe": _json(action.get("interaction")) if action.get("interaction") else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, default=ROOT / "data/raw/系统调试样本.xlsx")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data/derived/debug_experiment")
    parser.add_argument("--participant-limit", type=int, default=None, help="Only process the first N participants (useful for smoke tests).")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-session-ai", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be >= 1")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records = parse_workbook(args.xlsx)
    participant_ids = sorted({record["participant_id"] for record in records})
    if args.participant_limit is not None:
        participant_ids = participant_ids[: max(0, args.participant_limit)]
    selected = [record for record in records if record["participant_id"] in set(participant_ids)]
    rubrics = load_rubrics(ROOT)
    scorer, configured_mode = configured_scorer(rubrics)

    checkpoint = args.out_dir / "score_checkpoints.jsonl"
    cached: dict[str, dict[str, Any]] = {}
    if not args.no_resume:
        for row in _read_jsonl(checkpoint):
            if row.get("response_id"):
                cached[str(row["response_id"])] = row
    pending = [record for record in selected if str(record.get("response_id")) not in cached]
    if pending:
        with checkpoint.open("a", encoding="utf-8") as handle:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {executor.submit(score_record, record, rubrics, scorer): record for record in pending}
                for future in as_completed(futures):
                    row = future.result()
                    cached[str(row["response_id"])] = row
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    handle.flush()

    rows = [cached[str(record["response_id"])] for record in selected if str(record.get("response_id")) in cached]
    _write_jsonl(args.out_dir / "results.jsonl", rows)
    with (args.out_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    session_rows: list[dict[str, Any]] = []
    if not args.skip_session_ai:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["participant_id"])].append(row)
        for participant_id in sorted(grouped):
            group = grouped[participant_id]
            if len(group) != 20:
                continue
            session_rows.append(_session_summary(group, rubrics, scorer))
        _write_jsonl(args.out_dir / "session_results.jsonl", session_rows)

    summary = compute_consistency_summary(rows)
    summary.update({
        "source_xlsx": str(args.xlsx),
        "configured_mode": configured_mode,
        "configured_provider": getattr(scorer, "name", "deterministic-keyword-baseline"),
        "configured_model": _provider_model(scorer, configured_mode),
        "participants_requested": len(participant_ids),
        "session_ai_participants": len(session_rows),
        "resume_checkpoint": str(checkpoint),
        "data_sha256": hashlib.sha256(args.xlsx.read_bytes()).hexdigest(),
    })
    (args.out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "participants": summary["participants"],
        "responses": summary["responses"],
        "configured_mode": configured_mode,
        "configured_model": summary["configured_model"],
        "provider_modes": summary["provider_modes"],
        "accuracy": summary.get("accuracy"),
        "macro_f1": summary.get("macro_f1"),
        "selective": summary.get("selective"),
        "session_ai_participants": len(session_rows),
        "out_dir": str(args.out_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
