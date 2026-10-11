# Build log

How this was built, in order. Times are IST. The spec came first and coding agents implemented it in small, reviewed steps.

| When (IST) | Step | Notes |
|---|---|---|
| Sun 11 Oct, 11:59 PM | Read the task, wrote `docs/SPEC.md` | Non-negotiables: truth first then mess, deterministic edges, calibrated confidence, abstain by default, numbers only from runs |
| Mon 12 Oct, 12:00 AM | Reuse research | GitHub and web search for org-chart inference, title parsers and seniority classifiers. Nothing does title-only org-chart inference; some candidates were too heavy, GPL or unlicensed. Reused libraries only (see `THIRD_PARTY_NOTICES.md`). Found no existing Firmable submissions and copied none |
| 12:05 AM | Generator v1 | True tree per company (CEO, then execs, VPs, directors, managers, ICs) shaped by industry and size, then a noise model. 520 companies, about 203k records |
| 12:08 AM | Title parser v1 | Its own vocabulary, independent of the generator. Handles "manager" titles that are ICs (Product Manager, Account Manager), "Solutions Engineer" sitting in Sales, and the CPO ambiguity |
| 12:12 AM | Inference v1 and first error analysis | Naive "always guess" precision was 48%. The high-confidence errors showed `EM - Backend` parsed as an IC and "X Manager Lead" seniors parsed as managers. Fixed the parser and changed the generator's ambiguous CS manager title |
| 12:15 AM | Phantom candidates | Unreadable titles in a department might be the real manager, so they now take a share of the confidence. Scaled by layer size after the first version over-penalised everyone |
| 12:20 AM | Calibration and threshold on train, metrics on held-out test | Isotonic calibration is close to the diagonal. Threshold chosen for 95% train precision |
| 12:22 AM | Roll-ups | When the direct manager is ambiguous but all plausible managers share an ancestor, publish "rolls up to". Processed top-down so roll-ups chain |
| 12:24 AM | Tried a logistic regression over 16 features | Lower coverage at 95% precision than the 3-factor heuristic, so it was rejected and kept as an ablation |
| 12:28 AM | UI stack switched to FastAPI plus a static SPA (Cytoscape and Chart.js), with Render free hosting | Per-company gzip JSON loaded lazily, `/health`, a waking-up loader |
| 12:35 AM | Tests, ablations, write-up | `pytest -q`; README numbers pasted from `reports/metrics.json` |

<!-- SHREY: add your own entries here, e.g. what you reviewed or changed by hand, and your Kiwi Control checkpoints. -->
