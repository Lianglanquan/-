"""Evaluate a transparent keyword baseline and selective prediction metrics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

AMBIGUOUS = ("不知道", "不清楚", "随缘", "还行", "责任", "担心", "无所谓", "说不清", "没想法")


def predict(text: str, rubric: dict | None = None) -> int:
    """Small reproducible baseline used as a comparison point, not a clinical model."""
    value = text.strip()
    if not value:
        return 1
    high = ("绝望", "解脱", "负担", "废物", "没用", "等待死亡", "完蛋", "放弃")
    mid = ("焦虑", "担心", "难过", "孤单", "失望", "随缘", "不知道", "还行")
    if any(token in value for token in high):
        return 2
    if any(token in value for token in mid):
        return 1
    return 0


def _metrics(records: list[dict]) -> dict:
    if not records:
        return {"macro_f1": None, "balanced_accuracy": None, "selective": []}
    per_class = {}
    recalls = []
    f1s = []
    for label in (0, 1, 2):
        tp = sum(r["legacy_score"] == label and predict(r["response"]) == label for r in records)
        fp = sum(r["legacy_score"] != label and predict(r["response"]) == label for r in records)
        fn = sum(r["legacy_score"] == label and predict(r["response"]) != label for r in records)
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        per_class[str(label)] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
        recalls.append(recall)
        f1s.append(f1)
    # The baseline abstains on the same short/abstract cases used by the UI.
    eligible = [r for r in records if not (len(r["response"].strip()) <= 3 or r["response"].strip() in AMBIGUOUS)]
    selective_accuracy = sum(predict(r["response"]) == r["legacy_score"] for r in eligible) / len(eligible) if eligible else None
    return {"macro_f1": round(sum(f1s) / 3, 4), "balanced_accuracy": round(sum(recalls) / 3, 4), "per_class": per_class, "selective": [{"policy": "abstain_short_or_abstract", "coverage": round(len(eligible) / len(records), 4), "accuracy_on_covered": round(selective_accuracy, 4) if selective_accuracy is not None else None}]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/derived/responses.jsonl"))
    parser.add_argument("--split", default="test")
    args = parser.parse_args()
    records = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = [r for r in records if r["split"] == args.split and r["legacy_score"] is not None]
    correct = sum(predict(r["response"]) == r["legacy_score"] for r in records)
    confusion = Counter(f"{r['legacy_score']}->{predict(r['response'])}" for r in records)
    print(json.dumps({"split": args.split, "n": len(records), "accuracy": round(correct / len(records), 4) if records else None, "confusion": dict(confusion), **_metrics(records)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
