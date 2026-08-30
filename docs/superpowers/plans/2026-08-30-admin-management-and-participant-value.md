# 管理员管理与参与者价值 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add auditable multi-admin management and turn the 20-question completion page into a useful, non-diagnostic evidence handoff.

**Architecture:** Extend the existing SQLite audit store with admin invitations and role-management methods. Keep server-side cookie authentication and session ownership as the authority, expose a small admin API, and add a protected member-management view. Reuse the existing global evidence state and session AI summary for participant value output without changing item scores.

**Tech Stack:** FastAPI, SQLite, Pydantic, React/Vite, TypeScript, existing Evidence Map/orchestrator modules.

**Spec:** `docs/superpowers/specs/2026-08-30-admin-management-and-participant-value-design.md`

## Global Constraints

- Do not write plaintext passwords or API keys to source files, logs, or Git.
- Cross-item evidence may plan probes and explain patterns, but must not change rubric-local item scores.
- Safety-gated sessions stop playful automation and do not receive ordinary participant advice.
- Existing legacy `X-Research-Token` access remains compatible for research scripts.
- Run backend tests, `python -m compileall backend/app`, `git diff --check`, and `npm run build` before claiming completion.

### Task 1: Admin data model and service operations

**Files:**
- Modify: `backend/app/audit/store.py`
- Modify: `backend/app/auth/service.py`
- Test: `backend/tests/test_admin_management.py`

- [ ] Write failing tests for promotion, demotion, invitation, activation, and last-admin protection.
- [ ] Run the focused tests and verify the missing-method failure.
- [ ] Add `admin_invites` schema, user role/active updates, invitation lookup/consume, and an admin count query.
- [ ] Add `AuthService` operations that normalize emails, preserve generic errors, and write no plaintext secret.
- [ ] Run focused tests, then the complete backend suite.

### Task 2: Admin API and audit boundary

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/security.py`
- Test: `backend/tests/test_admin_api.py`

- [ ] Write failing route-level tests for participant denial, admin list, promotion, demotion, invite, activation, and audit entries.
- [ ] Implement admin endpoints under `/api/admin/*` using `require_admin_access` and `AUDIT.record_admin_access`.
- [ ] Make registration consume a matching verified admin invitation.
- [ ] Run focused API tests and the complete backend suite.

### Task 3: Participant value handoff

**Files:**
- Modify: `backend/app/assessment/intelligence.py`
- Modify: `backend/app/assessment/service.py`
- Modify: `src/App.tsx`
- Modify: `src/index.css`
- Test: `backend/tests/test_participant_value.py`

- [ ] Write failing tests for a non-diagnostic session value summary and safety-gated handoff.
- [ ] Add a bounded `participant_handoff` object derived from global evidence and advisory AI text.
- [ ] Render “我听见了什么 / 还可以理解什么 / 接下来怎么做” on the completion page.
- [ ] Keep score values and safety behavior unchanged.
- [ ] Run focused tests and `npm run build`.

### Task 4: Members UI and seeded administrators

**Files:**
- Create: `src/components/admin/AdminMembersView.tsx`
- Modify: `src/App.tsx`
- Modify: `src/index.css`
- Create: `scripts/bootstrap_admin.py`
- Modify: `.env.example`

- [ ] Add an admin-only members view with role/active actions, invite form, and clear audit feedback.
- [ ] Add navigation without exposing admin controls to participants.
- [ ] Add a one-time bootstrap CLI that reads credentials from stdin/environment, hashes passwords, verifies emails, and never prints passwords.
- [ ] Seed the two requested admins only in the ignored local runtime database, not in source.
- [ ] Run all verification commands and inspect Git status for secrets.
