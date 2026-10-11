"""Precompute compact per-company JSON for the web app (lazy-loaded, gzip, ~25 KB each).

Run after scripts/run_eval.py. Output: data/app/index.json and data/app/companies/<id>.json.gz
"""
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orgchart.evaluate import label, split_of  # noqa: E402
from orgchart.titles import LEVEL_NAMES  # noqa: E402

data = ROOT / "data"
out = data / "app"
(out / "companies").mkdir(parents=True, exist_ok=True)
people = pd.read_parquet(data / "people.parquet")
truth = pd.read_parquet(data / "truth.parquet")
companies = pd.read_parquet(data / "companies.parquet")
pred = pd.read_parquet(data / "predictions.parquet")
metrics = json.loads((ROOT / "reports" / "metrics.json").read_text())
op = metrics["operating_point"]

lab = label(pred.drop(columns=["company_id"]).merge(people[["person_id", "company_id"]], on="person_id"), truth)
df = lab.merge(people[["person_id", "full_name", "title", "department", "location", "last_updated"]], on="person_id")


def _s(v):
    return None if v is None or (isinstance(v, float) and v != v) or v is pd.NaT else v


index = []
for cid, g in df.groupby("company_id"):
    meta = companies[companies.company_id == cid].iloc[0].to_dict()
    nodes = []
    for r in g.itertuples(index=False):
        nodes.append(dict(
            id=r.person_id, name=r.full_name, title=_s(r.title), department=_s(r.department), location=_s(r.location),
            updated=r.last_updated.strftime("%Y-%m-%d") if pd.notna(r.last_updated) else None,
            level=None if pd.isna(r.level) else int(r.level),
            level_name=None if pd.isna(r.level) else LEVEL_NAMES[int(r.level)],
            dept=_s(r.dept), specialty=_s(r.specialty), status=r.status,
            manager_id=_s(r.proposed_manager_id), confidence=round(float(r.confidence), 3),
            rollup_id=_s(r.rollup_id), rollup_conf=round(float(r.rollup_conf), 3), reason=r.reason,
            candidates=json.loads(r.candidates), stale=bool(r.is_stale_guess), duplicate_of=_s(r.dup_of_record),
            true_manager_id=_s(r.true_manager_id), proposed_correct=bool(r.proposed_correct),
        ))
    n_true = int(g.has_true_manager.sum())
    n_edge = int(g.edge.sum())
    stats = dict(precision=round(float(g.edge_correct.sum() / n_edge), 3) if n_edge else None,
                 coverage=round(n_edge / n_true, 3) if n_true else None, edges=n_edge, people=len(g),
                 rollups=int(g.rollup.sum()))
    payload = dict(company=dict(meta, split=split_of(cid), **stats), threshold=op["threshold"],
                   rollup_threshold=op["rollup_threshold"], nodes=nodes)
    with gzip.open(out / "companies" / f"{cid}.json.gz", "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    index.append(dict(meta, split=split_of(cid), **stats))
(out / "index.json").write_text(json.dumps(index, separators=(",", ":"), default=str))
print(f"wrote {len(index)} companies to {out}")
