"""Browser check for the chart's initial view (needs `pip install playwright` and a Chrome/Chromium).

For each viewport width, opens the default company (Aurora Works), the largest company and an uploaded
CSV. Strict check on the initial view: every visible node (CEO, execs, VPs and the "+N" fold chips) is
fully inside the canvas, the smallest rendered label is >= 10px, and the CEO is on screen.
It then opens the first fold chip and checks the zoom did not change and the chip's parent is still on screen.

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
    return not r["outside"] and r["labelPx"] >= 10 and r["ceoOnScreen"]


EXPAND = """async () => {
  const S = window.orgchart, cy = S.cy;
  const chip = cy.nodes('.fold').filter((n) => n.data('fold') !== '__orphans').first();
  if (!chip.length) return null;
  const parent = chip.data('fold'), z0 = cy.zoom(), before = cy.nodes(':visible').length;
  chip.emit('tap');
  await new Promise((r) => setTimeout(r, 450));
  const b = cy.getElementById(parent).renderedBoundingBox();
  return { zoomKept: Math.abs(cy.zoom() - z0) < 1e-6, parentOnScreen: b.x1 >= 0 && b.x2 <= cy.width() && b.y1 >= 0 && b.y2 <= cy.height(),
           grew: cy.nodes(':visible').length > before };
}"""


async def main(url: str, chrome: str | None) -> int:
    index = json.loads((ROOT / "data/app/index.json").read_text())
    largest = max(index, key=lambda c: c["people"])
    default = next(c for c in index if c["company_name"] == "Aurora Works")
    ok_all = True
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else await p.chromium.launch()
        for w, h in WIDTHS:
            ctx = await b.new_context(viewport={"width": w, "height": h})
            pg = await ctx.new_page()
            await pg.goto(url + "/", wait_until="networkidle")
            await pg.wait_for_function("window.orgchart && window.orgchart.cy && window.orgchart.payload")
            await pg.goto(f"{url}/#explore/{default['company_id']}")
            await pg.wait_for_function(f"window.orgchart.payload.company.company_id === '{default['company_id']}'")
            await pg.wait_for_timeout(300)
            runs = [("default", default["company_name"])]
            reports = [await pg.evaluate("window.orgchart.viewReport()")]
            reports[0]["expand"] = await pg.evaluate(EXPAND)
            await pg.goto(f"{url}/#explore/{largest['company_id']}")
            await pg.wait_for_function(f"window.orgchart.payload.company.company_id === '{largest['company_id']}'")
            await pg.wait_for_timeout(300)
            runs.append(("largest", largest["company_name"]))
            reports.append(await pg.evaluate("window.orgchart.viewReport()"))
            reports[-1]["expand"] = await pg.evaluate(EXPAND)
            await pg.goto(url + "/#upload")
            await pg.set_input_files("#file", str(ROOT / "data/sample_upload.csv"))
            await pg.click("#run-upload")
            await pg.wait_for_function("window.orgchart.payload.company.company_id === 'UPLOAD'")
            await pg.wait_for_timeout(300)
            runs.append(("upload", "sample_upload.csv"))
            reports.append(await pg.evaluate("window.orgchart.viewReport()"))
            reports[-1]["expand"] = await pg.evaluate(EXPAND)
            for (kind, name), r in zip(runs, reports):
                ok = verdict(r)
                ex = r["expand"]
                ex_ok = ex is None or (ex["zoomKept"] and ex["parentOnScreen"] and ex["grew"])
                ok_all &= ok and ex_ok
                print(f"{w:>5}px  {kind:<8} {name:<18} {'PASS' if ok else 'FAIL'}  fold={r['foldLevel']} mode={r['mode']:<11} zoom={r['zoom']:<5} "
                      f"label={r['labelPx']}px visible={r['visible']} chips={r['chips']} outside={len(r['outside'])} ceo={r['ceoOnScreen']}"
                      f"  | expand {'n/a' if ex is None else ('PASS' if ex_ok else 'FAIL ' + str(ex))}")
            await ctx.close()
        await b.close()
    return 0 if ok_all else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8765")
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.url, a.chrome)))
