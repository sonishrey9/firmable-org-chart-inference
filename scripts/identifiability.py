"""Upper bound: how many ICs could be placed even with PERFECT title parsing?

An IC's manager is identifiable from titles only if no other manager in the company shares
the true manager's (department, level, team), optionally plus office. Uses the answer key,
so it is an analysis tool, not part of inference.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
p = pd.read_parquet(ROOT / "data" / "people.parquet")
t = pd.read_parquet(ROOT / "data" / "truth.parquet")
t = t[~t.is_stale & t.duplicate_of.isna()].merge(p[["person_id", "location"]], on="person_id")
mg = t[t.n_direct_reports > 0]
k1 = mg.groupby(["company_id", "true_dept", "true_level", "true_specialty"], dropna=False).size()
k2 = mg.groupby(["company_id", "true_dept", "true_level", "true_specialty", "location"], dropna=False).size()
info = t.set_index("person_id")
ics = t[(t.true_level == 5) & t.manager_id.notna()]
u1 = u2 = 0
for mid, cid in zip(ics.manager_id, ics.company_id):
    m = info.loc[mid]
    key = (cid, m.true_dept, m.true_level, m.true_specialty)
    u1 += k1.get(key, 0) == 1
    u2 += k2.get(key + (m.location,), 0) == 1
print(f"ICs: {len(ics)}; identifiable by team: {u1 / len(ics):.1%}; by team + office: {u2 / len(ics):.1%}")
out = {"ics": int(len(ics)), "by_team": round(u1 / len(ics), 4), "by_team_and_office": round(u2 / len(ics), 4),
       "note": "Share of ICs whose true manager is the only manager in the company with that dept/level/team (upper bound for any title-only method)."}
(ROOT / "reports" / "identifiability.json").write_text(json.dumps(out, indent=2))
