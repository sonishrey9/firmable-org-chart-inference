"""Scoring against the hidden answer key.

The truth table is only read here, never by ``infer.py``.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .calibrate import CalibratedHeuristic, ConfidenceModel
from .infer import FEATURES, Config, infer_all

TARGET_PRECISION = 0.95


def split_of(company_id: str) -> str:
    return "test" if int(company_id[1:]) % 5 in (0, 1) else "train"   # 40% held-out companies


def _same_person(a, b, dup: dict) -> bool:
    if a is None or b is None or (isinstance(a, float)) or (isinstance(b, float)):
        return False
    return a == b or dup.get(a) == b or dup.get(b) == a


def label(pred: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    t = truth.rename(columns={"manager_id": "true_manager_id", "company_id": "_cid"})
    m = pred.merge(t, on="person_id", how="left", suffixes=("", "_true"))
    dup = {k: v for k, v in zip(truth.person_id, truth.duplicate_of) if isinstance(v, str)}
    parent = {k: v for k, v in zip(truth.person_id, truth.manager_id) if isinstance(v, str)}
    m["has_true_manager"] = m["true_manager_id"].notna()
    m["proposed_correct"] = [_same_person(p, t_, dup) for p, t_ in zip(m.proposed_manager_id, m.true_manager_id)]
    m["edge"] = m["status"].eq("edge")
    m["edge_correct"] = m["edge"] & m["proposed_correct"]

    def ancestors(pid):
        out, cur = set(), dup.get(pid, pid)
        for _ in range(12):
            cur = parent.get(cur)
            if not cur:
                break
            out.add(cur)
        return out
    m["rollup"] = m["status"].eq("rollup")
    m["rollup_correct"] = [bool(r) and (dup.get(rid, rid) in ancestors(pid))
                           for r, rid, pid in zip(m.rollup, m.rollup_id, m.person_id)]
    m["split"] = m["company_id"].map(split_of)
    return m


def headline(m: pd.DataFrame) -> dict:
    n_true = int(m.has_true_manager.sum())
    n_edge = int(m.edge.sum())
    n_ok = int(m.edge_correct.sum())
    prec = n_ok / n_edge if n_edge else 0.0
    rec = n_ok / n_true if n_true else 0.0
    n_roll = int(m.rollup.sum())
    return dict(
        people=int(len(m)), people_with_true_manager=n_true, edges=n_edge, correct_edges=n_ok,
        wrong_edges=n_edge - n_ok, precision=round(prec, 4), recall=round(rec, 4),
        coverage=round(n_edge / n_true, 4) if n_true else 0.0,
        f1=round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
        wrong_edges_on_people_without_manager=int((m.edge & ~m.has_true_manager).sum()),
        rollups=n_roll, rollup_precision=round(m.rollup_correct.sum() / n_roll, 4) if n_roll else None,
        answered_any=round(((m.edge | m.rollup) & m.has_true_manager).sum() / n_true, 4) if n_true else 0.0,
    )


def pick_threshold(conf: np.ndarray, correct: np.ndarray, target=TARGET_PRECISION) -> float:
    """Lowest threshold whose (train) precision stays >= target."""
    best = 0.99
    for t in np.round(np.arange(0.99, 0.29, -0.01), 2):
        sel = conf >= t
        if sel.sum() < 50:
            continue
        if correct[sel].mean() >= target:
            best = float(t)
        else:
            break
    return best


def precision_coverage_curve(m: pd.DataFrame) -> pd.DataFrame:
    n_true = m.has_true_manager.sum()
    has = m.proposed_manager_id.notna()
    rows = []
    for t in np.round(np.arange(0.0, 1.0, 0.025), 3):
        sel = has & (m.confidence >= t)
        k = sel.sum()
        rows.append(dict(threshold=float(t), edges=int(k), precision=float(m.proposed_correct[sel].mean()) if k else None,
                         coverage=float(k / n_true)))
    return pd.DataFrame(rows)


def reliability(m: pd.DataFrame, col: str = "confidence", bins: int = 10) -> pd.DataFrame:
    has = m.proposed_manager_id.notna() & m.features.notna()
    d = m[has]
    b = np.clip((d[col] * bins).astype(int), 0, bins - 1)
    g = d.groupby(b)
    return pd.DataFrame(dict(bin_lo=g[col].min().index / bins, mean_confidence=g[col].mean(),
                             accuracy=g.proposed_correct.mean(), n=g.size())).reset_index(drop=True)


def breakdown(m: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    for k, g in m.groupby(by, observed=True):
        h = headline(g)
        rows.append({by: k, "precision": h["precision"], "coverage": h["coverage"], "edges": h["edges"],
                     "answered_any": h["answered_any"]})
    return pd.DataFrame(rows)


def sales_questions(m: pd.DataFrame, truth: pd.DataFrame) -> dict:
    """'Who runs <dept>?' and 'who is the economic buyer (first VP/exec) above this IC?'."""
    t = truth.set_index("person_id")
    dup = {k: v for k, v in zip(truth.person_id, truth.duplicate_of) if isinstance(v, str)}
    # who runs dept
    res_head = []
    live_truth = truth[~truth.is_stale & truth.duplicate_of.isna() & truth.true_dept.notna()]
    true_heads = {}
    for (cid, d), g in live_truth.groupby(["company_id", "true_dept"]):
        top = g[g.true_level == g.true_level.min()]
        if len(top) == 1:
            true_heads[(cid, d)] = top.person_id.iloc[0]
    pm = m[m.dup_of_record.isna() & m.dept.notna() & m.level.notna() & ~m.is_stale_guess]
    for (cid, d), g in pm.groupby(["company_id", "dept"]):
        if (cid, d) not in true_heads:
            continue
        top = g[g.level == g.level.min()]
        guess = top.person_id.iloc[0] if len(top) == 1 else None
        res_head.append(guess is not None and _same_person(guess, true_heads[(cid, d)], dup) if guess else None)
    answered = [x for x in res_head if x is not None]
    # economic buyer: first ancestor at level <= 2 (VP or exec)
    pred_parent = {}
    for pid, st, mid, rid in zip(m.person_id, m.status, m.manager_id, m.rollup_id):
        if st == "edge":
            pred_parent[pid] = mid
        elif st == "rollup":
            pred_parent[pid] = rid
    lvl = dict(zip(m.person_id, m.level))
    tparent = {k: v for k, v in zip(truth.person_id, truth.manager_id) if isinstance(v, str)}
    tlvl = dict(zip(truth.person_id, truth.true_level))

    def first_buyer(pid, parent, levels):
        cur = pid
        for _ in range(10):
            cur = parent.get(cur)
            if cur is None:
                return None
            if levels.get(cur) is not None and levels.get(cur) <= 2:
                return cur
        return None
    def true_ancestors(pid):
        out, cur = set(), dup.get(pid, pid)
        for _ in range(12):
            cur = tparent.get(cur)
            if not cur:
                break
            out.add(cur)
        return out
    ics = m[(m.true_level == 5) & m.has_true_manager]
    n_ok = n_ans = n_in_chain = 0
    for pid in ics.person_id:
        g = first_buyer(pid, pred_parent, lvl)
        if g is None:
            continue
        n_ans += 1
        tb = first_buyer(dup.get(pid, pid), tparent, tlvl)
        n_ok += _same_person(g, tb, dup)
        n_in_chain += dup.get(g, g) in true_ancestors(pid)
    return dict(
        who_runs_dept=dict(questions=len(res_head), answered=len(answered),
                           precision=round(float(np.mean(answered)), 4) if answered else None,
                           coverage=round(len(answered) / len(res_head), 4) if res_head else None),
        economic_buyer_above_ic=dict(questions=int(len(ics)), answered=n_ans,
                                     precision_nearest_vp_or_exec=round(n_ok / n_ans, 4) if n_ans else None,
                                     precision_in_true_chain=round(n_in_chain / n_ans, 4) if n_ans else None,
                                     coverage=round(n_ans / len(ics), 4) if len(ics) else None),
    )


def run_pipeline(people: pd.DataFrame, truth: pd.DataFrame, cfg: Config | None = None, model_kind: str = "heuristic"):
    """Fit the confidence model + threshold on train companies only; predict everything.

    Returns (labelled predictions, model or None, threshold).
    """
    cfg = cfg or Config()
    train_ids = {c for c in people.company_id.unique() if split_of(c) == "train"}
    raw_pred = infer_all(people[people.company_id.isin(train_ids)], replace(cfg, always_guess=True))
    lab = label(raw_pred, truth)
    has = lab.proposed_manager_id.notna() & lab.features.notna()
    y = lab.proposed_correct[has].to_numpy()
    feats = list(lab.features[has])
    if model_kind == "logistic":
        model = ConfidenceModel.fit(FEATURES, feats, y)
    else:
        model = CalibratedHeuristic.fit(feats, y)
    conf = model.predict_many(feats)
    thr = pick_threshold(conf, y)
    # roll-up threshold: same precision target, picked on train roll-ups
    rthr = thr
    if cfg.use_rollup:
        probe = label(infer_all(people[people.company_id.isin(train_ids)],
                                replace(cfg, threshold=thr, rollup_threshold=0.5), model=model), truth)
        r = probe[probe.rollup]
        if len(r) >= 50:
            rthr = max(0.5, pick_threshold(r.rollup_conf.to_numpy(), r.rollup_correct.to_numpy()))
    final_cfg = replace(cfg, threshold=thr, rollup_threshold=rthr)
    pred = infer_all(people, final_cfg, model=model)
    out = label(pred, truth)
    out.attrs["rollup_threshold"] = rthr
    return out, model, thr
