"""Prepare the anonymous real-survey workbook for local testing.

The attached production survey uses one answer column per Q1--Q20 and does
not contain the historical score/rationale triplets used by
``scripts.parse_excel``.  This parser keeps the answer text, removes an
entire participant when Q20 is clearly outside its documented 0--10 range,
and hashes the source response id before writing derived records.

The raw workbook is never changed and the derived output is intended to stay
on the research workstation.  It must not be committed to the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl


QUESTION_COUNT = 20
ANSWER_START_INDEX = 6  # Column G; the first six columns are metadata.
Q20_INDEX = ANSWER_START_INDEX + QUESTION_COUNT - 1
Q20_RANGE = (0, 10)

_ARABIC_NUMBER = re.compile(r"(?<!\d)(10|[0-9]+)(?:\.0+)?\s*(?:分)?")
_CHINESE_NUMERALS = (
    ("十", 10),
    ("零", 0),
    ("一", 1),
    ("二", 2),
    ("两", 2),
    ("三", 3),
    ("四", 4),
    ("五", 5),
    ("六", 6),
    ("七", 7),
    ("八", 8),
    ("九", 9),
)


def parse_q20_numeric(value: Any) -> int | None:
    """Extract the first explicit Q20 score from a survey answer."""

    text = "" if value is None else str(value).strip()
    if not text:
        return None
    match = _ARABIC_NUMBER.search(text)
    if match:
        return int(match.group(1))
    for numeral, number in _CHINESE_NUMERALS:
        if numeral in text:
            return number
    return None


def q20_validity(value: Any) -> str:
    """Return a stable quality label for the Q20 answer."""

    numeric = parse_q20_numeric(value)
    if numeric is None:
        return "UNPARSEABLE"
    if not Q20_RANGE[0] <= numeric <= Q20_RANGE[1]:
        return "OUT_OF_RANGE"
    return "VALID"


def anonymise_participant_id(source_id: str) -> str:
    """Create a stable opaque id without retaining the source answer id."""

    digest = hashlib.sha256(f"qiuzheng-real-survey-v1:{source_id}".encode("utf-8")).hexdigest()
    return f"real_{digest[:24]}"


def participant_split(source_id: str) -> str:
    """Keep all answers from a participant in one deterministic split."""

    bucket = int(hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "test" if bucket < 20 else "validation" if bucket < 35 else "train"


def _header_map(header_row: tuple[Any, ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, value in enumerate(header_row):
        text = str(value or "").strip().upper()
        if re.fullmatch(r"Q(?:0?[1-9]|1[0-9]|20)", text):
            result.setdefault(text, index)
    missing = [f"Q{index}" for index in range(1, QUESTION_COUNT + 1) if f"Q{index}" not in result and f"Q{index:02d}" not in result]
    if missing:
        raise ValueError(f"real survey workbook is missing answer columns: {', '.join(missing)}")
    return result


def _question_index(header: dict[str, int], position: int) -> int:
    return header.get(f"Q{position}", header.get(f"Q{position:02d}", ANSWER_START_INDEX + position - 1))


def parse_workbook(source: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse and filter the real survey, returning records plus an audit manifest."""

    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = list(worksheet.iter_rows(values_only=True))
    if len(rows) < 3:
        raise ValueError("real survey workbook must contain two header rows and data")

    header = _header_map(tuple(rows[1]))
    participants: list[dict[str, Any]] = []
    excluded_values: Counter[str] = Counter()
    missing_ids = 0
    duplicate_ids = 0
    seen_ids: set[str] = set()

    for values in rows[2:]:
        source_id = str(values[0] or "").strip()
        if not source_id:
            missing_ids += 1
            continue
        if source_id in seen_ids:
            duplicate_ids += 1
            continue
        seen_ids.add(source_id)
        q20_index = _question_index(header, QUESTION_COUNT)
        q20_value = values[q20_index] if q20_index < len(values) else None
        q20_status = q20_validity(q20_value)
        q20_numeric = parse_q20_numeric(q20_value)
        if q20_status == "OUT_OF_RANGE":
            excluded_values[str(q20_numeric)] += 1
            continue
        participants.append({
            "source_id": source_id,
            "q20_status": q20_status,
            "q20_numeric": q20_numeric,
            "split": participant_split(source_id),
            "answers": [
                str(values[_question_index(header, position)] or "").strip()
                if _question_index(header, position) < len(values)
                else ""
                for position in range(1, QUESTION_COUNT + 1)
            ],
        })

    records: list[dict[str, Any]] = []
    for participant in participants:
        participant_id = anonymise_participant_id(participant["source_id"])
        for position, answer in enumerate(participant["answers"], start=1):
            question_id = f"Q{position:02d}"
            records.append({
                "response_id": f"{participant_id}:{question_id}",
                "participant_id": participant_id,
                "question_id": question_id,
                "source_question_code": f"Q{position}",
                "response": answer,
                "legacy_score": None,
                "legacy_rationale": "",
                "evidence_sufficiency": "UNASSESSED",
                "adjudicated_score": None,
                "split": participant["split"],
                "provenance": {
                    "source": source.name,
                    "sheet": worksheet.title,
                    "source_type": "real_survey_answers",
                    "q20_filter": "exclude participant when parsed Q20 is outside [0, 10]",
                },
            })

    input_participants = len(seen_ids)
    included_participants = len(participants)
    manifest = {
        "source_type": "real_survey_answers",
        "source_file": source.name,
        "sheet": worksheet.title,
        "filter_rule": "exclude the entire participant when Q20 parses to a value outside [0, 10]",
        "participants_input": input_participants,
        "participants_included": included_participants,
        "participants_excluded": input_participants - included_participants,
        "responses_included": len(records),
        "responses_excluded": (input_participants - included_participants) * QUESTION_COUNT,
        "excluded_q20_values": dict(sorted(excluded_values.items(), key=lambda item: int(item[0]))),
        "missing_ids": missing_ids,
        "duplicate_ids": duplicate_ids,
        "split_participants": dict(Counter(participant["split"] for participant in participants)),
        "q20_validity_included": dict(Counter(participant["q20_status"] for participant in participants)),
        "privacy": "source participant ids are replaced with stable opaque hashes; raw workbook remains outside version control",
    }
    return records, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, default=Path("data/raw/正式调研380人(1).xlsx"))
    parser.add_argument("--out", type=Path, default=Path("data/derived/real_survey"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    records, manifest = parse_workbook(args.xlsx)
    with (args.out / "responses.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
