"""Deterministic reporting-line inference with abstention.

For each company:
  1. parse titles (rules)                       -> level, dept, specialty, flags
  2. dedupe records of the same person
  3. re-level relative to the company           (e.g. "Head of Data" above Directors acts as the VP)
  4. candidate managers = nearest layer above in the same department, else the exec who
     usually owns that department, else the CEO
  5. score candidates (specialty, location, stale, parse quality) -> raw confidence = share of
     the best candidate x how sure we are about the person's own title
  6. calibrated confidence (isotonic, fitted on train companies) -> emit edge or abstain
  7. if abstaining but every plausible manager rolls up to the same person, emit a weaker
     "rolls up to" (skip-level) link

Every edge carries a one-line, human-readable reason.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from .calibrate import heuristic_conf
from .titles import parse_title, normalise, LEVEL_NAMES

# How often each exec owns a department when it has no leader of its own.
# Hand-set priors (in real life: learned from a few hundred labelled org charts).
OWNER_PRIOR = {
    "Engineering": {"CTO": 1.0}, "Data": {"CDO": 1.0, "CTO": 0.55, "CFO": 0.1, "CEO": 0.2},
    "Product": {"CPO": 1.0, "CTO": 0.3, "CEO": 0.2}, "Design": {"CPO": 0.7, "CTO": 0.2, "CMO": 0.2, "CEO": 0.1},
    "Sales": {"CRO": 1.0, "CEO": 0.1}, "Marketing": {"CMO": 1.0, "CRO": 0.15, "CEO": 0.1},
    "Customer Success": {"CCO": 1.0, "CRO": 0.45, "COO": 0.35, "CEO": 0.1}, "Finance": {"CFO": 1.0, "CEO": 0.1},
    "People": {"CHRO": 1.0, "COO": 0.3, "CEO": 0.25}, "Legal": {"GC": 1.0, "CFO": 0.25, "CEO": 0.15},
    "Operations": {"COO": 1.0, "CEO": 0.15}, "IT": {"CIO": 1.0, "CTO": 0.3, "COO": 0.2, "CFO": 0.1},
    "Security": {"CISO": 1.0, "CTO": 0.45, "CIO": 0.3},
}
STALE_DAYS = 540


@dataclass
class Config:
    use_specialty: bool = True
    use_location: bool = True
    use_stale: bool = True
    use_relevel: bool = True
    use_dedupe: bool = True
    use_rollup: bool = True
    always_guess: bool = False     # baseline: never abstain
    threshold: float = 0.80        # on calibrated confidence
    rollup_threshold: float = 0.85


@dataclass
class Rec:
    pid: str
    name: str
    title: str | None
    loc: str | None
    stale: bool
    level: int | None
    dept: str | None
    spec: str | None
    role: str | None
    assistant: bool
    head_of: bool
    pconf: float
    level_conf: float
    dup_of: str | None = None
    extra: dict = field(default_factory=dict)


def _records(df: pd.DataFrame, ref_date: pd.Timestamp, cfg: Config) -> list[Rec]:
    out = []
    for row in df.itertuples(index=False):
        p = parse_title(row.title if isinstance(row.title, str) else None,
                        row.department if isinstance(row.department, str) else None)
        lu = row.last_updated
        stale = bool(cfg.use_stale and pd.notna(lu) and (ref_date - lu).days > STALE_DAYS)
        out.append(Rec(row.person_id, str(row.full_name), row.title if isinstance(row.title, str) else None,
                       row.location if isinstance(row.location, str) else None, stale, p.level, p.dept,
                       p.specialty, p.exec_role, p.is_assistant, p.head_of, p.conf, p.level_conf))
    return out


def _dedupe(recs: list[Rec]) -> None:
    by_name = defaultdict(list)
    for r in recs:
        by_name[r.name.strip().lower()].append(r)
    for group in by_name.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: (r.title is None, r.stale, -r.pconf))
        keep = group[0]
        kt = normalise(keep.title)[0] if keep.title else ""
        for other in group[1:]:
            ot = normalise(other.title)[0] if other.title else ""
            if not ot or not kt or fuzz.ratio(kt, ot) >= 85:
                other.dup_of = keep.pid


def _relevel(recs: list[Rec]) -> None:
    by_dept = defaultdict(list)
    for r in recs:
        if r.dup_of is None and r.dept and r.level is not None:
            by_dept[r.dept].append(r)
    for dept, rs in by_dept.items():
        has_vp = any(r.level == 2 for r in rs)
        heads = [r for r in rs if r.head_of and r.level == 3 and r.spec is None]
        others = [r for r in rs if r.level == 3 and not (r.head_of and r.spec is None)]
        if heads and not has_vp and (others or len(heads) == 1 and any(r.level == 3 for r in rs if r is not heads[0])):
            for h in heads:
                h.level = 2
                h.extra["releveled"] = "Head of {dept} sits above other directors, treated as the VP".format(dept=dept)
        # A lone "Head of X (specialty)" in a dept without other directors and with managers: director, as parsed.
    # Multiple CEO-like records: keep the most confident, others become execs without a home dept.
    ceos = [r for r in recs if r.level == 0 and r.dup_of is None]
    if len(ceos) > 1:
        ceos.sort(key=lambda r: -r.level_conf)
        for r in ceos[1:]:
            r.level, r.role = 1, None


def _score(child: Rec, cand: Rec, cfg: Config, others_have_spec: bool) -> tuple[float, list[str]]:
    w, why = 1.0, []
    if cfg.use_specialty and child.spec:
        if cand.spec == child.spec:
            w *= 4.0
            why.append(f"same team ({child.spec})")
        elif cand.spec:
            w *= 0.25
        elif others_have_spec:
            w *= 0.8
    if cfg.use_location and child.loc and cand.loc:
        if child.loc == cand.loc:
            w *= 2.0
            why.append(f"same office ({cand.loc})")
        else:
            w *= 0.5
    if cand.stale:
        w *= 0.35
    w *= max(0.3, cand.level_conf)
    return w, why


def _logit(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return float(np.log(p / (1 - p)))


FEATURES = ["share_logit", "pconf_logit", "child_stale", "cand_stale", "cross_dept", "spec_match", "loc_match",
            "loc_mismatch", "log_cands", "phantom", "exec_edge", "child_ic", "child_mgr", "child_head_of",
            "cand_level_conf", "level_gap"]


def infer_company(df: pd.DataFrame, cfg: Config | None = None, ref_date: pd.Timestamp | None = None,
                  model=None) -> pd.DataFrame:
    """Infer edges for one company. Returns one row per input record."""
    cfg = cfg or Config()
    if ref_date is None:
        ref_date = df["last_updated"].max() if df["last_updated"].notna().any() else pd.Timestamp.today()
    recs = _records(df, ref_date, cfg)
    if cfg.use_dedupe:
        _dedupe(recs)
    if cfg.use_relevel:
        _relevel(recs)
    live = [r for r in recs if r.dup_of is None]
    ceos = [r for r in live if r.level == 0]
    ceo = ceos[0] if ceos else None
    execs = [r for r in live if r.level == 1]
    # Records we could not read might be the real manager: count them per department
    unread = defaultdict(int)
    for r in live:
        if r.level is None:
            unread[r.dept] += 1
    by_dept_level = defaultdict(lambda: defaultdict(list))
    for r in live:
        if r.dept and r.level is not None:
            by_dept_level[r.dept][r.level].append(r)

    out = {}
    for r in live:
        cands, weights, why, basis = [], [], [], ""
        if r.level is None:
            out[r.pid] = dict(manager_id=None, raw_conf=0.0, reason="title could not be parsed", n_candidates=0)
            continue
        if r.level == 0:
            out[r.pid] = dict(manager_id=None, raw_conf=0.0, reason="top of company (CEO)", n_candidates=0, is_root=True)
            continue
        if ceo is None:
            out[r.pid] = dict(manager_id=None, raw_conf=0.0, reason="no CEO found in this company", n_candidates=0)
            continue
        cross = False
        if r.level == 1 or r.assistant:
            cands, weights, basis = [ceo], [1.0], "executives and assistants report to the CEO"
        elif not r.dept:
            out[r.pid] = dict(manager_id=None, raw_conf=0.0, reason="department unknown", n_candidates=0)
            continue
        else:
            levels = sorted(l for l in by_dept_level[r.dept] if l < r.level)
            if levels:
                layer = by_dept_level[r.dept][levels[-1]]
                cands = [c for c in layer if c.pid != r.pid]
                basis = f"nearest {LEVEL_NAMES[levels[-1]]} layer above in {r.dept}"
                any_spec = any(c.spec for c in cands)
                scored = [_score(r, c, cfg, any_spec) for c in cands]
                weights = [s[0] for s in scored]
                whys = [s[1] for s in scored]
            else:
                prior = OWNER_PRIOR.get(r.dept, {})
                for e in execs:
                    if e.role in prior:
                        cands.append(e)
                        weights.append(prior[e.role])
                cands.append(ceo)
                weights.append(prior.get("CEO", 0.15))
                basis = f"no {r.dept} leader above, so the exec who usually owns {r.dept}"
                cross = True
                whys = [[] for _ in cands]
        if not cands:
            out[r.pid] = dict(manager_id=None, raw_conf=0.0, reason="no candidate managers", n_candidates=0)
            continue
        if r.level == 1 or r.assistant:
            whys = [[]]
        weights = np.asarray(weights, dtype=float)
        best = int(np.argmax(weights))
        # phantom weight: an unreadable title in the same department could be the real manager
        # scaled by how likely a random person in the department is to sit in that layer.
        phantom = 0.0
        if not (r.level == 1 or r.assistant) and r.dept:
            dept_n = sum(len(v) for v in by_dept_level[r.dept].values()) or 1
            layer_frac = len(cands) / dept_n
            phantom = (unread.get(r.dept, 0) + 0.2 * unread.get(None, 0)) * layer_frac
        share = float(weights[best] / (weights.sum() + phantom))
        bc = cands[best]
        feat = dict(share_logit=_logit(share), pconf_logit=_logit(r.pconf), child_stale=float(r.stale),
                    cand_stale=float(bc.stale), cross_dept=float(cross),
                    spec_match=float(bool(r.spec) and bc.spec == r.spec),
                    loc_match=float(bool(r.loc) and bc.loc == r.loc),
                    loc_mismatch=float(bool(r.loc) and bool(bc.loc) and bc.loc != r.loc),
                    log_cands=float(np.log(len(cands))), phantom=float(phantom > 0),
                    exec_edge=float(r.level == 1 or r.assistant), child_ic=float(r.level == 5),
                    child_mgr=float(r.level == 4), child_head_of=float(r.head_of), cand_level_conf=bc.level_conf,
                    level_gap=float(r.level - (bc.level or 0)))
        raw = heuristic_conf(feat)
        reason_bits = [basis] + whys[best] + [f"{len(cands)} candidate(s), best share {share:.0%}"]
        if phantom:
            reason_bits.append("some titles nearby could not be read")
        if r.stale:
            reason_bits.append("record not updated for 18+ months")
        keep = [i for i in np.argsort(-weights) if weights[i] >= 0.25 * weights[best]][:12]
        plausible = [cands[i].pid for i in keep]
        mass_share = float(weights[keep].sum() / (weights.sum() + phantom))
        top = [(cands[i].pid, round(float(weights[i] / (weights.sum() + phantom)), 3)) for i in np.argsort(-weights)[:5]]
        out[r.pid] = dict(manager_id=bc.pid, raw_conf=raw, reason="; ".join(reason_bits), n_candidates=len(cands),
                          plausible=plausible, feat=feat, mass_feat=dict(feat, share_logit=_logit(mass_share)),
                          candidates=top)

    # ---- calibrate + abstain ------------------------------------------
    for pid, o in out.items():
        if model is not None and "feat" in o:
            o["confidence"] = float(model.predict(o["feat"]))
        else:
            o["confidence"] = o["raw_conf"]
        o["proposed_manager_id"] = o.get("manager_id")
        if not cfg.always_guess and o["confidence"] < cfg.threshold:
            o["manager_id"] = None
            o["status"] = "abstain" if o.get("proposed_manager_id") else "unresolved"
        else:
            o["status"] = "edge" if o.get("manager_id") else ("root" if o.get("is_root") else "unresolved")

    # ---- skip-level "rolls up to" for abstentions ----------------------
    # Processed top-down, so a manager's own roll-up can be reused by their reports.
    if cfg.use_rollup and not cfg.always_guess:
        level_of = {r.pid: (r.level if r.level is not None else 9) for r in live}

        def up(pid):
            o = out.get(pid)
            if not o:
                return None
            if o["status"] == "edge":
                return o["manager_id"], o["confidence"]
            if o["status"] == "rollup":
                return o["rollup_id"], o["rollup_conf"]
            return None

        def chain(pid, limit=8):
            seq, cur, conf = [(pid, 1.0)], pid, 1.0
            for _ in range(limit):
                nxt = up(cur)
                if not nxt:
                    break
                cur, c = nxt
                conf = min(conf, c)
                seq.append((cur, conf))
            return seq

        for pid in sorted(out, key=lambda k: level_of.get(k, 9)):
            o = out[pid]
            if o["status"] != "abstain" or not o.get("plausible") or len(o["plausible"]) < 2:
                continue
            chains = [chain(c) for c in o["plausible"]]
            common = set(x for x, _ in chains[0])
            for ch in chains[1:]:
                common &= set(x for x, _ in ch)
            lca = next((node for node, _ in chains[0] if node in common), None)
            if lca is None:
                continue
            path_conf = min(next(c for node, c in ch if node == lca) for ch in chains)
            # P(true manager is in the plausible set): same model, share = combined share of the set
            mf = o["mass_feat"]
            pin = float(model.predict(mf)) if model is not None else heuristic_conf(mf)
            rconf = path_conf * pin
            if rconf >= cfg.rollup_threshold:
                o["rollup_id"], o["rollup_conf"] = lca, rconf
                o["status"] = "rollup"
                o["reason"] += f"; direct manager unclear, but all {len(chains)} likely managers roll up to {lca}"

    rows = []
    for r in recs:
        if r.dup_of:
            src = out.get(r.dup_of, {})
            o = dict(src)
            o["reason"] = f"duplicate record of {r.dup_of}; " + src.get("reason", "")
            o["confidence"] = src.get("confidence", 0.0) * 0.97
            if o.get("status") == "edge" and o["confidence"] < cfg.threshold and not cfg.always_guess:
                o["status"], o["manager_id"] = "abstain", None
        else:
            o = out[r.pid]
        rows.append(dict(person_id=r.pid, manager_id=o.get("manager_id"), confidence=round(o.get("confidence", 0.0), 4),
                         raw_conf=round(o.get("raw_conf", 0.0), 4), status=o.get("status", "unresolved"),
                         proposed_manager_id=o.get("proposed_manager_id"), rollup_id=o.get("rollup_id"),
                         rollup_conf=round(o.get("rollup_conf", 0.0), 4), reason=o.get("reason", ""),
                         n_candidates=o.get("n_candidates", 0), candidates=o.get("candidates", []),
                         features=o.get("feat"), level=r.level, dept=r.dept, specialty=r.spec,
                         exec_role=r.role, is_stale_guess=r.stale, dup_of_record=r.dup_of, parse_conf=round(r.pconf, 3)))
    return pd.DataFrame(rows)


def infer_all(people: pd.DataFrame, cfg: Config | None = None, model=None) -> pd.DataFrame:
    ref = people["last_updated"].max()
    parts = [infer_company(g, cfg, ref, model) for _, g in people.groupby("company_id", sort=True)]
    res = pd.concat(parts, ignore_index=True)
    return res.merge(people[["person_id", "company_id"]], on="person_id", how="left")
