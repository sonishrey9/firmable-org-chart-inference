from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "app" / "index.json").exists(),
                                reason="run scripts/run_eval.py and scripts/build_app_data.py first")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_companies_search_and_pagination(client):
    r = client.get("/api/companies", params={"page_size": 5})
    d = r.json()
    assert d["total"] >= 500 and len(d["items"]) == 5
    name = d["items"][0]["company_name"].split()[0]
    assert all(name.lower() in c["company_name"].lower() for c in client.get("/api/companies", params={"q": name}).json()["items"])


def test_company_payload(client):
    cid = client.get("/api/companies", params={"page_size": 1}).json()["items"][0]["company_id"]
    d = client.get(f"/api/company/{cid}").json()
    assert d["nodes"] and 0 < d["threshold"] < 1
    n = d["nodes"][0]
    for k in ("id", "title", "status", "confidence", "manager_id", "candidates", "reason"):
        assert k in n
    assert client.get("/api/company/NOPE").status_code == 404
    csv = client.get(f"/api/company/{cid}/export.csv").text
    assert csv.startswith("person_id,")


def test_metrics_and_calibration(client):
    m = client.get("/api/metrics").json()
    assert m["test"]["precision"] > 0.9
    c = client.get("/api/calibration").json()
    assert c["precision_coverage"] and c["reliability"]


def test_upload_infer(client):
    sample = (ROOT / "data" / "sample_upload.csv").read_bytes()
    r = client.post("/api/infer", files={"file": ("s.csv", sample, "text/csv")})
    assert r.status_code == 200
    d = r.json()
    assert len(d["nodes"]) > 100
    assert any(n["status"] == "edge" for n in d["nodes"])
    bad = client.post("/api/infer", files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert bad.status_code == 400


def test_upload_header_only_is_400(client):
    r = client.post("/api/infer", files={"file": ("h.csv", b"full_name,title,department\n", "text/csv")})
    assert r.status_code == 400
    assert "No rows found" in r.json()["detail"]


def test_gzip_enabled(client):
    r = client.get("/api/companies", params={"page_size": 50}, headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
