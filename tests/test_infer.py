import pandas as pd

from orgchart.calibrate import Isotonic
from orgchart.evaluate import headline, label, run_pipeline
from orgchart.generator import generate
from orgchart.infer import Config, infer_company


def _df(rows):
    df = pd.DataFrame(rows, columns=["person_id", "company_id", "full_name", "title", "department", "location"])
    df["last_updated"] = pd.Timestamp("2026-09-01")
    return df


def test_simple_company_is_resolved():
    df = _df([
        ("p1", "c", "Asha Rao", "CEO", None, "Pune"),
        ("p2", "c", "Ben Li", "CTO", None, "Pune"),
        ("p3", "c", "Cara D", "VP Engineering", "Eng", "Pune"),
        ("p4", "c", "Dev K", "Engineering Manager, Backend", "Eng", "Pune"),
        ("p5", "c", "Eli M", "Senior Backend Engineer", "Eng", "Pune"),
    ])
    out = infer_company(df, Config(threshold=0.5)).set_index("person_id")
    assert out.loc["p1", "status"] == "root"
    assert out.loc["p2", "manager_id"] == "p1"
    assert out.loc["p3", "manager_id"] == "p2"
    assert out.loc["p4", "manager_id"] == "p3"
    assert out.loc["p5", "manager_id"] == "p4"


def test_ambiguous_manager_abstains_but_rolls_up():
    df = _df([
        ("p1", "c", "Asha Rao", "CEO", None, "Pune"),
        ("p2", "c", "Ben Li", "CTO", None, "Pune"),
        ("p3", "c", "Cara D", "Engineering Manager", "Eng", "Pune"),
        ("p4", "c", "Dev K", "Engineering Manager", "Eng", "Pune"),
        ("p5", "c", "Eli M", "Software Engineer", "Eng", "Pune"),
    ])
    out = infer_company(df, Config(threshold=0.8, rollup_threshold=0.4)).set_index("person_id")
    assert pd.isna(out.loc["p5", "manager_id"])              # 50/50: no edge
    assert out.loc["p5", "status"] == "rollup"
    assert out.loc["p5", "rollup_id"] == "p2"               # both managers report to the CTO


def test_unparseable_title_gets_no_edge():
    df = _df([("p1", "c", "A", "CEO", None, None), ("p2", "c", "B", "Code Ninja", None, None)])
    out = infer_company(df, Config(threshold=0.1)).set_index("person_id")
    assert pd.isna(out.loc["p2", "manager_id"])


def test_isotonic_is_monotone():
    import numpy as np
    rng = np.random.default_rng(0)
    x = rng.random(2000)
    y = rng.random(2000) < x
    iso = Isotonic.fit(x, y)
    grid = np.linspace(0, 1, 50)
    assert np.all(np.diff(iso(grid)) >= -1e-12)


def test_end_to_end_precision_target_small():
    _, people, truth = generate(25, seed=5)
    m, model, thr = run_pipeline(people, truth)
    h = headline(m[m.split == "train"])
    assert h["precision"] >= 0.9          # threshold was chosen for 0.95 on train
    assert h["edges"] > 0
