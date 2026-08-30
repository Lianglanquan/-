# 求证式评估研究工作台

这是半结构化自杀意念语句智能自动评估系统的研究原型。核心流程是：固定 20 道 Seed Probes，生成可审计的 0/1/2 初评，独立判断证据充分性，必要时提出一个最小澄清问题，最后确认或转交专家复核。

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
python3 scripts/build_dataset.py
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
npm install
npm run dev -- --port 4173
```

For local use, copy `.env.example` to the ignored `.env.local`. Set
`ADMIN_EMAILS` to a comma-separated administrator allowlist and configure
Resend (`RESEND_API_KEY`, `AUTH_FROM_EMAIL`) so new accounts can verify their
email. All assessment sessions require a verified email/password login and are
bound to an internal `user_id`; participants can only read their own sessions.
Administrators can use the Research Dashboard and Expert Review workspace from
the same login. The legacy `X-Research-Token` header remains supported for
offline research scripts during migration.

External model calls remain disabled unless `ALLOW_EXTERNAL_SCORING=true`; with
the default `SCORING_PROVIDER=centroid`, participant responses stay local and
use the reproducible character n-gram baseline. If an opt-in provider is
unavailable, scoring falls back to the deterministic baseline and marks the
provider mode explicitly.

Open `http://127.0.0.1:4173`. Vite proxies `/api` to FastAPI. The scorer is a deterministic, auditable research baseline; it is not a clinical diagnosis or autonomous crisis-response system.

## Research commands

```bash
npm run build
.venv/bin/python -m compileall backend/app
.venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/python scripts/evaluate.py --split test
.venv/bin/python scripts/train_centroid.py
```

`scripts/build_dataset.py` reads the unchanged files in `data/raw/`, writes canonical records to `data/derived/`, and uses participant-level deterministic splits. `scripts/train_centroid.py` trains only on the participant-locked train split and writes the model/report artifacts. Runtime sessions and expert decisions are persisted in `data/derived/audit.sqlite3`; `legacy_score` and `legacy_rationale` remain historical annotations, while `adjudicated_score` and `evidence_sufficiency` are separate review fields.

For the anonymous real-survey answer workbook used in local smoke tests, run:

```bash
.venv/bin/python scripts/parse_real_survey.py --xlsx data/raw/正式调研380人\(1\).xlsx --out data/derived/real_survey
```

The real-survey parser keeps the 20 answer texts but does not invent legacy labels. It excludes a whole participant when Q20 parses to a number outside the documented `0--10` range (including the observed `30`, `70`, and `80` entries), hashes source response IDs, and writes a local-only manifest with the included/excluded counts. The raw workbook and derived real-survey responses are ignored by Git and must not be uploaded to production.

To run the non-persistent scorer smoke test over that filtered set:

```bash
.venv/bin/python scripts/smoke_real_survey.py
```

To replay every included participant through the configured runtime scorer and
session orchestrator, and export an auditable CSV for expert review:

```bash
.venv/bin/python scripts/review_real_survey.py \
  --data data/derived/real_survey/responses.jsonl \
  --out data/derived/real_survey/project_review.csv
```

The review CSV contains opaque participant ids, item scores, evidence
sufficiency, model uncertainty, safety state, cross-item support/conflict
signals, the session-level next action, and the selected cat-probe contract.
It is generated locally and remains ignored by Git. Answer-only real-survey
data has no expert gold labels, so `HUMAN_REVIEW` and `PROVISIONAL` are review
queues rather than claims that the system has made a clinically correct
judgement.

It prints aggregate status/safety counts only and never writes to the runtime audit database.

The raw spreadsheet and document are intentionally excluded from version
control because they contain sensitive response material. Place approved source
copies in `data/raw/` on a research workstation before running the dataset
scripts; production only needs the rubric/model artifacts and an empty runtime
database directory.

The runtime loop is session-level: `INITIAL -> rubric-local ScoreResult -> Global Evidence State -> optional bounded AI session advice -> deterministic orchestration -> CONTINUE_SEED / DEFER / CLARIFY / CONFIRM / SAFETY / HUMAN_REVIEW -> expert adjudication -> Evidence Map`. The orchestrator can defer a low-context gap, prioritize a consequential node using cross-item support/conflict, and ask at most three automatic probes per session. AI advice is advisory and auditable: it can synthesize constructs and refine neutral probe wording, but never changes an item's 0/1/2 score or bypasses safety/expert review. Case Replay reads the persisted event chain and decision history; the research endpoints expose aggregate metrics, a paginated review queue, and an explicit adjudicated-dataset export for the next rubric/model evolution cycle.

When a probe is selected now, the participant sees a companion-style `cat_probe`: the cat receives the original words, shares a tentative understanding, admits it may have heard them incorrectly, and offers equal semantic paths plus free-text and pause exits. Option selection, free text, `PROBE_PAUSED`, and re-scoring are all auditable. This is a warmer interaction layer over the same evidence-aware policy, not a second scoring system.

The participant-facing protocol, safety boundary, reserved exits, and copy
validation rules are documented in [`docs/COMPANION_PROBE.md`](docs/COMPANION_PROBE.md).

The interface uses 汇文明朝体 as its unified display and reading face. The
webfont and its CC0 notice are kept under `public/fonts/` so production does
not depend on a user's installed fonts.

See `docs/ADR-001-evidence-aware-scoring.md`, `docs/ADR-002-participant-splits.md`, and the other `docs/` files for research and safety decisions.
