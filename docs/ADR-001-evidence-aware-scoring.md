# ADR-001: Evidence-aware scoring as the core contract

## Status

Accepted for prototype

## Decision

Keep `preliminary_score` and `evidence_sufficiency` as separate fields. A score can be `0`, `1`, or `2` while its `score_status` is `PROVISIONAL`. The scorer returns rationale, evidence spans, confidence, target semantic gap, and one neutral clarification question.

## Rationale

Historical spreadsheet answers include abstract and context-free responses. Forcing every response into a confirmed label conflates “no observed evidence” with “evidence for zero”. Separating these axes allows selective prediction and an auditable adaptive-probe experiment.

## Consequences

The pipeline can measure coverage-risk tradeoffs and clarification resolution. Human review remains a first-class terminal state. No item score is interpreted as a clinical safety level.
