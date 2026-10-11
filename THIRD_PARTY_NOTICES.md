# Third-party notices

This project uses the following open-source components as **libraries** (installed via pip or loaded from a CDN). No third-party source code is copied into this repository.

| Component | Used for | Licence |
|---|---|---|
| [Faker](https://github.com/joke2k/faker) | Realistic, locale-aware names in the synthetic data | MIT |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | Typo repair in title tokens, near-duplicate detection | MIT |
| [pandas](https://github.com/pandas-dev/pandas) | Data frames | BSD-3-Clause |
| [NumPy](https://github.com/numpy/numpy) | Numerics, calibration | BSD-3-Clause |
| [PyArrow](https://github.com/apache/arrow) | Parquet files | Apache-2.0 |
| [FastAPI](https://github.com/fastapi/fastapi) | JSON API and static file server | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI server | BSD-3-Clause |
| [python-multipart](https://github.com/Kludex/python-multipart) | CSV upload parsing | Apache-2.0 |
| [pytest](https://github.com/pytest-dev/pytest) | Tests (dev only) | MIT |
| [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) | Interactive graph rendering (CDN) | MIT |
| [dagre](https://github.com/dagrejs/dagre) and [cytoscape-dagre](https://github.com/cytoscape/cytoscape.js-dagre) | Hierarchical tree layout (CDN) | MIT |
| [Chart.js](https://github.com/chartjs/Chart.js) | Metrics charts (CDN) | MIT |
| [Tailwind CSS Play CDN](https://tailwindcss.com) | Utility classes (CDN) | MIT |
| Instrument Sans, IBM Plex Mono (Google Fonts) | Typography | SIL Open Font License 1.1 |

The full licence texts ship with each package. All are permissive (MIT, BSD, Apache-2.0 or OFL) and compatible with any licence chosen for this repository.

## Looked at, not used

| Project | Why not |
|---|---|
| `find-job-titles` (MIT) | Finds title spans inside free text. Our input is already a title, so it adds nothing. |
| `arjun10g/na-tech-jobs-seniority-v1` (MIT, Hugging Face) | Needs sentence-transformers, which is too heavy for a 512 MB free instance. It also covers seniority only, not function. |
| `dlapushin/job_title_ner` (MIT) | Naive Bayes level and function tagger. Its training data depends on a separate academic dataset with its own terms. |
| JobBERT evaluation dataset | Licence not stated, so it can't be redistributed. |
| `skydockAI/org_chart_helper` | GPL-3.0, and it needs an existing reporting-line file. |
| O*NET occupation taxonomy (CC BY 4.0) | Maps occupations, not seniority or reporting lines. It could later help with department mapping. |
| dabeng/OrgChart, bumbeishvili/org-chart (MIT) | Good JS org chart widgets, but Cytoscape plus dagre handles abstained or unplaced nodes and confidence-styled edges more flexibly. |
