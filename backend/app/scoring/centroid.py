"""Pure-Python per-item character n-gram centroid baseline.

The model is trained only on the participant-locked training split. It is a
reproducible research baseline for agreement with legacy annotations, not a
clinical model and not a replacement for adjudicated expert labels.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from backend.app.scoring.engine import Evidence, ScoreResult, evidence_gap


DEFAULT_NGRAM_SIZES = (1, 2, 3)


def char_ngrams(text: str, sizes: Iterable[int] = DEFAULT_NGRAM_SIZES) -> set[str]:
    value = re.sub(r"\s+", "", text)
    return {value[index : index + size] for size in sizes for index in range(max(0, len(value) - size + 1))}


def train_centroid_model(records: list[dict[str, Any]], sizes: tuple[int, ...] = DEFAULT_NGRAM_SIZES) -> dict[str, Any]:
    questions: dict[str, Any] = {}
    for question_id in sorted({record["question_id"] for record in records}):
        subset = [record for record in records if record["question_id"] == question_id and record.get("legacy_score") in (0, 1, 2)]
        documents: list[tuple[int, set[str]]] = []
        document_frequency: Counter[str] = Counter()
        for record in subset:
            grams = char_ngrams(str(record.get("response", "")), sizes)
            documents.append((int(record["legacy_score"]), grams))
            document_frequency.update(grams)
        total_documents = len(documents)
        centroids: dict[str, Counter[str]] = {str(score): Counter() for score in (0, 1, 2)}
        class_counts: Counter[int] = Counter()
        for score, grams in documents:
            class_counts[score] += 1
            for gram in grams:
                centroids[str(score)][gram] += math.log((total_documents + 1) / (document_frequency[gram] + 1)) + 1
        serialized_centroids: dict[str, dict[str, float]] = {}
        norms: dict[str, float] = {}
        for score in (0, 1, 2):
            key = str(score)
            denominator = class_counts[score] or 1
            values = {gram: round(weight / denominator, 8) for gram, weight in centroids[key].items()}
            serialized_centroids[key] = values
            norms[key] = math.sqrt(sum(weight * weight for weight in values.values())) or 1.0
        questions[question_id] = {
            "documents": total_documents,
            "class_counts": {str(score): class_counts[score] for score in (0, 1, 2)},
            "document_frequency": dict(document_frequency),
            "centroids": serialized_centroids,
            "norms": norms,
        }
    return {
        "model_type": "per-item-char-ngram-tfidf-centroid",
        "version": "1.0.0",
        "ngram_sizes": list(sizes),
        "temperature": 0.2,
        "uncertainty_margin": 0.035,
        "questions": questions,
    }


def similarity_scores(model: dict[str, Any], question_id: str, response: str) -> dict[int, float]:
    item = model["questions"].get(question_id)
    if not item:
        return {0: 0.0, 1: 0.0, 2: 0.0}
    grams = char_ngrams(response, tuple(model.get("ngram_sizes", DEFAULT_NGRAM_SIZES)))
    total_documents = int(item["documents"])
    document_frequency = item["document_frequency"]
    vector = {
        gram: math.log((total_documents + 1) / (int(document_frequency.get(gram, 0)) + 1)) + 1
        for gram in grams
    }
    vector_norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0
    result: dict[int, float] = {}
    for score in (0, 1, 2):
        key = str(score)
        centroid = item["centroids"][key]
        dot = sum(weight * float(centroid.get(gram, 0.0)) for gram, weight in vector.items())
        result[score] = dot / (vector_norm * float(item["norms"][key]))
    return result


def calibrated_probabilities(scores: dict[int, float], temperature: float) -> dict[int, float]:
    safe_temperature = max(0.01, temperature)
    peak = max(scores.values())
    exponentials = {score: math.exp((value - peak) / safe_temperature) for score, value in scores.items()}
    total = sum(exponentials.values()) or 1.0
    return {score: value / total for score, value in exponentials.items()}


class CentroidScorer:
    name = "per-item-char-ngram-centroid"

    def __init__(self, rubrics: dict[str, dict[str, Any]], model_path: Path) -> None:
        self.rubrics = rubrics
        self.model_path = model_path
        self.model_data = json.loads(model_path.read_text(encoding="utf-8"))
        self.model_name = self.model_data.get("model_type", self.name)

    @property
    def version(self) -> str:
        return str(self.model_data.get("version", "unknown"))

    def score(self, question_id: str, response: str) -> ScoreResult:
        scores = similarity_scores(self.model_data, question_id, response)
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        preliminary_score = ordered[0][0]
        margin = ordered[0][1] - ordered[1][1]
        probabilities = calibrated_probabilities(scores, float(self.model_data.get("temperature", 0.2)))
        gap = evidence_gap(question_id, response, self.rubrics.get(question_id, {}))
        uncertain = margin < float(self.model_data.get("uncertainty_margin", 0.035))
        reasons: list[str] = []
        if gap:
            reasons.append(gap[0])
        if uncertain:
            reasons.append("MODEL_UNCERTAINTY")
        sufficiency = "INSUFFICIENT" if gap else "SUFFICIENT"
        review_recommended = uncertain and not gap
        # A semantic gap is actionable by one neutral adaptive probe. Model
        # uncertainty without a gap is not: asking the participant again would
        # not add a targeted piece of evidence, so it goes straight to review.
        if gap:
            status = "PROVISIONAL"
        elif uncertain:
            status = "HUMAN_REVIEW"
        else:
            status = "CONFIRMED"
        spans = _rubric_evidence(response, self.rubrics.get(question_id, {}), preliminary_score)
        rationale = (
            f"字符 n-gram 研究基线在 {question_id} 的训练样本中倾向 {preliminary_score} 分；"
            f"类别相似度边际为 {margin:.3f}。该结果表示与历史标签的模型匹配，不是临床判断。"
        )
        if gap:
            rationale += f" 当前回答缺少可确认评分的语义信息：{gap[1]}。"
        elif uncertain:
            rationale += " 当前语言证据存在，但模型无法稳定区分相邻评分边界，应直接进入专家复核。"
        return ScoreResult(
            question_id=question_id,
            response=response,
            preliminary_score=preliminary_score,
            score_status=status,
            evidence_sufficiency=sufficiency,
            rationale=rationale,
            evidence_spans=spans,
            confidence=round(probabilities[preliminary_score], 3),
            target_gap=gap[1] if gap else None,
            clarification_question=gap[2] if gap else None,
            rubric_version=str(self.rubrics.get(question_id, {}).get("version", "unknown")),
            decision_reasons=reasons,
            review_recommended=review_recommended,
            model_margin=round(margin, 4),
        )


def _rubric_evidence(response: str, rubric: dict[str, Any], score: int) -> list[Evidence]:
    spans: list[Evidence] = []
    criterion = next((item for item in rubric.get("criteria", []) if item.get("score") == score), None)
    if criterion:
        for example in criterion.get("examples", []):
            cleaned = str(example).strip("。！？!?，,；; ")
            if len(cleaned) < 2:
                continue
            start = response.find(cleaned)
            if start >= 0:
                spans.append(Evidence(text=cleaned, start=start, end=start + len(cleaned), rule=criterion.get("description", "")))
                if len(spans) >= 3:
                    break
    if not spans and response.strip():
        text = response.strip()
        start = response.find(text)
        spans.append(
            Evidence(
                text=text,
                start=start,
                end=start + len(text),
                rule="整体回答用于字符 n-gram 基线匹配；尚不构成独立的心理学证据解释。",
            )
        )
    return spans
