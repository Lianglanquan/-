"""Append-only local audit store for assessment sessions and expert review.

SQLite is sufficient for the research prototype and keeps the complete event
chain reproducible without adding a service dependency. Raw source files stay
untouched; this database is generated under ``data/derived``.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    question_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    response TEXT NOT NULL,
                    clarification_round INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, created_at);
                CREATE TABLE IF NOT EXISTS session_decisions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    event_id TEXT,
                    deterministic_json TEXT NOT NULL,
                    ai_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_decisions_session ON session_decisions(session_id, created_at);
                CREATE TABLE IF NOT EXISTS review_cases (
                    response_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    participant_id TEXT,
                    session_id TEXT,
                    event_id TEXT,
                    question_id TEXT NOT NULL,
                    response TEXT NOT NULL,
                    legacy_score INTEGER,
                    legacy_rationale TEXT,
                    preliminary_score INTEGER,
                    adjudicated_score INTEGER,
                    score_status TEXT,
                    evidence_sufficiency TEXT NOT NULL,
                    safety_state TEXT NOT NULL DEFAULT 'CLEAR',
                    reason_codes_json TEXT NOT NULL DEFAULT '[]',
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_status ON review_cases(status, updated_at);
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    response_id TEXT NOT NULL REFERENCES review_cases(response_id),
                    adjudicated_score INTEGER,
                    evidence_sufficiency TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    reviewer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_case ON reviews(response_id, created_at);
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(review_cases)").fetchall()}
            if "adjudicated_score" not in columns:
                connection.execute("ALTER TABLE review_cases ADD COLUMN adjudicated_score INTEGER")

    def create_session(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions(id, created_at, updated_at, status) VALUES (?, ?, ?, ?)",
                (session_id, now, now, "IN_PROGRESS"),
            )
        return {"id": session_id, "created_at": now, "updated_at": now, "status": "IN_PROGRESS", "items": []}

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row is not None

    def set_session_status(self, session_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), session_id))

    def set_session_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Persist the latest session-level snapshot without touching events."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET metadata_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(metadata, ensure_ascii=False), utc_now(), session_id),
            )

    def append_session_decision(
        self,
        *,
        session_id: str,
        event_id: str | None,
        deterministic_state: dict[str, Any],
        ai_analysis: dict[str, Any],
    ) -> str:
        """Keep an append-only replay trace for each orchestrator decision."""

        decision_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO session_decisions
                   (id, session_id, event_id, deterministic_json, ai_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    session_id,
                    event_id,
                    json.dumps(deterministic_state, ensure_ascii=False),
                    json.dumps(ai_analysis, ensure_ascii=False),
                    utc_now(),
                ),
            )
        return decision_id

    def append_event(
        self,
        *,
        session_id: str,
        question_id: str,
        event_type: str,
        response: str,
        clarification_round: int,
        payload: dict[str, Any],
    ) -> str:
        event_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO events
                   (id, session_id, question_id, event_type, response, clarification_round, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, session_id, question_id, event_type, response, clarification_round, json.dumps(payload, ensure_ascii=False), now),
            )
            connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return event_id

    def upsert_review_case(self, case: dict[str, Any]) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO review_cases
                   (response_id, source, participant_id, session_id, event_id, question_id, response,
                    legacy_score, legacy_rationale, preliminary_score, adjudicated_score, score_status, evidence_sufficiency,
                    safety_state, reason_codes_json, payload_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(response_id) DO UPDATE SET
                    event_id=excluded.event_id,
                    response=excluded.response,
                    preliminary_score=excluded.preliminary_score,
                    adjudicated_score=CASE WHEN review_cases.status IN ('ADJUDICATED', 'UNRESOLVED') THEN review_cases.adjudicated_score ELSE excluded.adjudicated_score END,
                    score_status=excluded.score_status,
                    evidence_sufficiency=CASE WHEN review_cases.status IN ('ADJUDICATED', 'UNRESOLVED') THEN review_cases.evidence_sufficiency ELSE excluded.evidence_sufficiency END,
                    safety_state=excluded.safety_state,
                    reason_codes_json=excluded.reason_codes_json,
                    payload_json=excluded.payload_json,
                    status=review_cases.status,
                    updated_at=excluded.updated_at""",
                (
                    case["response_id"], case.get("source", "session"), case.get("participant_id"), case.get("session_id"),
                    case.get("event_id"), case["question_id"], case.get("response", ""), case.get("legacy_score"),
                    case.get("legacy_rationale", ""), case.get("preliminary_score"), case.get("adjudicated_score"), case.get("score_status"),
                    case.get("evidence_sufficiency", "UNASSESSED"), case.get("safety_state", "CLEAR"),
                    json.dumps(case.get("reason_codes", []), ensure_ascii=False), json.dumps(case, ensure_ascii=False),
                    case.get("status", "OPEN"), case.get("created_at", now), now,
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            session = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                return None
            events = connection.execute("SELECT * FROM events WHERE session_id = ? ORDER BY created_at, rowid", (session_id,)).fetchall()
            decisions = connection.execute("SELECT * FROM session_decisions WHERE session_id = ? ORDER BY created_at, rowid", (session_id,)).fetchall()
        items = []
        for event in events:
            payload = json.loads(event["payload_json"])
            items.append({
                "event_id": event["id"],
                "question_id": event["question_id"],
                "response": event["response"],
                "clarification": event["event_type"] != "INITIAL",
                "clarification_round": event["clarification_round"],
                "score": payload.get("score"),
                "safety": payload.get("safety"),
                "probe_type": payload.get("probe_type") or (event["event_type"] if event["event_type"] != "INITIAL" else None),
                "probe_option_id": payload.get("probe_option_id"),
                "probe_action": payload.get("probe_action", "ANSWER"),
                "probe_interaction": payload.get("probe_interaction"),
                "event_type": event["event_type"],
                "created_at": event["created_at"],
            })
        try:
            metadata = json.loads(session["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        decision_history = []
        for decision in decisions:
            try:
                deterministic = json.loads(decision["deterministic_json"])
            except json.JSONDecodeError:
                deterministic = {}
            try:
                ai_analysis = json.loads(decision["ai_json"])
            except json.JSONDecodeError:
                ai_analysis = {}
            decision_history.append({
                "id": decision["id"],
                "event_id": decision["event_id"],
                "deterministic_state": deterministic,
                "ai_analysis": ai_analysis,
                "created_at": decision["created_at"],
            })
        return {
            "id": session["id"], "created_at": session["created_at"], "updated_at": session["updated_at"],
            "status": session["status"], "metadata": metadata, "items": items, "decision_history": decision_history,
        }

    def list_review_cases(
        self,
        *,
        limit: int = 40,
        offset: int = 0,
        source: str | None = None,
        statuses: Iterable[str] = ("OPEN", "UNRESOLVED"),
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        conditions = [f"status IN ({placeholders})"]
        values: list[Any] = list(statuses)
        if source:
            conditions.append("source = ?")
            values.append(source)
        values.extend((max(1, min(limit, 200)), max(0, offset)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM review_cases WHERE {' AND '.join(conditions)} ORDER BY CASE source WHEN 'session' THEN 0 ELSE 1 END, updated_at DESC LIMIT ? OFFSET ?", values
            ).fetchall()
        output = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            output.append({
                "response_id": row["response_id"],
                "question_id": row["question_id"],
                "response": row["response"],
                "legacy_score": row["legacy_score"],
                "legacy_rationale": row["legacy_rationale"],
                "preliminary_score": row["preliminary_score"],
                "adjudicated_score": row["adjudicated_score"],
                "score_status": row["score_status"],
                "evidence_sufficiency": row["evidence_sufficiency"],
                "safety_state": row["safety_state"],
                "reason_codes": json.loads(row["reason_codes_json"]),
                "status": row["status"],
                "source": row["source"],
            })
        return output

    def get_review_case(self, response_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM review_cases WHERE response_id = ?", (response_id,)).fetchone()
            reviews = connection.execute("SELECT * FROM reviews WHERE response_id = ? ORDER BY created_at", (response_id,)).fetchall()
        if row is None:
            return None
        case = {
            "response_id": row["response_id"], "question_id": row["question_id"], "response": row["response"],
            "participant_id": row["participant_id"], "session_id": row["session_id"], "event_id": row["event_id"],
            "legacy_score": row["legacy_score"], "legacy_rationale": row["legacy_rationale"],
            "preliminary_score": row["preliminary_score"], "score_status": row["score_status"],
            "adjudicated_score": row["adjudicated_score"],
            "evidence_sufficiency": row["evidence_sufficiency"], "safety_state": row["safety_state"],
            "reason_codes": json.loads(row["reason_codes_json"]), "status": row["status"], "source": row["source"],
            "reviews": [dict(review) for review in reviews],
        }
        return case

    def record_review(self, response_id: str, *, adjudicated_score: int | None, evidence_sufficiency: str, note: str, reviewer: str) -> dict[str, Any]:
        existing = self.get_review_case(response_id)
        if not existing:
            raise KeyError(response_id)
        review_id = uuid.uuid4().hex
        now = utc_now()
        status = "ADJUDICATED" if evidence_sufficiency == "SUFFICIENT" and adjudicated_score in (0, 1, 2) else "UNRESOLVED"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO reviews(id, response_id, adjudicated_score, evidence_sufficiency, note, reviewer, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (review_id, response_id, adjudicated_score, evidence_sufficiency, note, reviewer, now),
            )
            connection.execute(
                "UPDATE review_cases SET status = ?, evidence_sufficiency = ?, adjudicated_score = ?, updated_at = ? WHERE response_id = ?",
                (status, evidence_sufficiency, adjudicated_score, now, response_id),
            )
        if existing.get("session_id"):
            # The session remains append-only; its next GET will fold this
            # adjudication into the effective Evidence Map while preserving
            # the original preliminary score and event trace.
            self.set_session_status(existing["session_id"], "AWAITING_REVIEW" if status == "UNRESOLVED" else "IN_PROGRESS")
        return {"review_id": review_id, "response_id": response_id, "adjudicated_score": adjudicated_score, "evidence_sufficiency": evidence_sufficiency, "note": note, "reviewer": reviewer, "status": status, "created_at": now}

    def session_adjudications(self, session_id: str) -> dict[str, dict[str, Any]]:
        """Return the latest expert decision for each session item."""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT question_id, event_id, preliminary_score, adjudicated_score,
                          score_status, evidence_sufficiency, safety_state, status, updated_at
                   FROM review_cases WHERE session_id = ? ORDER BY updated_at, rowid""",
                (session_id,),
            ).fetchall()
        return {
            str(row["question_id"]): {
                "question_id": row["question_id"],
                "event_id": row["event_id"],
                "preliminary_score": row["preliminary_score"],
                "adjudicated_score": row["adjudicated_score"],
                "score_status": row["score_status"],
                "evidence_sufficiency": row["evidence_sufficiency"],
                "safety_state": row["safety_state"],
                "status": row["status"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def export_adjudicated_dataset(self, path: Path) -> dict[str, Any]:
        """Write only expert-adjudicated session cases as a derived artifact."""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT response_id, source, participant_id, session_id, event_id,
                          question_id, response, preliminary_score, adjudicated_score,
                          score_status, evidence_sufficiency, safety_state, payload_json,
                          updated_at
                   FROM review_cases WHERE status = 'ADJUDICATED'
                   ORDER BY updated_at, rowid"""
            ).fetchall()
        records = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            records.append({
                "response_id": row["response_id"],
                "source": row["source"],
                "participant_id": row["participant_id"],
                "session_id": row["session_id"],
                "event_id": row["event_id"],
                "question_id": row["question_id"],
                "response": row["response"],
                "preliminary_score": row["preliminary_score"],
                "adjudicated_score": row["adjudicated_score"],
                "score_status": row["score_status"],
                "evidence_sufficiency": row["evidence_sufficiency"],
                "safety_state": row["safety_state"],
                "rubric_version": ((payload.get("score") or {}).get("rubric_version")),
                "updated_at": row["updated_at"],
            })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
        by_rubric_version: dict[str, int] = {}
        for record in records:
            version = str(record.get("rubric_version") or "unknown")
            by_rubric_version[version] = by_rubric_version.get(version, 0) + 1
        return {"path": str(path), "records": len(records), "by_rubric_version": by_rubric_version}

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS n FROM review_cases GROUP BY status").fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def assessment_metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            sessions = connection.execute("SELECT COUNT(*) AS n, SUM(status = 'COMPLETED') AS completed FROM sessions").fetchone()
            events = connection.execute("SELECT event_type, payload_json FROM events").fetchall()
        clarifications = 0
        resolved = 0
        safety_reviews = 0
        human_reviews = 0
        for event in events:
            payload = json.loads(event["payload_json"])
            score = payload.get("score") or {}
            if event["event_type"] != "INITIAL":
                clarifications += 1
                if score.get("score_status") == "CONFIRMED":
                    resolved += 1
            if score.get("safety_state") != "CLEAR":
                safety_reviews += 1
            if score.get("score_status") == "HUMAN_REVIEW":
                human_reviews += 1
        return {
            "sessions": int(sessions["n"] or 0),
            "completed_sessions": int(sessions["completed"] or 0),
            "clarifications": clarifications,
            "clarification_resolved": resolved,
            "clarification_resolution_rate": round(resolved / clarifications, 4) if clarifications else None,
            "safety_reviews": safety_reviews,
            "human_review_events": human_reviews,
        }
