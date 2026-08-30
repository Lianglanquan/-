"""Extract the expert rubric tables from the source DOCX into JSON.

The DOCX remains the source of truth.  The generated JSON is a reviewable,
versioned representation used by the API and experiments.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from docx import Document


def parse_docx(source: Path) -> list[dict]:
    rubrics: list[dict] = []
    for table in Document(source).tables:
        rows = [[" ".join(cell.text.split()) for cell in row.cells] for row in table.rows]
        if len(rows) < 7:
            continue
        question = rows[0][1]
        raw_id = rows[1][1].replace("Q", "")
        if not raw_id.isdigit():
            continue
        item_id = f"Q{int(raw_id):02d}"
        dimension = rows[2][1]
        criteria = []
        for row in rows[4:7]:
            match = re.search(r"([012])分", row[0])
            if not match:
                continue
            criteria.append({
                "score": int(match.group(1)),
                "description": row[1],
                "examples": [x.strip() for x in re.split(r"[、，；;]", row[2]) if x.strip()],
            })
        rubrics.append({
            "id": item_id,
            "source_id": f"Q{int(raw_id)}",
            "version": "1.0.0",
            "status": "source-extracted",
            "question": question,
            "dimension": dimension,
            "criteria": criteria,
            "provenance": {"source": source.name, "table_index": len(rubrics)},
        })
    return sorted(rubrics, key=lambda item: item["id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("rubrics"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rubrics = parse_docx(args.source)
    if len(rubrics) != 20:
        raise SystemExit(f"Expected 20 rubric tables, found {len(rubrics)}")
    for rubric in rubrics:
        (args.output_dir / f"{rubric['id']}.json").write_text(
            json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Wrote {len(rubrics)} rubrics to {args.output_dir}")


if __name__ == "__main__":
    main()
