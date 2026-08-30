# Model Specification

The model interface is `Question + Response + Rubric -> ScoreResult`. A result always contains a preliminary `0/1/2`, `rationale`, quoted `evidence_spans`, `confidence`, `score_status`, `evidence_sufficiency`, and rubric version.

The shipped scorer is deterministic and auditable. It is a research baseline, not a clinical classifier. Future providers must implement the same interface and be evaluated with the same participant-level splits. Gold-test human scores and rationales must never be placed in inference context.

`CONFIRMED` means evidence is currently sufficient for the item rubric; `PROVISIONAL` means the score is a working hypothesis and the system should ask one neutral, gap-targeted clarification. Persistent uncertainty becomes `HUMAN_REVIEW`.
