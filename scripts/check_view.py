"""Browser check for the chart's initial view (needs `pip install playwright` and a Chrome/Chromium).

For each viewport width, opens the default company, the largest company and an uploaded CSV, then
asks the page which visible level 0-3 nodes (CEO, execs, VPs, directors) are not fully inside the canvas.
PASS when either everything fits ("fit" mode), or the tree is too wide to fit at a readable zoom and the
view is left-aligned with the leftmost leader fully on screen ("left-aligned" mode).

    python scripts/check_view.py [--url http://localhost:8765] [--chrome /usr/bin/google-chrome]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = [(1280, 800), (1440, 900), (1920, 1080), (375, 812)]


def verdict(r: dict) -> bool:
    if r["mode"] == "fit":
        return not r["outside"]
    return r["mode"] == "left-aligned" and 0 <= r["leftmostX"] <= 60 and r["labelPx"] >= 10


async def main(url: str, chrome: str | None) -> int:
    index = json.loads((ROOT / "data/app/index.json").read_text())
    largest = max(index, key=lambda c: c["people"])
    ok_all = True
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else await p.chromium.launch()
        for w, h in WIDTHS:
            ctx = await b.new_context(viewport={"width": w, "height": h})
            pg = await ctx.new_page()
            await pg.goto(url + "/", wait_until="networkidle")
            await pg.wait_for_function("window.orgchart && window.orgchart.cy && window.orgchart.payload")
            runs = [("default", await pg.evaluate("window.orgchart.payload.company.company_name"))]
            reports = [await pg.evaluate("window.orgchart.viewReport()")]
            await pg.goto(f"{url}/#explore/{largest['company_id']}")
            await pg.wait_for_function(f"window.orgchart.payload.company.company_id === '{largest['company_id']}'")
            await pg.wait_for_timeout(300)
            runs.append(("largest", largest["company_name"]))
            reports.append(await pg.evaluate("window.orgchart.viewReport()"))
            await pg.goto(url + "/#upload")
            await pg.set_input_files("#file", str(ROOT / "data/sample_upload.csv"))
            await pg.click("#run-upload")
            await pg.wait_for_function("window.orgchart.payload.company.company_id === 'UPLOAD'")
            await pg.wait_for_timeout(300)
            runs.append(("upload", "sample_upload.csv"))
            reports.append(await pg.evaluate("window.orgchart.viewReport()"))
            for (kind, name), r in zip(runs, reports):
                ok = verdict(r)
                ok_all &= ok
                print(f"{w:>5}px  {kind:<8} {name:<18} {'PASS' if ok else 'FAIL'}  mode={r['mode']:<12} zoom={r['zoom']:<5} "
                      f"label={r['labelPx']}px leaders={r['leaders']} outside={len(r['outside'])} leftmostX={r['leftmostX']}")
            await ctx.close()
        await b.close()
    return 0 if ok_all else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8765")
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.url, a.chrome)))
