# Remove Q16 and Introduce the Two-Dimension Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a versioned 19-item assessment catalog after removing the former Q16 “牵挂” item, while preserving interpretation of legacy 20-item sessions.

**Architecture:** Active rubrics become catalog `2.0.0` with Q01–Q19 and two display dimensions. Legacy rubrics remain under `rubrics/legacy-v1`; each new session stores its catalog version and seed count. Runtime/reporting resolves the catalog from the session, so old Q16/Q20 data is never reinterpreted by the new numbering.

**Tech Stack:** Python 3.12, FastAPI, SQLite audit store, Pydantic, React/Vite/TypeScript.

**Spec:** User-approved change: delete Q16, shift former Q17–Q20 to Q16–Q19, expose only “情绪状态与人际联结” and “自我认知与绝望感”, retain fine-grained constructs internally.

## Global Constraints

- New sessions contain 19 seed probes; legacy sessions remain 20-item.
- Cross-item planning never changes item-local 0/1/2 scores.
- Active public API accepts Q01–Q19 only; legacy sessions remain readable by administrators.
- Do not modify raw source survey files or commit personally identifiable response data.
- Frontend changes are limited to catalog labels, counts, and version-aware copy.

### Task 1: Version the rubric catalog

**Files:**
- Create: `rubrics/catalog.json`
- Create: `rubrics/legacy-v1/Q01.json` … `Q20.json`
- Modify: `rubrics/Q01.json` … `Q19.json`
- Delete: `rubrics/Q20.json`
- Test: `backend/tests/test_catalog_versioning.py`

- [ ] Copy the current 20 rubrics into `rubrics/legacy-v1` unchanged.
- [ ] Rewrite active Q01–Q15 with the same question/criteria and the public dimension group `情绪状态与人际联结` for Q01–Q07 or `自我认知与绝望感` for Q08–Q15; preserve the prior fine construct in a `construct` field.
- [ ] Promote legacy Q17→active Q16, Q18→Q17, Q19→Q18, Q20→Q19; update `id`, `source_id`, version `2.0.0`, and public dimension while retaining `construct`.
- [ ] Add catalog metadata with active version `2.0.0`, active ids Q01–Q19, and legacy version `1.0.0` with Q01–Q20.
- [ ] Test active ids/count, new Q16 text, absence of active Q20, and legacy Q16/Q20 preservation.

### Task 2: Make backend runtime catalog-aware

**Files:**
- Modify: `backend/app/scoring/engine.py`
- Modify: `backend/app/assessment/orchestrator.py`
- Modify: `backend/app/assessment/service.py`
- Modify: `backend/app/audit/store.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_catalog_versioning.py`, `backend/tests/test_pipeline.py`, `backend/tests/test_admin_api.py`

- [ ] Add active/legacy rubric loaders and catalog metadata helpers.
- [ ] Persist catalog version and seed total in new sessions; resolve legacy rubrics for sessions without active metadata.
- [ ] Make orchestrator seed totals dynamic while retaining a 20-item default for legacy/unit callers.
- [ ] Change request validation and `/questions` to Q01–Q19; use session-specific rubrics for reports/review endpoints.
- [ ] Update readiness to report 19 active rubrics and catalog version `2.0.0`.
- [ ] Add tests proving new sessions/report matrices have 19 items and legacy sessions still expose 20 items including old Q16/Q20.

### Task 3: Align participant/admin surfaces

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/components/participant/ParticipantFlow.tsx`
- Modify: `src/components/admin/AdminOverviewView.tsx`
- Modify: `src/components/admin/AdminSessionsView.tsx`
- Modify: `backend/app/assessment/probes.py`
- Modify: `backend/app/assessment/intelligence.py`
- Modify: `backend/app/scoring/llm.py`

- [ ] Remove the former Q16 “牵挂” from active fallback questions and shift Q17–Q20 labels to Q16–Q19.
- [ ] Replace hard-coded `/20`, “20题”, and 20-item defaults in active participant/admin copy with catalog-aware values.
- [ ] Shift active probe/gap/confirmation packs to the new ids; keep legacy stored event text untouched.
- [ ] Keep two public dimension labels while preserving internal construct names in evidence/report fields.

### Task 4: Verify, commit, push, and deploy

**Files:**
- Modify: affected files above only.

- [ ] Run backend tests, Python compile, and frontend build.
- [ ] Run focused active/legacy catalog tests and verify `/questions`, `/ready`, and a new session locally.
- [ ] Commit the catalog migration and push `main`.
- [ ] Deploy the release to the configured production host and verify public health/readiness.

