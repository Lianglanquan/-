# Project Guidance

## Scope

This repository contains a React/Vite frontend and a Python backend for a psychological assessment research project.

## Data handling

- Keep source spreadsheets and documents in `data/raw/`.
- Store generated artifacts in `data/derived/`; never overwrite raw inputs.
- Do not commit personally identifiable or sensitive response data.
- Rubric changes must be reviewed alongside the affected evaluation tests.

## Validation

- Frontend: run `npm run build`.
- Backend: install `backend/requirements.txt` and run `python -m compileall backend/app`.
