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
                    user_id TEXT REFERENCES users(id),
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
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    email_hash TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'PARTICIPANT',
                    email_verified_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash);
                CREATE TABLE IF NOT EXISTS auth_challenges (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id),
                    email_hash TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_challenges_lookup ON auth_challenges(email_hash, purpose, created_at);
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_token ON auth_sessions(token_hash);
                CREATE TABLE IF NOT EXISTS admin_invites (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    email_hash TEXT NOT NULL,
                    invited_by TEXT NOT NULL REFERENCES users(id),
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_admin_invites_lookup ON admin_invites(email_hash, consumed_at, expires_at);
                CREATE TABLE IF NOT EXISTS admin_access_logs (
                    id TEXT PRIMARY KEY,
                    admin_user_id TEXT NOT NULL REFERENCES users(id),
                    target_user_id TEXT,
                    session_id TEXT,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_admin_access_logs_admin ON admin_access_logs(admin_user_id, created_at);
                """
            )
            session_columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)").fetchall()}
            if "user_id" not in session_columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT REFERENCES users(id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at)")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(review_cases)").fetchall()}
            if "adjudicated_score" not in columns:
                connection.execute("ALTER TABLE review_cases ADD COLUMN adjudicated_score INTEGER")

    def create_session(
        self,
        user_id: str | None = None,
        *,
        catalog_version: str = "2.0.0",
        seed_total: int = 19,
    ) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = utc_now()
        metadata = {"catalog_version": catalog_version, "seed_total": int(seed_total)}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions(id, user_id, created_at, updated_at, status, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, user_id, now, now, "IN_PROGRESS", json.dumps(metadata, ensure_ascii=False)),
            )
        return {"id": session_id, "user_id": user_id, "created_at": now, "updated_at": now, "status": "IN_PROGRESS", "metadata": metadata, "items": []}

    def session_belongs_to_user(self, session_id: str, user_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
        return row is not None

    def session_user_id(self, session_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row["user_id"] if row else None

    def list_users(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, email, role, email_verified_at, is_active, created_at, updated_at, last_login_at,
                          (SELECT COUNT(*) FROM sessions s WHERE s.user_id = users.id) AS session_count
                   FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (max(1, min(limit, 200)), max(0, offset)),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "email": row["email"],
                "role": row["role"],
                "email_verified": bool(row["email_verified_at"]),
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "last_login_at": row["last_login_at"],
                "session_count": int(row["session_count"] or 0),
            }
            for row in rows
        ]

    def create_user(self, *, email: str, email_hash: str, password_hash: str, role: str) -> dict[str, Any]:
        user_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO users(id, email, email_hash, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, email, email_hash, password_hash, role, now, now),
            )
        return {"id": user_id, "email": email, "role": role, "email_verified": False, "is_active": True, "created_at": now}

    def find_user_by_email_hash(self, email_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE email_hash = ?", (email_hash,)).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def mark_user_verified(self, user_id: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("UPDATE users SET email_verified_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))

    def mark_user_login(self, user_id: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))

    def update_user_role(self, user_id: str, role: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, now, user_id))
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def update_user_active(self, user_id: str, is_active: bool) -> dict[str, Any] | None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?", (1 if is_active else 0, now, user_id))
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def count_admins(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'ADMIN' AND is_active = 1").fetchone()
        return int(row["n"] or 0)

    def update_user_password(self, user_id: str, password_hash: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (password_hash, now, user_id))

    def create_auth_challenge(self, *, user_id: str, email_hash: str, purpose: str, code_hash: str, expires_at: str) -> str:
        challenge_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_challenges(id, user_id, email_hash, purpose, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (challenge_id, user_id, email_hash, purpose, code_hash, expires_at, utc_now()),
            )
        return challenge_id

    def create_admin_invite(self, *, email: str, email_hash: str, invited_by: str, expires_at: str) -> str:
        invite_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO admin_invites(id, email, email_hash, invited_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (invite_id, email, email_hash, invited_by, expires_at, utc_now()),
            )
        return invite_id

    def consume_admin_invite(self, *, email_hash: str, now: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM admin_invites WHERE email_hash = ? AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (email_hash,),
            ).fetchone()
            if row is None or row["expires_at"] <= now:
                return None
            connection.execute("UPDATE admin_invites SET consumed_at = ? WHERE id = ?", (now, row["id"]))
            return dict(row)

    def invitation_consumed(self, email: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM admin_invites WHERE email = ? AND consumed_at IS NOT NULL LIMIT 1", (email.lower().strip(),)).fetchone()
        return row is not None

    def consume_auth_challenge(self, *, email_hash: str, purpose: str, code_hash: str, now: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_challenges WHERE email_hash = ? AND purpose = ? AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (email_hash, purpose),
            ).fetchone()
            if row is None or row["expires_at"] <= now or row["attempts"] >= 5:
                return None
            if row["code_hash"] != code_hash:
                connection.execute("UPDATE auth_challenges SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
                return None
            connection.execute("UPDATE auth_challenges SET consumed_at = ? WHERE id = ?", (now, row["id"]))
            return dict(row)

    def create_auth_session(self, *, user_id: str, token_hash: str, expires_at: str) -> str:
        session_id = uuid.uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_sessions(id, user_id, token_hash, expires_at, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, user_id, token_hash, expires_at, now, now),
            )
        return session_id

    def get_auth_session_user(self, *, token_hash: str, now: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT u.* FROM auth_sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ? AND u.is_active = 1""",
                (token_hash, now),
            ).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?", (now, token_hash))
        return dict(row)

    def revoke_auth_session(self, token_hash: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ?", (utc_now(), token_hash))

    def revoke_user_auth_sessions(self, user_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (utc_now(), user_id))

    def list_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, user_id, created_at, updated_at, status, metadata_json FROM sessions WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        output = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            output.append({"id": row["id"], "user_id": row["user_id"], "created_at": row["created_at"], "updated_at": row["updated_at"], "status": row["status"], "metadata": metadata})
        return output

    def list_all_sessions(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT s.id, s.user_id, s.created_at, s.updated_at, s.status, s.metadata_json, u.email, u.role
                   FROM sessions s LEFT JOIN users u ON u.id = s.user_id
                   ORDER BY s.updated_at DESC LIMIT ? OFFSET ?""",
                (max(1, min(limit, 200)), max(0, offset)),
            ).fetchall()
        output = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            output.append({"id": row["id"], "user_id": row["user_id"], "email": row["email"], "role": row["role"], "created_at": row["created_at"], "updated_at": row["updated_at"], "status": row["status"], "metadata": metadata})
        return output

    def record_admin_access(self, *, admin_user_id: str, target_user_id: str | None, session_id: str | None, action: str, resource: str) -> str:
        access_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO admin_access_logs(id, admin_user_id, target_user_id, session_id, action, resource, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (access_id, admin_user_id, target_user_id, session_id, action, resource, utc_now()),
            )
        return access_id

    def list_admin_access_logs(self, admin_user_id: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM admin_access_logs"
        values: list[Any] = []
        if admin_user_id:
            query += " WHERE admin_user_id = ?"
            values.append(admin_user_id)
        query += " ORDER BY created_at, rowid LIMIT ?"
        values.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

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
            "id": session["id"], "user_id": session["user_id"], "created_at": session["created_at"], "updated_at": session["updated_at"],
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

    def ensure_session_review_case(self, session_id: str, question_id: str) -> dict[str, Any] | None:
        """Materialize a session node as an expert case when an admin opens it.

        Session events remain append-only.  This helper only creates the
        review-queue projection needed to give an unresolved report node a
        stable adjudication target.  Existing adjudications are preserved by
        ``upsert_review_case``.
        """

        session = self.get_session(session_id)
        if not session:
            return None
        latest = next((item for item in reversed(session.get("items", [])) if item.get("question_id") == question_id), None)
        if not latest:
            return None
        score = latest.get("score") or {}
        payload = {
            "score": score,
            "safety": latest.get("safety") or {"state": "CLEAR"},
            "probe_type": latest.get("probe_type"),
            "source_response": latest.get("response", ""),
        }
        self.upsert_review_case({
            "response_id": f"session:{session_id}:{question_id}",
            "source": "session",
            "participant_id": session.get("user_id"),
            "session_id": session_id,
            "event_id": latest.get("event_id"),
            "question_id": question_id,
            "response": latest.get("response", ""),
            "preliminary_score": score.get("preliminary_score"),
            "score_status": score.get("score_status"),
            "evidence_sufficiency": score.get("evidence_sufficiency", "UNASSESSED"),
            "safety_state": (latest.get("safety") or {}).get("state", "CLEAR"),
            "reason_codes": score.get("decision_reasons", []),
            "payload": payload,
        })
        return self.get_review_case(f"session:{session_id}:{question_id}")

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
