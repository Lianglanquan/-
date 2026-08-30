"""Run the local scorer over the filtered real-survey answer set.

This is a non-persistent smoke test: it reads derived answer records, scores
them in memory, and prints aggregate quality counts only. It never writes to
the runtime audit database and never prints participant identifiers or answer
text.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.scoring.engine import load_rubrics, score_response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/derived/real_survey/responses.jsonl"))
    args = parser.parse_args()

    records = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    rubrics = load_rubrics(ROOT)
    status = Counter()
    safety = Counter()
    provisional_by_item = Counter()
    participant_ids = {record["participant_id"] for record in records}
    for record in records:
        result = score_response(record["question_id"], record["response"], rubrics)
        status[result.score_status] += 1
        safety[result.safety_state] += 1
        if result.score_status == "PROVISIONAL":
            provisional_by_item[record["question_id"]] += 1

    print(json.dumps({
        "participants": len(participant_ids),
        "responses": len(records),
        "score_status": dict(status),
        "safety_state": dict(safety),
        "provisional_by_item": dict(sorted(provisional_by_item.items())),
        "q20_out_of_range_in_derived": sum(
            1 for record in records
            if record["question_id"] == "Q20" and record["response"].strip() in {"30", "70", "80"}
        ),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
