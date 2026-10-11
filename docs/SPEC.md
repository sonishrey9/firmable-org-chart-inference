# SPEC: Org Chart Inference

Written before any code. Coding agents implement against this file; if the code and the spec disagree, the spec wins until it is changed on purpose.

## Problem
Input: for each company, a flat list of people: `person_id, company_id, full_name, title, department, location, last_updated`. Any field except the ids may be missing or wrong.
Output: for each person, either a `manager_id` with a `confidence` in [0, 1], or **no edge** (abstain). A wrong edge is worse than no edge.

## Non-negotiables
1. **Truth first, mess second.** The generator builds a true reporting tree, then derives the flat list from it and adds noise. The answer key (`truth.parquet`) is never read by the inference code.
2. **Deterministic edges.** Every edge comes from rules that can be explained in one sentence. An LLM may only help parse a title the rules can't read. It never creates or overrides an edge, and it is off by default.
3. **Calibrated confidence.** "0.9" should mean right about 9 times in 10. Calibration is fitted on train companies and reported on held-out test companies.
4. **Abstain by default.** Below the operating threshold we publish no edge. If every plausible manager rolls up to the same person, we publish a weaker "rolls up to" (skip-level) link instead.
5. **Numbers come from runs.** README metrics are pasted from `reports/metrics.json`, produced by `scripts/run_eval.py`.

## Data requirements (from Firmable)
- >= 500 companies, each >= 100 employees, a mix of industries and sizes.
- Realistic titles across functions and seniority. Messy: inconsistent titles, abbreviations, missing fields.

## Noise model (per company noise level: clean / moderate / messy / very_messy)
Title synonyms and abbreviations, typos, casing, junk suffixes, missing titles, missing or wrong department field, missing location, specialty dropped from manager titles, duplicate records, contractors, stale records of people who have left, and a held-out vocabulary (titles the parser was never written for) to test how well it generalises.

## Pipeline
1. `titles.parse_title`: title + department field -> level (0 CEO, 1 exec, 2 VP, 3 director, 4 manager, 5 IC), department, specialty, exec role, flags, parse confidence.
2. `infer.infer_company`: dedupe, re-level relative to the company, pick candidate managers in the nearest layer above, score them (department, specialty, location), give a raw confidence, then abstain or emit.
3. `calibrate`: isotonic fit of raw confidence -> P(correct) on train companies.
4. `evaluate`: precision, recall, coverage, F1, calibration curve, precision-coverage curve, breakdowns, sales-question accuracy, and ablations.

## Acceptance
- Test-split edge precision >= 0.95 at the chosen threshold.
- `pytest` green. `scripts/run_eval.py` reproduces `reports/metrics.json` from seed 42.
