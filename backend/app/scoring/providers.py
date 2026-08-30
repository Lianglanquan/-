"""Provider contract for controlled model comparisons.

Every provider must return the same auditable result. This keeps prompt-based,
retrieval-based, fine-tuned and deterministic systems comparable in evaluation.
"""

from __future__ import annotations

from typing import Protocol

from backend.app.scoring.engine import ScoreResult


class ScoringProvider(Protocol):
    name: str
    version: str

    def score(self, question_id: str, response: str) -> ScoreResult:
        ...


class DeterministicBaseline:
    name = "deterministic-keyword-baseline"
    version = "0.1.0"

    def __init__(self, rubrics: dict) -> None:
        self.rubrics = rubrics

    def score(self, question_id: str, response: str) -> ScoreResult:
        from backend.app.scoring.engine import score_response

        return score_response(question_id, response, self.rubrics)
