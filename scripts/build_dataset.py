"""Build all derived research artifacts from the two raw source files."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from parse_excel import parse_workbook
from parse_rubric import parse_docx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", type=Path, default=Path("data/raw/系统调试样本.xlsx"))
    parser.add_argument("--docx", type=Path, default=Path("data/raw/正式调研题项及评分细则(1).docx"))
    parser.add_argument("--out", type=Path, default=Path("data/derived"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    records = parse_workbook(args.xlsx)
    with (args.out / "responses.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    rubrics = parse_docx(args.docx)
    (args.out / "rubrics.json").write_text(json.dumps(rubrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_dir = Path("rubrics")
    rubric_dir.mkdir(parents=True, exist_ok=True)
    for rubric in rubrics:
        (rubric_dir / f"{rubric['id']}.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "participants": len({r["participant_id"] for r in records}),
        "responses": len(records),
        "questions": len({r["question_id"] for r in records}),
        "split_participants": Counter(r["split"] for r in {x["participant_id"]: x for x in records}.values()),
        "legacy_scores": Counter(str(r["legacy_score"]) for r in records),
        "source_files": [args.xlsx.as_posix(), args.docx.as_posix()],
    }
    (args.out / "dataset_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
