"""Parse the historical spreadsheet without treating legacy labels as gold."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import openpyxl

QUESTION_CODES = ["A1", "A2", "A3", "A4", "A6", "B3", "B5", "C1", "C2", "C3", "C5", "D1", "D2", "D4", "D5", "D6", "E1", "E2", "E5", "E8"]


def _split(participant_id: str) -> str:
    # Stable participant-level split: all 20 responses stay together.
    bucket = int(hashlib.sha256(participant_id.encode()).hexdigest()[:8], 16) % 100
    return "test" if bucket < 20 else "validation" if bucket < 35 else "train"


def parse_workbook(source: Path) -> list[dict]:
    ws = openpyxl.load_workbook(source, read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 3:
        return []
    question_codes = {}
    for col in range(6, len(rows[1])):
        code = rows[1][col]
        if isinstance(code, str) and code not in {"原因", "Q"}:
            question_codes.setdefault(code, col)
    records: list[dict] = []
    for values in rows[2:]:
        participant_id = str(values[0] or "").strip()
        if not participant_id:
            continue
        for position, source_code in enumerate(QUESTION_CODES):
            answer_col = question_codes.get(source_code)
            if answer_col is None:
                continue
            score = values[answer_col + 1] if answer_col + 1 < len(values) else None
            rationale = values[answer_col + 2] if answer_col + 2 < len(values) else None
            answer = values[answer_col]
            if answer is None and score is None:
                continue
            records.append({
                "response_id": f"{participant_id}:{source_code}",
                "participant_id": participant_id,
                "question_id": f"Q{position + 1:02d}",
                "source_question_code": source_code,
                "response": str(answer or "").strip(),
                "legacy_score": int(score) if isinstance(score, (int, float)) and int(score) in (0, 1, 2) else None,
                "legacy_rationale": str(rationale or "").strip(),
                "evidence_sufficiency": "UNASSESSED",
                "adjudicated_score": None,
                "split": _split(participant_id),
                "provenance": {"source": source.name, "sheet": ws.title},
            })
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/derived/responses.jsonl"))
    args = parser.parse_args()
    records = parse_workbook(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    participants = len({record["participant_id"] for record in records})
    print(f"Wrote {len(records)} response records from {participants} participants to {args.output}")


if __name__ == "__main__":
    main()
