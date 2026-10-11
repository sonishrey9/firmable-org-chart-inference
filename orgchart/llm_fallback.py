"""Optional LLM fallback for titles the rules cannot read. OFF by default.

Contract (matches the "rules first, LLM only where rules can't reach" principle):
  * input: one raw title string the rule parser returned level=None for
  * output: a ParsedTitle-like dict {level, dept, specialty} or None
  * the LLM never sees other people, never proposes a manager, never overrides a rule
  * answers are cached by normalised title, so each unique title costs at most one call
  * any answer it gives is capped at confidence 0.6, so it rarely clears the edge threshold alone

No API key is needed to run this project; with ORGCHART_LLM unset this module does nothing.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

PROMPT = (
    "Classify this job title. Reply with JSON only: "
    '{"level": 0-5 (0 CEO, 1 C-level, 2 VP, 3 Director/Head, 4 people manager, 5 individual contributor) or null, '
    '"dept": one of Engineering, Data, Product, Design, Sales, Marketing, Customer Success, Finance, People, '
    'Legal, Operations, IT, Security, or null}. Title: '
)


def enabled() -> bool:
    return os.environ.get("ORGCHART_LLM", "").lower() in {"1", "true", "on"}


@lru_cache(maxsize=10_000)
def classify(title: str) -> dict | None:
    if not enabled():
        return None
    client = _client()
    if client is None:
        return None
    try:
        raw = client(PROMPT + title)
        d = json.loads(raw)
        if d.get("level") is None:
            return None
        return {"level": int(d["level"]), "dept": d.get("dept"), "specialty": None, "conf": 0.6}
    except Exception:
        return None


def _client():
    """Plug in a provider here (kept empty on purpose: no keys in the repo, no paid calls by default)."""
    return None
