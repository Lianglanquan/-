"""HTTP routes for participant assessment and protected research work."""

from __future__ import annotations

import json
import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Header, Response
from pydantic import BaseModel, Field, field_validator

from backend.app.assessment.service import AssessmentStore
from backend.app.assessment.reporting import build_population_summary, build_session_evidence_report
from backend.app.audit.store import AuditStore
from backend.app.auth.mailer import MailDeliveryError, ResendMailer
from backend.app.auth.service import AuthError, AuthService
from backend.app.config import load_local_env, runtime_data_root
from backend.app.safety.engine import screen
from backend.app.scoring.catalog import catalog_for_session, load_active_catalog
from backend.app.scoring.engine import evidence_gap, load_active_rubrics, score_response
from backend.app.scoring.llm import configured_scorer, score_with_configured_provider
from backend.app.security import (
    SESSION_COOKIE,
    _session_token,
    require_admin_access,
    require_current_user,
    require_research_access,
)


ROOT = Path(__file__).resolve().parents[3]
ACTIVE_CATALOG = load_active_catalog(ROOT)
RUBRICS = ACTIVE_CATALOG.rubrics
RUNTIME_DATA = runtime_data_root()
AUDIT = AuditStore(RUNTIME_DATA / "audit.sqlite3")
SCORER, SCORER_MODE = configured_scorer(RUBRICS)
STORE = AssessmentStore(RUBRICS, scorer=SCORER, audit=AUDIT, root=ROOT)
AUTH = AuthService(AUDIT, mailer=ResendMailer())
router = APIRouter(prefix="/api")


class RegisterRequest(BaseModel):
    email: str
    password: str
    password_confirmation: str


class VerifyEmailRequest(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(VerifyEmailRequest):
    new_password: str


class AdminRoleRequest(BaseModel):
    role: Literal["ADMIN", "PARTICIPANT"]


class AdminActiveRequest(BaseModel):
    is_active: bool


class AdminInviteRequest(BaseModel):
    email: str


class ScoreRequest(BaseModel):
    question_id: str = Field(pattern=r"^Q(?:0[1-9]|1[0-9])$")
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
    return [{"id": item_id, "question": data.get("question", ""), "dimension": data.get("dimension", ""), "construct": data.get("construct", ""), "criteria": data.get("criteria", [])} for item_id, data in sorted(RUBRICS.items())]


def _session_rubrics(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return catalog_for_session(session, ROOT).rubrics


def _auth_failure(exc: Exception) -> HTTPException:
    if isinstance(exc, MailDeliveryError):
        return HTTPException(status_code=503, detail="邮箱服务暂时不可用，请稍后重试。")
    return HTTPException(status_code=400, detail=str(exc))


def _set_session_cookie(response: Response, token: str) -> None:
    load_local_env()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"},
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )


@router.post("/auth/register")
def register(request: RegisterRequest, response: Response) -> dict[str, Any]:
    try:
        AUTH.register(request.email, request.password, request.password_confirmation)
        user, token = AUTH.login(request.email, request.password)
    except (AuthError, MailDeliveryError) as exc:
        raise _auth_failure(exc) from exc
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/auth/verify-email")
def verify_email(request: VerifyEmailRequest) -> dict[str, Any]:
    try:
        return AUTH.verify_email(request.email, request.code)
    except AuthError as exc:
        raise _auth_failure(exc) from exc


@router.post("/auth/resend-verification")
def resend_verification(request: PasswordResetRequest) -> dict[str, str]:
    try:
        AUTH.resend_verification(request.email)
    except (AuthError, MailDeliveryError) as exc:
        raise _auth_failure(exc) from exc
    return {"message": "如果这个邮箱还没有完成验证，新的验证码会发送到邮箱。"}


@router.post("/auth/login")
def login(request: LoginRequest, response: Response) -> dict[str, Any]:
    try:
        user, token = AUTH.login(request.email, request.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/auth/logout")
def logout(response: Response, token: str | None = Depends(_session_token)) -> dict[str, bool]:
    AUTH.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/auth/request-reset")
def request_reset(request: PasswordResetRequest) -> dict[str, str]:
    try:
        AUTH.request_password_reset(request.email)
    except (AuthError, MailDeliveryError) as exc:
        # Keep invalid email syntax visible, but never reveal account existence.
        raise _auth_failure(exc) from exc
    return {"message": "如果这个邮箱已经注册，验证码会发送到邮箱。"}


@router.post("/auth/reset-password")
def reset_password(request: PasswordResetConfirmRequest) -> dict[str, bool]:
    try:
        AUTH.reset_password(request.email, request.code, request.new_password)
    except AuthError as exc:
        raise _auth_failure(exc) from exc
    return {"ok": True}


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
def start_assessment(user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    return STORE.start(user_id=user["id"])


@router.post("/assessment/{session_id}/responses")
def assessment_response(session_id: str, request: ResponseRequest, user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    try:
        return STORE.respond(
            session_id,
            request.question_id,
            request.response,
            request.clarification,
            request.probe_type,
            request.probe_option_id,
            request.probe_action,
            user_id=user["id"],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/assessment/{session_id}")
def assessment(session_id: str, user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    try:
        value = STORE.get(session_id, user_id=user["id"], allow_admin=user.get("role") == "ADMIN")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    return value


@router.get("/admin/users")
def admin_users(admin: dict[str, Any] = Depends(require_admin_access)) -> list[dict[str, Any]]:
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=None, session_id=None, action="LIST", resource="users")
    return AUDIT.list_users()


@router.post("/admin/users/{user_id}/role")
def admin_set_role(user_id: str, request: AdminRoleRequest, admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    try:
        return AUTH.admin_set_role(admin["id"], user_id, request.role)
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/admin/users/{user_id}/active")
def admin_set_active(user_id: str, request: AdminActiveRequest, admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    try:
        return AUTH.admin_set_active(admin["id"], user_id, request.is_active)
    except AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/admin/invites")
def admin_invite(request: AdminInviteRequest, admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    try:
        return AUTH.admin_invite(admin["id"], request.email)
    except AuthError as exc:
        raise _auth_failure(exc) from exc


@router.get("/admin/audit")
def admin_audit(admin: dict[str, Any] = Depends(require_admin_access), limit: int = 200) -> list[dict[str, Any]]:
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=None, session_id=None, action="LIST", resource="admin_access_logs")
    return AUDIT.list_admin_access_logs(limit=limit)


@router.get("/admin/sessions")
def admin_sessions(admin: dict[str, Any] = Depends(require_admin_access), limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=None, session_id=None, action="LIST", resource="sessions")
    return AUDIT.list_all_sessions(limit=limit, offset=offset)


@router.get("/admin/sessions/{session_id}")
def admin_session(session_id: str, admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    try:
        value = STORE.get(session_id, allow_admin=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    if value is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    if value.get("user_id"):
        value["email"] = next((user.get("email") for user in AUDIT.list_users() if user.get("id") == value.get("user_id")), None)
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=value.get("user_id"), session_id=session_id, action="READ", resource="assessment_session")
    return value


@router.get("/admin/sessions/{session_id}/report")
def admin_session_report(session_id: str, admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    try:
        value = STORE.get(session_id, allow_admin=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    if value is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=value.get("user_id"), session_id=session_id, action="READ", resource="assessment_report")
    report = build_session_evidence_report(value, _session_rubrics(value))
    # Every unresolved node receives a stable session-scoped case id when an
    # administrator opens the report.  This makes the next step actionable
    # without exposing a separate, disconnected research queue.
    for gap in report.get("review_queue", []):
        question_id = str(gap.get("question_id") or "")
        if question_id:
            AUDIT.ensure_session_review_case(session_id, question_id)
    return report


@router.get("/admin/sessions/{session_id}/review/{question_id}")
def admin_session_review_case(session_id: str, question_id: str, admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    """Open one unresolved node in the context of its original session."""

    try:
        value = STORE.get(session_id, allow_admin=True)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    if value is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    session_rubrics = _session_rubrics(value)
    if question_id not in session_rubrics:
        raise HTTPException(status_code=404, detail="review node not found")
    case = AUDIT.ensure_session_review_case(session_id, question_id)
    if case is None:
        raise HTTPException(status_code=404, detail="review node not found")
    case["question"] = session_rubrics[question_id].get("question", "")
    case["dimension"] = session_rubrics[question_id].get("dimension", "")
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=value.get("user_id"), session_id=session_id, action="READ", resource="session_review_case")
    return case


@router.post("/admin/sessions/{session_id}/review/{question_id}")
def adjudicate_admin_session_review(
    session_id: str,
    question_id: str,
    request: ReviewRequest,
    admin: dict[str, Any] = Depends(require_admin_access),
) -> dict[str, Any]:
    """Save an expert decision and immediately rebuild the same report."""

    try:
        value = STORE.get(session_id, allow_admin=True)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail="assessment session not found") from exc
    if value is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    session_rubrics = _session_rubrics(value)
    if question_id not in session_rubrics:
        raise HTTPException(status_code=404, detail="review node not found")
    case = AUDIT.ensure_session_review_case(session_id, question_id)
    if case is None:
        raise HTTPException(status_code=404, detail="review node not found")
    try:
        review = AUDIT.record_review(
            case["response_id"],
            adjudicated_score=request.adjudicated_score,
            evidence_sufficiency=request.evidence_sufficiency,
            note=request.note,
            reviewer=str(admin.get("email") or admin.get("id") or "administrator"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review node not found") from exc
    refreshed = STORE.get(session_id, allow_admin=True)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="assessment session not found")
    report = build_session_evidence_report(refreshed, _session_rubrics(refreshed))
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=refreshed.get("user_id"), session_id=session_id, action="ADJUDICATE", resource="session_review_case")
    return {"review": review, "session_id": session_id, "question_id": question_id, "report": report}


@router.get("/admin/overview")
def admin_overview(admin: dict[str, Any] = Depends(require_admin_access)) -> dict[str, Any]:
    AUDIT.record_admin_access(admin_user_id=admin["id"], target_user_id=None, session_id=None, action="LIST", resource="overview")
    sessions = AUDIT.list_all_sessions(limit=200, offset=0)
    review_priorities: list[dict[str, Any]] = []
    safety_sessions: list[dict[str, Any]] = []
    awaiting_review = 0
    completed = 0
    for session in sessions:
        status = str(session.get("status") or "")
        if status == "AWAITING_REVIEW":
            awaiting_review += 1
        if status == "COMPLETED":
            completed += 1
        metadata = session.get("metadata") or {}
        evidence = metadata.get("latest_global_evidence") or {}
        report = metadata.get("latest_admin_report") or {}
        if report.get("safety_triggered") or status == "SAFETY_REVIEW":
            safety_sessions.append({
                "session_id": session["id"],
                "email": session.get("email"),
                "updated_at": session.get("updated_at"),
                "status": status,
            })
        for gap in evidence.get("unresolved_gaps") or []:
            review_priorities.append({
                "session_id": session["id"],
                "email": session.get("email"),
                "question_id": gap.get("question_id"),
                "priority": gap.get("priority", 0),
                "status": gap.get("status", "OPEN"),
                "target_gap": gap.get("target_gap") or gap.get("clarification_question"),
                "support_count": gap.get("support_count", 0),
                "conflict_count": gap.get("conflict_count", 0),
                "updated_at": session.get("updated_at"),
            })
    review_priorities.sort(key=lambda row: (float(row.get("priority") or 0), str(row.get("updated_at") or "")), reverse=True)
    return {
        "updated_at": max((session.get("updated_at") or "" for session in sessions), default=None),
        "counts": {
            "sessions": len(sessions),
            "completed": completed,
            "awaiting_review": awaiting_review,
            "safety_sessions": len(safety_sessions),
            "open_nodes": len(review_priorities),
        },
        "recent_sessions": sessions[:12],
        "review_priorities": review_priorities[:24],
        "safety_sessions": safety_sessions[:12],
        "disclaimer": "这里展示的是研究评估证据与复核队列，不是临床诊断或自动干预结论。",
    }


def _records() -> list[dict[str, Any]]:
    path = RUNTIME_DATA / "responses.jsonl"
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
    evaluation_path = RUNTIME_DATA / "evaluation.json"
    if evaluation_path.exists():
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    population = build_population_summary(records)
    return {
        "participants": len({r["participant_id"] for r in records}), "responses": total, "score_counts": score_counts,
        "questions": questions_summary, "splits": {split: len({r["participant_id"] for r in records if r["split"] == split}) for split in ("train", "validation", "test")},
        "review_queue": AUDIT.counts(), "assessment_runtime": AUDIT.assessment_metrics(), "evaluation": evaluation,
        "overall_mean_score": population["overall_mean_score"], "risk_counts": population["risk_counts"],
        "risk_rule_version": population["risk_rule_version"], "risk_disclaimer": population["disclaimer"],
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

    path = RUNTIME_DATA / "adjudicated_dataset.jsonl"
    return AUDIT.export_adjudicated_dataset(path)
