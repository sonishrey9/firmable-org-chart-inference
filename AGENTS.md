# AGENTS.md: instructions for coding agents working in this repo

Read `docs/SPEC.md` first. It is the source of truth, and code that contradicts it is a bug.

## Ground rules
- **Deterministic edges.** Reporting lines come from rules in `orgchart/infer.py`. An LLM may only help parse titles the rules can't read (`orgchart/llm_fallback.py`, off by default). It never creates or overrides an edge.
- **Never read the answer key in inference.** `truth.parquet` is used only in `orgchart/evaluate.py`.
- **The parser and the generator vocabularies stay independent.** Don't copy generator tables into `titles.py`, and don't "fix" a held-out title by adding it to the parser. Held-out titles measure generalisation.
- **Numbers come from runs.** If you change inference, rerun `python scripts/run_eval.py && python scripts/build_app_data.py` and update the README tables from `reports/metrics.json`.
- **Keep it small.** No new heavy dependencies (the app must fit in 512 MB on Render's free tier). No Node build step for the frontend.
- Small commits with clear messages, and keep `pytest -q` green.

## Layout
| Path | What |
|---|---|
| `orgchart/generator.py` | Builds the true tree, then the messy flat list and the answer key |
| `orgchart/titles.py` | Title parser: rules, abbreviations, RapidFuzz typo repair |
| `orgchart/infer.py` | Candidate selection, scoring, abstention, roll-ups |
| `orgchart/calibrate.py` | Isotonic calibration; the logistic-regression ablation |
| `orgchart/evaluate.py` | Metrics, curves, breakdowns, sales questions |
| `scripts/` | `generate_data.py`, `run_eval.py`, `build_app_data.py` |
| `app/` | FastAPI backend (`main.py`) and the static frontend (`static/`) |
| `tests/` | pytest |

## Commands
```bash
python scripts/generate_data.py      # data/*.parquet (seed 42, 520 companies)
python scripts/run_eval.py           # reports/metrics.json, data/predictions.parquet
python scripts/build_app_data.py     # data/app/ (per-company gzip JSON for the UI)
pytest -q
uvicorn app.main:app --reload        # http://127.0.0.1:8000
```
