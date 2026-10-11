"""Confidence model: a tiny logistic regression over the rule features, then isotonic calibration.

Both are a few lines of numpy, so there is no sklearn dependency and the fitted model is a small JSON file.
"""
from __future__ import annotations

import json
import numpy as np


class Isotonic:
    def __init__(self, xs=None, ys=None):
        self.xs = np.asarray(xs if xs is not None else [0.0, 1.0], float)
        self.ys = np.asarray(ys if ys is not None else [0.0, 1.0], float)

    @classmethod
    def fit(cls, raw: np.ndarray, correct: np.ndarray, n_bins: int = 40) -> "Isotonic":
        raw, correct = np.asarray(raw, float), np.asarray(correct, float)
        order = np.argsort(raw)
        raw, correct = raw[order], correct[order]
        # bin by quantile first so each block has enough support
        edges = np.unique(np.quantile(raw, np.linspace(0, 1, n_bins + 1)))
        idx = np.clip(np.searchsorted(edges, raw, side="right") - 1, 0, len(edges) - 2)
        blocks = []  # [x_mean, y_mean, weight]
        for b in range(len(edges) - 1):
            m = idx == b
            if m.any():
                blocks.append([raw[m].mean(), correct[m].mean(), m.sum()])
        # PAV
        i = 0
        while i < len(blocks) - 1:
            if blocks[i][1] > blocks[i + 1][1]:
                a, b = blocks[i], blocks[i + 1]
                w = a[2] + b[2]
                blocks[i] = [(a[0] * a[2] + b[0] * b[2]) / w, (a[1] * a[2] + b[1] * b[2]) / w, w]
                del blocks[i + 1]
                i = max(i - 1, 0)
            else:
                i += 1
        xs = [0.0] + [b[0] for b in blocks] + [1.0]
        ys = [blocks[0][1]] + [b[1] for b in blocks] + [blocks[-1][1]]
        return cls(xs, ys)

    def __call__(self, x):
        return np.interp(x, self.xs, self.ys)

    def to_json(self) -> str:
        return json.dumps({"xs": list(map(float, self.xs)), "ys": list(map(float, self.ys))})

    @classmethod
    def from_json(cls, s: str) -> "Isotonic":
        d = json.loads(s)
        return cls(d["xs"], d["ys"])


def heuristic_conf(f: dict) -> float:
    """Raw confidence: best candidate's share x sqrt(title quality) x stale penalty."""
    share = 1 / (1 + np.exp(-f["share_logit"]))
    pconf = 1 / (1 + np.exp(-f["pconf_logit"]))
    return float(share * np.sqrt(pconf) * (0.45 if f["child_stale"] else 1.0))


class CalibratedHeuristic:
    """The shipped confidence model: heuristic_conf, then isotonic calibration fitted on train companies."""
    kind = "heuristic+isotonic"

    def __init__(self, iso: Isotonic):
        self.iso = iso

    @classmethod
    def fit(cls, feats: list[dict], y) -> "CalibratedHeuristic":
        return cls(Isotonic.fit(np.array([heuristic_conf(f) for f in feats]), np.asarray(y, float)))

    def predict(self, f: dict) -> float:
        return float(self.iso(heuristic_conf(f)))

    def predict_many(self, feats: list[dict]) -> np.ndarray:
        return self.iso(np.array([heuristic_conf(f) for f in feats]))

    def to_json(self) -> str:
        return json.dumps({"kind": self.kind, "iso": json.loads(self.iso.to_json())})

    @classmethod
    def from_json(cls, s: str) -> "CalibratedHeuristic":
        d = json.loads(s)
        return cls(Isotonic(d["iso"]["xs"], d["iso"]["ys"]))


class ConfidenceModel:
    """Ablation: P(edge is correct | 16 rule features) via logistic regression (L2, Newton) + isotonic.

    Tried and rejected: it fits log-loss over all edges, and ranked the high-precision head worse than
    the 3-factor heuristic. See README "Decisions".
    """
    kind = "logistic+isotonic"

    def __init__(self, features: list[str], weights=None, iso: Isotonic | None = None):
        self.features = features
        self.w = np.asarray(weights if weights is not None else np.zeros(len(features) + 1), float)
        self.iso = iso

    def _x(self, feats: list[dict]) -> np.ndarray:
        X = np.array([[f[k] for k in self.features] for f in feats], float)
        return np.hstack([np.ones((len(X), 1)), X])

    def _lr(self, X):
        return 1 / (1 + np.exp(-np.clip(X @ self.w, -30, 30)))

    @classmethod
    def fit(cls, features: list[str], feats: list[dict], y, l2: float = 1.0, iters: int = 25) -> "ConfidenceModel":
        m = cls(features)
        X, y = m._x(feats), np.asarray(y, float)
        for _ in range(iters):
            p = m._lr(X)
            g = X.T @ (p - y) + l2 * np.r_[0, m.w[1:]]
            H = (X * (p * (1 - p))[:, None]).T @ X + l2 * np.diag(np.r_[0, np.ones(len(features))])
            m.w -= np.linalg.solve(H, g)
        m.iso = Isotonic.fit(m._lr(X), y)
        return m

    def predict(self, f: dict) -> float:
        p = float(self._lr(self._x([f]))[0])
        return float(self.iso(p)) if self.iso else p

    def predict_many(self, feats: list[dict]) -> np.ndarray:
        p = self._lr(self._x(feats))
        return self.iso(p) if self.iso else p

    def coefficients(self) -> dict:
        return {"intercept": float(self.w[0]), **{k: float(v) for k, v in zip(self.features, self.w[1:])}}

    def to_json(self) -> str:
        return json.dumps({"features": self.features, "weights": list(map(float, self.w)),
                           "iso": json.loads(self.iso.to_json()) if self.iso else None}, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "ConfidenceModel":
        d = json.loads(s)
        iso = Isotonic(d["iso"]["xs"], d["iso"]["ys"]) if d.get("iso") else None
        return cls(d["features"], d["weights"], iso)
