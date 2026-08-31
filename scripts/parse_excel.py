"""Parse the historical spreadsheet without treating legacy labels as gold."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import openpyxl

# The source workbook stores the 20 prompts under an internal code system
# whose column order does not match the Q01--Q20 rubric order.  Keep this
# mapping explicit so answer text, legacy labels, and rubrics cannot drift.
QUESTION_CODE_TO_ID = {
    "A1": "Q09",
    "A2": "Q08",
    "A3": "Q10",
    "A4": "Q14",
    "A6": "Q13",
    "B3": "Q01",
    "B5": "Q20",
    "C1": "Q02",
    "C2": "Q04",
    "C3": "Q05",
    "C5": "Q03",
    "D1": "Q11",
    "D2": "Q12",
    "D4": "Q15",
    "D5": "Q06",
    "D6": "Q07",
    "E1": "Q18",
    "E2": "Q17",
    "E5": "Q19",
    "E8": "Q16",
}
QUESTION_CODES = tuple(QUESTION_CODE_TO_ID)


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
        for source_code in QUESTION_CODES:
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
                "question_id": QUESTION_CODE_TO_ID[source_code],
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
