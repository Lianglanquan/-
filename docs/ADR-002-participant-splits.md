# ADR-002: Participant-level deterministic splits

## Status

Accepted for prototype

## Decision

Hash `participant_id` into fixed train/validation/test buckets. The split is written onto every response record and recorded in the dataset manifest.

## Rationale

Each participant answers all 20 items. Row-level splitting would leak personal language style and response tendencies across evaluation sets and inflate performance.
