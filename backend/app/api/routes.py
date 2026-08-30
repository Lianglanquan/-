"""HTTP routes for participant assessment and protected research work."""

from __future__ import annotations

import json
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field, field_validator

from backend.app.assessment.service import AssessmentStore
from backend.app.audit.store import AuditStore
from backend.app.safety.engine import screen
from backend.app.scoring.engine import evidence_gap, load_rubrics, score_response
from backend.app.scoring.llm import configured_scorer, score_with_configured_provider
from backend.app.security import require_research_access


ROOT = Path(__file__).resolve().parents[3]
RUBRICS = load_rubrics(ROOT)
AUDIT = AuditStore(ROOT / "data" / "derived" / "audit.sqlite3")
SCORER, SCORER_MODE = configured_scorer(RUBRICS)
STORE = AssessmentStore(RUBRICS, scorer=SCORER, audit=AUDIT, root=ROOT)
router = APIRouter(prefix="/api")


class ScoreRequest(BaseModel):
    question_id: str = Field(pattern=r"^Q(?:0[1-9]|1[0-9]|20)$")
    response: str = Field(min_length=1, max_length=5000)

    @field_validator("response")
    @classmethod
    def validate_response(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("response must contain non-whitespace text")
        return value


class ResponseRequest(ScoreRequest):
    clarification: bool = False
    probe_type: str | None = Field(default=None, pattern=r"^(CLARIFICATION|DISAMBIGUATION|CONFIRMATION)$")
    probe_option_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    probe_action: Literal["ANSWER", "PAUSE"] = "ANSWER"


class ReviewRequest(BaseModel):
    adjudicated_score: int | None = Field(default=None, ge=0, le=2)
    evidence_sufficiency: str
    note: str = Field(default="", max_length=4000)

    @field_validator("evidence_sufficiency")
    @classmethod
    def validate_sufficiency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"SUFFICIENT", "INSUFFICIENT", "EXPERT_DISAGREEMENT"}:
            raise ValueError("evidence_sufficiency must be SUFFICIENT, INSUFFICIENT, or EXPERT_DISAGREEMENT")
        return normalized


@router.get("/questions")
def questions() -> list[dict[str, Any]]:
    return [{"id": item_id, "question": data.get("question", ""), "dimension": data.get("dimension", ""), "criteria": data.get("criteria", [])} for item_id, data in sorted(RUBRICS.items())]


def _provider_model(mode: str) -> str:
    if mode == "llm":
        return str(getattr(SCORER, "model", "configured-llm"))
    if mode == "centroid":
        return str(getattr(SCORER, "model_name", "per-item-char-ngram-centroid"))
    if mode == "deterministic-fallback":
        return "deterministic-keyword-baseline"
    return str(getattr(SCORER, "name", "deterministic-keyword-baseline"))


def _score_request(question_id: str, response: str) -> tuple[dict[str, Any], str]:
    safety = screen(response)
    if safety.state != "CLEAR":
        result, mode = score_response(question_id, response, RUBRICS), "safety-gated"
        result.safety_state = safety.state
        result.score_status = "HUMAN_REVIEW"
        result.clarification_question = None
        result.decision_reasons = list(dict.fromkeys([*result.decision_reasons, "SAFETY_REVIEW"]))
        result.review_recommended = True
    else:
        result, mode = score_with_configured_provider(question_id, response, RUBRICS, SCORER)
    output = result.model_dump()
    output["provider"] = mode
    output["model"] = _provider_model(mode)
    output["safety"] = safety.model_dump()
    return output, mode


@router.post("/score")
def score(request: ScoreRequest) -> dict[str, Any]:
    output, _ = _score_request(request.question_id, request.response)
    return output


@router.get("/provider")
def provider_status() -> dict[str, str]:
    session_ai = "llm-advisory" if callable(getattr(SCORER, "analyze_session", None)) else "rule-fallback"
    return {
        "mode": SCORER_MODE,
        "provider": getattr(SCORER, "name", "deterministic-keyword-baseline"),
        "model": _provider_model(SCORER_MODE),
        "session_intelligence": session_ai,
    }


@router.post("/assessment/start")
def start_assessment() -> dict[str, Any]:
    return STORE.start()


@router.post("/assessment/{session_id}/responses")
def assessment_response(session_id: str, request: ResponseRequest) -> dict[str, Any]:
    try:
        return STORE.respond(
            session_id,
            request.question_id,
            request.response,
            request.clarification,
            request.probe_type,
            request.probe_option_id,
            request.probe_action,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/assessment/{session_id}")
def assessment(session_id: str) -> dict[str, Any]:
    value = STORE.get(session_id)
    if value is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    return value


def _records() -> list[dict[str, Any]]:
    path = ROOT / "data" / "derived" / "responses.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normal(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("。！？!?，,；; ")


def _historical_review_cases(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["question_id"], _normal(record.get("response", "")))].append(record)
    conflicting_keys = {key for key, rows in grouped.items() if len(rows) > 1 and len({row.get("legacy_score") for row in rows}) > 1 and key[1]}
    cases = []
    for record in records:
        gap = evidence_gap(record["question_id"], record.get("response", ""), RUBRICS.get(record["question_id"], {}))
        reasons: list[str] = []
        if gap:
            reasons.append(gap[0])
        if (record["question_id"], _normal(record.get("response", ""))) in conflicting_keys:
            reasons.append("CONFLICTING_LEGACY_LABELS")
        mentioned = {int(value) for value in re.findall(r"(?<!\d)([012])\s*分", record.get("legacy_rationale", ""))}
        if mentioned and record.get("legacy_score") not in mentioned:
            reasons.append("RATIONALE_SCORE_MISMATCH_CANDIDATE")
        if not reasons:
            continue
        cases.append({
            "response_id": _public_historical_id(record["response_id"]), "source": "historical", "participant_id": record["participant_id"],
            "question_id": record["question_id"], "response": record["response"], "legacy_score": record.get("legacy_score"),
            "legacy_rationale": record.get("legacy_rationale", ""), "evidence_sufficiency": "UNASSESSED",
            "reason_codes": reasons, "payload": record,
        })
    return cases


def _public_historical_id(response_id: str) -> str:
    """Expose a stable opaque case id without leaking the participant id."""

    return "historical:" + hashlib.sha256(response_id.encode("utf-8")).hexdigest()[:20]


def _seed_historical_review_cases() -> None:
    for case in _historical_review_cases(_records()):
        AUDIT.upsert_review_case(case)


@router.get("/research/summary")
def research_summary(_: str = Depends(require_research_access)) -> dict[str, Any]:
    _seed_historical_review_cases()
    records = _records()
    total = len(records)
    score_counts = {str(score): sum(r.get("legacy_score") == score for r in records) for score in (0, 1, 2)}
    questions_summary = []
    for question_id in sorted({r["question_id"] for r in records}):
        subset = [r for r in records if r["question_id"] == question_id]
        candidates = sum(evidence_gap(question_id, r.get("response", ""), RUBRICS.get(question_id, {})) is not None for r in subset)
        questions_summary.append({"id": question_id, "n": len(subset), "mean_score": round(sum(r["legacy_score"] for r in subset) / len(subset), 2), "provisional_candidates": candidates})
    evaluation = {}
    evaluation_path = ROOT / "data" / "derived" / "evaluation.json"
    if evaluation_path.exists():
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    return {
        "participants": len({r["participant_id"] for r in records}), "responses": total, "score_counts": score_counts,
        "questions": questions_summary, "splits": {split: len({r["participant_id"] for r in records if r["split"] == split}) for split in ("train", "validation", "test")},
        "review_queue": AUDIT.counts(), "assessment_runtime": AUDIT.assessment_metrics(), "evaluation": evaluation,
    }


@router.get("/review/cases")
def review_cases(limit: int = 40, offset: int = 0, source: str | None = None, _: str = Depends(require_research_access)) -> list[dict[str, Any]]:
    _seed_historical_review_cases()
    return AUDIT.list_review_cases(limit=limit, offset=offset, source=source)


@router.get("/review/{response_id:path}")
def review_case(response_id: str, _: str = Depends(require_research_access)) -> dict[str, Any]:
    _seed_historical_review_cases()
    case = AUDIT.get_review_case(response_id)
    if case is None:
        raise HTTPException(status_code=404, detail="review case not found")
    return case


@router.post("/review/{response_id:path}")
def review(
    response_id: str,
    request: ReviewRequest,
    reviewer: str = Depends(require_research_access),
    x_research_reviewer: str | None = Header(default=None),
) -> dict[str, Any]:
    _seed_historical_review_cases()
    reviewer_name = (x_research_reviewer or reviewer or "researcher").strip()[:120]
    try:
        return AUDIT.record_review(
            response_id,
            adjudicated_score=request.adjudicated_score,
            evidence_sufficiency=request.evidence_sufficiency,
            note=request.note,
            reviewer=reviewer_name,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review case not found") from exc


@router.post("/research/adjudications/export")
def export_adjudications(_: str = Depends(require_research_access)) -> dict[str, Any]:
    """Export expert-confirmed session cases for the next research cycle.

    The artifact is generated under ``data/derived`` and contains no legacy
    labels as a substitute for expert decisions.  It is an input to a human-
    reviewed dataset/model/rubric evolution cycle, not an automatic retrain.
    """

    path = ROOT / "data" / "derived" / "adjudicated_dataset.jsonl"
    return AUDIT.export_adjudicated_dataset(path)
