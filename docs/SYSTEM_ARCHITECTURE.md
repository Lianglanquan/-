# System Architecture

The Vite/React frontend calls a FastAPI service. `backend/app/scoring` owns deterministic/rubric-local item scoring and evidence spans; `backend/app/safety` is an isolated safety gate; `backend/app/assessment/orchestrator.py` maintains the session-level Evidence Map and hard action policy; `backend/app/assessment/intelligence.py` gives an opt-in provider-backed AI a bounded role in session synthesis, cross-item hypotheses, and probe wording; `backend/app/audit/store.py` persists sessions, events, append-only orchestrator decisions, review cases, and adjudications in the generated SQLite database; `backend/app/api` exposes questions, scoring, assessment sessions, research summary, review queue, and adjudicated-dataset export endpoints.

The derived JSONL dataset is read-only input to the research endpoints. Runtime assessment traces are append-only events in `data/derived/audit.sqlite3`, while raw spreadsheets and documents remain untouched. Provider-backed LLMs are behind the scoring contract and are disabled unless `ALLOW_EXTERNAL_SCORING=true`; they are never called directly from the browser. Research endpoints require `X-Research-Token` and never expose the internal payload or participant identifier for historical cases.

The supported runtime path is:

`INITIAL response -> item-local ScoreResult -> Global Evidence State -> bounded AI session advice -> deterministic action guardrail -> CONTINUE_SEED / DEFER / CLARIFY / CONFIRM / SAFETY / HUMAN_REVIEW -> expert adjudication -> effective Evidence Map -> adjudicated_dataset.jsonl -> next rubric/model research cycle`.

Model uncertainty without an actionable semantic gap can receive one bounded confirmation probe; unresolved uncertainty then goes to `HUMAN_REVIEW`. The session has a maximum of three automatic probes to control participant burden. AI advice is stored alongside the deterministic decision trace, but cannot change a 0/1/2 score, invent evidence, override safety, or bypass expert review. Safety states independently stop adaptive clarification and enter the professional review queue.

## Companion probe interaction

When the final action is `CLARIFY_NOW` or `CONFIRM_NOW`, the participant-facing contract includes a `cat_probe`: a short reflection of the original words, a tentative understanding, an explicit humility sentence, a gentle invitation, and neutral options. The options are semantic directions rather than score labels; `other` and `not_ready` exits are mandatory. The participant may choose an option, add free text, or pause. A pause is recorded as `PROBE_PAUSED` and does not become evidence or trigger another automatic probe for that node. Safety-gated items never receive companion wording.

The full interaction contract and copy guardrails live in `docs/COMPANION_PROBE.md`. In particular, an existing session never silently falls back to the stateless scorer after a probe error: preserving the audit chain takes precedence over hiding a failed request.
