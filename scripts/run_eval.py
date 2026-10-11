"""Run the full evaluation and write reports/metrics.json (+ CSVs used by the app and README).

Usage: python scripts/run_eval.py [--no-ablations]
All numbers in the README come from this script's output.
"""
import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orgchart.evaluate import (breakdown, headline, precision_coverage_curve, reliability,  # noqa: E402
                               run_pipeline, sales_questions)
from orgchart.infer import Config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--no-ablations", action="store_true")
ap.add_argument("--data", default=str(ROOT / "data"))
a = ap.parse_args()
data = Path(a.data)
reports = ROOT / "reports"
reports.mkdir(exist_ok=True)

people = pd.read_parquet(data / "people.parquet")
truth = pd.read_parquet(data / "truth.parquet")
companies = pd.read_parquet(data / "companies.parquet")

t0 = time.time()
m, model, thr = run_pipeline(people, truth)
elapsed = time.time() - t0
m = m.merge(companies[["company_id", "industry", "size_bucket", "noise_level", "country"]], on="company_id", how="left")
test = m[m.split == "test"]

# Parser accuracy vs truth (live, non-duplicate records)
live = test[~test.is_stale & test.duplicate_of.isna()]
parse = dict(
    level_accuracy=round(float((live.level == live.true_level).mean()), 4),
    dept_accuracy_when_given=round(float((live.dept == live.true_dept)[live.true_dept.notna() & live.dept.notna()].mean()), 4),
    unparsed_rate=round(float(live.level.isna().mean()), 4),
    heldout_titles=int(live.heldout_title.sum()),
    heldout_unparsed_rate=round(float(live[live.heldout_title].level.isna().mean()), 4),
)
stale = test[test.is_stale]
stale_m = dict(stale_records=int(len(stale)), flagged_by_date=round(float(stale.is_stale_guess.mean()), 4),
               got_a_wrong_edge=int(stale.edge.sum()))

metrics = dict(
    generated_at=time.strftime("%Y-%m-%d %H:%M %Z"),
    dataset=dict(companies=int(len(companies)), records=int(len(people)),
                 employees_min=int(companies.n_employees.min()), employees_max=int(companies.n_employees.max()),
                 employees_median=int(companies.n_employees.median()),
                 industries=companies.industry.value_counts().to_dict(),
                 size_buckets=companies.size_bucket.value_counts().to_dict(),
                 noise_levels=companies.noise_level.value_counts().to_dict(),
                 test_companies=int(test.company_id.nunique()), train_companies=int(m[m.split == "train"].company_id.nunique())),
    operating_point=dict(threshold=thr, rollup_threshold=m.attrs.get("rollup_threshold"), target_precision=0.95,
                         chosen_on="train companies", reported_on="held-out test companies"),
    test=headline(test), train=headline(m[m.split == "train"]),
    naive_always_guess_test=None,
    parser=parse, stale=stale_m,
    sales_questions=sales_questions(test, truth),
    runtime_seconds_full_pipeline=round(elapsed, 1),
    calibration_model=json.loads(model.to_json()),
)
pc = precision_coverage_curve(test)
rel = reliability(test)
rel_raw = reliability(test, col="raw_conf")
metrics["curves"] = dict(precision_coverage=pc.to_dict("records"), reliability=rel.to_dict("records"),
                         reliability_raw=rel_raw.to_dict("records"))
naive = pc.iloc[0]
metrics["naive_always_guess_test"] = dict(precision=round(float(naive.precision), 4), coverage=round(float(naive.coverage), 4),
                                          note="top candidate for everyone, no abstention")
metrics["breakdowns"] = {k: breakdown(test, k).to_dict("records") for k in
                         ["noise_level", "size_bucket", "industry", "true_level", "is_contractor", "heldout_title"]}

if not a.no_ablations:
    abl = {}
    for name, cfg, kind in [
        ("full system", Config(), "heuristic"),
        ("no specialty signal", Config(use_specialty=False), "heuristic"),
        ("no location signal", Config(use_location=False), "heuristic"),
        ("no stale-record signal", Config(use_stale=False), "heuristic"),
        ("no company-relative re-levelling", Config(use_relevel=False), "heuristic"),
        ("no dedupe", Config(use_dedupe=False), "heuristic"),
        ("no roll-ups", Config(use_rollup=False), "heuristic"),
        ("logistic regression confidence (16 features)", Config(), "logistic"),
    ]:
        if name == "full system":
            mm, t_ = m, thr
        else:
            mm, _, t_ = run_pipeline(people, truth, cfg, model_kind=kind)
        h = headline(mm[mm.split == "test"])
        abl[name] = dict(threshold=t_, precision=h["precision"], coverage=h["coverage"], f1=h["f1"],
                         answered_any=h["answered_any"], rollup_precision=h["rollup_precision"])
        print(f"{name:48s} thr={t_:.2f} P={h['precision']:.3f} cov={h['coverage']:.3f} any={h['answered_any']:.3f}", flush=True)
    metrics["ablations"] = abl


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else round(float(o), 4)
    if isinstance(o, float) and np.isnan(o):
        return None
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


(reports / "metrics.json").write_text(json.dumps(_clean(metrics), indent=1))
(reports / "confidence_model.json").write_text(model.to_json())
cols = ["person_id", "company_id", "manager_id", "confidence", "raw_conf", "status", "proposed_manager_id", "rollup_id",
        "rollup_conf", "reason", "n_candidates", "candidates", "level", "dept", "specialty", "exec_role", "is_stale_guess",
        "dup_of_record", "parse_conf"]
pred = m[cols].copy()
pred["candidates"] = pred["candidates"].map(lambda c: json.dumps(c) if isinstance(c, (list, tuple, np.ndarray)) else "[]")
pred.to_parquet(data / "predictions.parquet", index=False)
print(json.dumps({k: metrics[k] for k in ["operating_point", "test", "naive_always_guess_test", "parser", "sales_questions"]}, indent=1, default=str))
