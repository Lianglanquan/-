# Evaluation

The research pipeline compares baselines behind the same `ScoreResult` contract. `scripts/evaluate.py` remains the transparent keyword reference; `scripts/train_centroid.py` trains the shipped participant-locked character n-gram TF-IDF centroid baseline and writes `models/supervised/char_centroid_v1.json` plus `data/derived/evaluation.json`. The runtime defaults to this local baseline. Provider-backed prompting is an opt-in comparison path, not a requirement for participant scoring.

The generated evaluation report includes accuracy, macro-F1, balanced accuracy, per-class metrics, confusion, calibration (ECE/Brier), per-item results, and selective coverage-risk metrics. Clarification resolution is intentionally marked as prospective until enough runtime events exist; the live rate is reported by the audit store in `/api/research/summary`. All static metrics use participant-level locked splits from `data/derived/dataset_manifest.json`.

Do not use legacy labels as unquestioned truth. Release gates should report agreement with legacy labels separately from agreement with adjudicated labels, and include the proportion of `INSUFFICIENT` and `EXPERT_DISAGREEMENT` cases.
