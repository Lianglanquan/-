# Data Specification

## Source-backed facts

- `data/raw/系统调试样本.xlsx` is retained unchanged. It contains 205 participants, 20 prompts, 4,100 response rows, historical `0/1/2` scores, and human rationales.
- `data/raw/正式调研题项及评分细则(1).docx` is the source of truth for the 20 item rubrics. `scripts/parse_rubric.py` extracts each table into `rubrics/Q01.json` … `Q20.json`.
- `data/raw/正式调研380人(1).xlsx` is an answer-only real-survey workbook for local testing. `scripts/parse_real_survey.py` reads its Q1--Q20 columns and excludes the entire participant when Q20 parses outside the valid `0--10` range. The observed out-of-range values are `30` (2 participants), `70` (1), and `80` (1), so the generated local test set contains 376 of 380 participants. The source workbook and `data/derived/real_survey/` remain ignored and are never production inputs.

## Canonical response record

`data/derived/responses.jsonl` stores one record per participant and item:

`response_id`, `participant_id`, `question_id`, `source_question_code`, `response`, `legacy_score`, `legacy_rationale`, `evidence_sufficiency`, `adjudicated_score`, `split`, and `provenance`.

`legacy_score` is historical annotation, never an immutable Gold label. `adjudicated_score` is reserved for reviewed cases. `evidence_sufficiency` is an independent axis with `UNASSESSED`, `SUFFICIENT`, `INSUFFICIENT`, and `EXPERT_DISAGREEMENT`.

Runtime participant sessions are stored separately in the generated SQLite audit store at `data/derived/audit.sqlite3`. It contains `sessions`, append-only `events` (`INITIAL` and adaptive probe event types), append-only `session_decisions` (deterministic state plus bounded AI advice), `review_cases`, and `reviews`; it is not a replacement for the raw spreadsheet or the derived response dataset. A session item can expose `original_preliminary_score` and a separate expert `adjudicated_score`; the latter is the effective score used by the Evidence Map only after an adjudication is recorded.

`POST /api/research/adjudications/export` writes the expert-confirmed subset to `data/derived/adjudicated_dataset.jsonl`. This is a research-cycle artifact for dataset curation, rubric review, calibration, and model comparison. Export does not mutate raw inputs or automatically retrain/replace the production scorer.

## Splits and retention

Splits are deterministic SHA-256 buckets of `participant_id` (65% train, 15% validation, 20% test). Every answer by one participant stays in one split. Raw files are never overwritten; generated files belong in `data/derived/` and should not contain additional identifying data.

The real-survey parser replaces each source `作答ID` with a stable opaque hash before writing derived records. Its manifest records only aggregate quality counts and the Q20 filter rule; no raw participant identifier is copied into the derived test set.

Historical review APIs expose an opaque `historical:<hash>` case identifier and omit the internal payload/participant identifier. Session review cases use `session:<session_id>:<question_id>` internally so the full event chain can be replayed locally.
