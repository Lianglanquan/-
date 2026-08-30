"""Train and evaluate the pure-Python participant-locked centroid baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.scoring.centroid import calibrated_probabilities, similarity_scores, train_centroid_model


def metrics(records: list[dict], predictions: list[tuple[int, float, float]]) -> dict:
    pairs = [(record["legacy_score"], prediction[0]) for record, prediction in zip(records, predictions)]
    accuracy = sum(actual == predicted for actual, predicted in pairs) / len(pairs) if pairs else 0
    per_class = {}
    f1s = []
    recalls = []
    for label in (0, 1, 2):
        tp = sum(actual == label and predicted == label for actual, predicted in pairs)
        fp = sum(actual != label and predicted == label for actual, predicted in pairs)
        fn = sum(actual == label and predicted != label for actual, predicted in pairs)
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        per_class[str(label)] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
        f1s.append(f1)
        recalls.append(recall)
    confidences = [item[1] for item in predictions]
    brier = sum(
        sum(((confidence if score == predicted else 0.0) - (1.0 if score == actual else 0.0)) ** 2 for score in (0, 1, 2))
        for (actual, predicted), confidence in zip(pairs, confidences)
    ) / len(pairs) if pairs else 0
    bins = [[] for _ in range(10)]
    for (actual, predicted), confidence in zip(pairs, confidences):
        bins[min(9, int(confidence * 10))].append((actual == predicted, confidence))
    ece = sum(abs(sum(int(ok) for ok, _ in bucket) / len(bucket) - sum(conf for _, conf in bucket) / len(bucket)) * len(bucket) / len(pairs) for bucket in bins if bucket) if pairs else 0
    return {
        "n": len(pairs),
        "accuracy": round(accuracy, 4),
        "macro_f1": round(sum(f1s) / 3, 4),
        "balanced_accuracy": round(sum(recalls) / 3, 4),
        "brier": round(brier, 4),
        "ece_10_bin": round(ece, 4),
        "per_class": per_class,
        "confusion": dict(Counter(f"{actual}->{predicted}" for actual, predicted in pairs)),
    }


def per_item_metrics(records: list[dict], predictions_: list[tuple[int, float, float]]) -> dict[str, dict]:
    output = {}
    question_ids = sorted({record["question_id"] for record in records})
    for question_id in question_ids:
        subset = [(record, prediction) for record, prediction in zip(records, predictions_) if record["question_id"] == question_id]
        output[question_id] = metrics([record for record, _ in subset], [prediction for _, prediction in subset])
    return output


def selective_metrics(records: list[dict], predictions_: list[tuple[int, float, float]], threshold: float) -> dict:
    covered = [(record, prediction) for record, prediction in zip(records, predictions_) if prediction[2] >= threshold]
    coverage = len(covered) / len(records) if records else 0
    accuracy = sum(record["legacy_score"] == prediction[0] for record, prediction in covered) / len(covered) if covered else None
    return {
        "policy": "abstain_below_calibrated_margin",
        "margin_threshold": threshold,
        "coverage": round(coverage, 4),
        "abstentions": len(records) - len(covered),
        "accuracy_on_covered": round(accuracy, 4) if accuracy is not None else None,
        "risk_on_covered": round(1 - accuracy, 4) if accuracy is not None else None,
    }


def predictions(model: dict, records: list[dict]) -> list[tuple[int, float, float]]:
    output = []
    for record in records:
        scores = similarity_scores(model, record["question_id"], record["response"])
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        probabilities = calibrated_probabilities(scores, float(model["temperature"]))
        output.append((ordered[0][0], probabilities[ordered[0][0]], ordered[0][1] - ordered[1][1]))
    return output


def choose_temperature(model: dict, validation: list[dict]) -> float:
    best = (math.inf, 0.2)
    for temperature in (0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0):
        model["temperature"] = temperature
        loss = 0.0
        for record, prediction in zip(validation, predictions(model, validation)):
            scores = similarity_scores(model, record["question_id"], record["response"])
            probabilities = calibrated_probabilities(scores, temperature)
            loss -= math.log(max(1e-9, probabilities[int(record["legacy_score"])]))
        if validation:
            loss /= len(validation)
        if loss < best[0]:
            best = (loss, temperature)
    return best[1]


def choose_margin(model: dict, validation: list[dict]) -> float:
    candidates = sorted({round(item[2], 4) for item in predictions(model, validation)})
    best = (0.0, 0.0)
    for threshold in candidates:
        covered = [(record, prediction) for record, prediction in zip(validation, predictions(model, validation)) if prediction[2] >= threshold]
        coverage = len(covered) / len(validation) if validation else 0
        if coverage < 0.7 or not covered:
            continue
        accuracy = sum(record["legacy_score"] == prediction[0] for record, prediction in covered) / len(covered)
        objective = accuracy - 0.08 * (1 - coverage)
        if objective > best[0]:
            best = (objective, threshold)
    return round(best[1], 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/derived/responses.jsonl"))
    parser.add_argument("--model", type=Path, default=Path("models/supervised/char_centroid_v1.json"))
    parser.add_argument("--report", type=Path, default=Path("data/derived/evaluation.json"))
    args = parser.parse_args()
    records = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    train = [record for record in records if record["split"] == "train"]
    validation = [record for record in records if record["split"] == "validation"]
    test = [record for record in records if record["split"] == "test"]
    model = train_centroid_model(train)
    model["temperature"] = choose_temperature(model, validation)
    model["uncertainty_margin"] = choose_margin(model, validation)
    model["trained_on"] = "participant-locked train split only"
    model["training_records"] = len(train)
    model["data_sha256"] = hashlib.sha256(args.data.read_bytes()).hexdigest()
    model["generated_on"] = date.today().isoformat()
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.model.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "model": {key: model[key] for key in ("model_type", "version", "ngram_sizes", "temperature", "uncertainty_margin", "training_records", "data_sha256", "generated_on")},
        "validation": metrics(validation, predictions(model, validation)),
        "test": metrics(test, predictions(model, test)),
        "validation_per_item": per_item_metrics(validation, predictions(model, validation)),
        "test_per_item": per_item_metrics(test, predictions(model, test)),
        "selective": {
            "validation": selective_metrics(validation, predictions(model, validation), float(model["uncertainty_margin"])),
            "test": selective_metrics(test, predictions(model, test), float(model["uncertainty_margin"])),
        },
        "clarification_experiment": {"status": "NOT_ESTIMATED_FROM_STATIC_DATA", "note": "Requires prospective clarification events; runtime rate is reported by the audit store."},
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
