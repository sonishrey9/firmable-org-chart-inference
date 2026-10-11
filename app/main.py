"""FastAPI backend + static single-page frontend for the org chart inference demo.

Memory budget (Render free, 512 MB): nothing heavy is computed at boot. The company index is a
small JSON file; each company's precomputed chart is a ~25 KB gzipped JSON loaded on demand and
kept in a small LRU cache. Inference code is imported only when someone uploads a CSV.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
APP_DATA = ROOT / "data" / "app"
REPORTS = ROOT / "reports"
STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_ROWS = 3000

app = FastAPI(title="Org Chart Inference", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


@lru_cache(maxsize=1)
def _index() -> list[dict]:
    return json.loads((APP_DATA / "index.json").read_text())


@lru_cache(maxsize=1)
def _metrics() -> dict:
    return json.loads((REPORTS / "metrics.json").read_text())


@lru_cache(maxsize=24)
def _company(cid: str) -> dict:
    path = APP_DATA / "companies" / f"{cid}.json.gz"
    if not path.is_file():
        raise KeyError(cid)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


@app.get("/health")
def health():
    return {"status": "ok", "companies": len(_index())}


@app.get("/api/companies")
def companies(q: str = "", industry: str = "", size: str = "", noise: str = "", split: str = "",
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    items = _index()
    ql = q.strip().lower()
    if ql:
        items = [c for c in items if ql in c["company_name"].lower() or ql in c["company_id"].lower()]
    for key, val in (("industry", industry), ("size_bucket", size), ("noise_level", noise), ("split", split)):
        if val:
            items = [c for c in items if c[key] == val]
    total = len(items)
    start = (page - 1) * page_size
    facets = {k: sorted({c[k] for c in _index()}) for k in ("industry", "size_bucket", "noise_level")}
    return {"total": total, "page": page, "page_size": page_size, "items": items[start:start + page_size],
            "facets": facets}


@app.get("/api/company/{cid}")
def company(cid: str):
    try:
        return _company(cid)
    except KeyError:
        raise HTTPException(404, f"Company {cid} not found")


def _rows_for_export(payload: dict, threshold: float) -> list[dict]:
    names = {n["id"]: n["name"] for n in payload["nodes"]}
    rows = []
    for n in payload["nodes"]:
        edge = n["manager_id"] if (n["manager_id"] and n["confidence"] >= threshold and n["status"] != "root") else None
        roll = n["rollup_id"] if (not edge and n.get("rollup_id")) else None
        rows.append(dict(person_id=n["id"], name=n["name"], title=n["title"] or "", level=n["level_name"] or "",
                         department=n["dept"] or "", manager_id=edge or "", manager_name=names.get(edge, ""),
                         confidence=n["confidence"] if edge else "", rolls_up_to=roll or "",
                         rolls_up_to_name=names.get(roll, ""), status="edge" if edge else ("rollup" if roll else n["status"] if n["status"] == "root" else "no edge"),
                         reason=n["reason"]))
    return rows


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


@app.get("/api/company/{cid}/export.csv")
def export(cid: str, threshold: float | None = None):
    payload = company(cid)
    t = payload["threshold"] if threshold is None else threshold
    return Response(_csv(_rows_for_export(payload, t)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{cid}_org_chart.csv"'})


@app.get("/api/metrics")
def metrics():
    m = dict(_metrics())
    m.pop("curves", None)
    m.pop("calibration_model", None)
    return m


@app.get("/api/calibration")
def calibration():
    return _metrics()["curves"]


@app.get("/api/sample.csv")
def sample_csv():
    return FileResponse(ROOT / "data" / "sample_upload.csv", media_type="text/csv", filename="sample_upload.csv")


@app.post("/api/infer")
async def infer(file: UploadFile = File(...), format: str = "json"):
    """Run the shipped pipeline on an uploaded CSV: columns full_name,title[,department,location,last_updated,person_id]."""
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "File is larger than 2 MB. Upload one company at a time.")
    import pandas as pd  # lazy: keep boot memory small
    from orgchart.calibrate import CalibratedHeuristic
    from orgchart.infer import Config, infer_company
    from orgchart.titles import LEVEL_NAMES
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except Exception:
        raise HTTPException(400, "Could not read that file as CSV.")
    df.columns = [c.strip().lower() for c in df.columns]
    if "title" not in df.columns:
        raise HTTPException(400, "The CSV needs at least a 'title' column (and ideally 'full_name').")
    if len(df) > MAX_UPLOAD_ROWS:
        raise HTTPException(413, f"Up to {MAX_UPLOAD_ROWS} rows per upload, this file has {len(df)}.")
    if "full_name" not in df.columns:
        df["full_name"] = df.get("name", [f"Person {i + 1}" for i in range(len(df))])
    if "person_id" not in df.columns:
        df["person_id"] = [f"U{i + 1:05d}" for i in range(len(df))]
    for col in ("department", "location"):
        if col not in df.columns:
            df[col] = None
    df = df.replace({"": None})
    df["company_id"] = "UPLOAD"
    df["last_updated"] = pd.to_datetime(df["last_updated"], errors="coerce") if "last_updated" in df.columns else pd.NaT
    m = _metrics()
    model = CalibratedHeuristic.from_json((REPORTS / "confidence_model.json").read_text())
    thr, rthr = m["operating_point"]["threshold"], m["operating_point"]["rollup_threshold"]
    ref = df["last_updated"].max() if df["last_updated"].notna().any() else pd.Timestamp.today()
    out = infer_company(df, Config(threshold=thr, rollup_threshold=rthr), ref, model).set_index("person_id")
    nodes = []
    for r in df.itertuples(index=False):
        o = out.loc[r.person_id]
        lvl = None if pd.isna(o.level) else int(o.level)
        nodes.append(dict(id=r.person_id, name=r.full_name, title=r.title, department=r.department, location=r.location,
                          updated=None, level=lvl, level_name=LEVEL_NAMES.get(lvl) if lvl is not None else None,
                          dept=o.dept if isinstance(o.dept, str) else None,
                          specialty=o.specialty if isinstance(o.specialty, str) else None, status=o.status,
                          manager_id=o.proposed_manager_id if isinstance(o.proposed_manager_id, str) else None,
                          confidence=round(float(o.confidence), 3),
                          rollup_id=o.rollup_id if isinstance(o.rollup_id, str) else None,
                          rollup_conf=round(float(o.rollup_conf), 3), reason=o.reason,
                          candidates=list(o.candidates) if isinstance(o.candidates, list) else [],
                          stale=bool(o.is_stale_guess),
                          duplicate_of=o.dup_of_record if isinstance(o.dup_of_record, str) else None,
                          true_manager_id=None, proposed_correct=None))
    payload = dict(company=dict(company_id="UPLOAD", company_name=file.filename or "Uploaded file", industry="Upload",
                                n_employees=len(df), size_bucket="", noise_level="", split="upload"),
                   threshold=thr, rollup_threshold=rthr, nodes=nodes)
    if format == "csv":
        return PlainTextResponse(_csv(_rows_for_export(payload, thr)), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="inferred_org_chart.csv"'})
    return JSONResponse(payload)


@app.get("/")
def index_page():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
