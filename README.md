# VSR Scaffold Planner & Simulator — MVP (2D sections)

A planning and comparison tool for VARD Shipyards Romania. It does five things:
1. Imports frame-section drawings (DWG via ODA → DXF, or vector PDF).
2. Defines areas on them.
3. Lays out and simulates the erection of **Layher Allround LW** and **Marcegaglia SM8** on each area.
4. Compares the two systems on productivity, material, safety and cost.
5. Recommends a system per area, with the reasons, the sensitivity and a vessel-level summary.

> **Planning and comparison aid only.** It is not a structural design or certification tool. Every scaffold must be designed and approved per the manufacturer's approval (Layher DIBt, SM8 ministerial authorisation), EN 12810 / EN 12811 and Romanian OSH rules, and inspected by a competent person.

## Quick start
```bash
./scripts/setup.sh          # venv + dependencies + sample + tests
./scripts/run.sh            # http://localhost:8000  (sample project B12 is seeded on first start)
```
Manual equivalent:
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python samples/generate_sample_block.py          # DXF + PDF + project.json (already committed)
python -m pytest -q                              # validation tests 1-8
PYTHONPATH=backend uvicorn vsr.api.app:app --port 8000
```
**Online on Azure:** see [`docs/DEPLOYMENT_AZURE.md`](docs/DEPLOYMENT_AZURE.md) (App Service, Microsoft login, auto-deploy from GitHub).

DWG import needs the [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) on the server: `export ODA_FILE_CONVERTER=/path/to/ODAFileConverter`.

## What's in the MVP
| Area | Status |
|---|---|
| DXF import (ezdxf): layer-mapping wizard, saved templates, splines/bulges/blocks, CL/BL view registration, frame-number detection, scale/dimension check | ✅ |
| DWG → DXF via ODA File Converter (no LibreDWG) | ✅ wrapper, needs ODA installed |
| Vector PDF (PyMuPDF): style mapping, click calibration + verification, frame per view when text is outlined | ✅ |
| Manual section editor (confidence low) | ✅ |
| Layout engine: exact longitudinal DP, exact transverse search (stepped lines, brackets), infills, inboard faces, obstructions avoid/flag | ✅ |
| BoM per area/system with `verified`/`estimate` status on every line | ✅ |
| Erection simulation (lift by lift, advance guardrail), safety indicators, cost | ✅ |
| Transparent scoring, reasons, sensitivity, re-scoring with custom weights | ✅ |
| Vessel summary: 100 % A / 100 % B / mixed optimum incl. complexity cost | ✅ |
| Side-by-side animated section + elevation views with live counters | ✅ (2D SVG) |
| Excel (run and vessel), trace CSV, print-ready management report | ✅ |
| Versioned catalogues / time standards / settings (sha256 stamped in every run) | ✅ |
| Navisworks FBX import, 3D view, scanned-PDF tracing | Phase 2 |
| Annex A calibration fitting, PDF report generator | Phase 3 (HTML report prints to PDF today) |
| SimPy multi-crew, schedule-based peak tonnage, rent vs buy | Phase 4 |

## Validation tests (`python -m pytest -q`)
| # | Test | Result |
|---|---|---|
| 1 | Reference tower BoM = hand count (both systems); SM8 weight = catalogue sum within 1 % | ✅ exact |
| 2 | Reference tower reproduces 76 / 52 min with 5 fitters within 2 % | ✅ (calibration point; see note §7) |
| 3 | Flat shell, run = multiple of the grid → no infills (all bay lengths, bounded/free ends) | ✅ |
| 4 | Bow: counts reported and stable between runs; coarser grid → more infills on curved section and in aggregate | ✅ — **plus one strict xfail on the strong-flare bow (finding, see note §8)** |
| 5 | Third system via a new catalogue file, no code change | ✅ |
| 6 | Traceability: every metric has formula + inputs; BoM lines → catalogue entries; steps → time-standard values | ✅ |
| 7 | DXF vs its PDF export: hull within ±20 mm (measured ≤ 6 mm), same bays per lift, same widths and infill count | ✅ (Navisworks leg: phase 2, skipped) |
| 8 | Obstructions: avoided or flagged as error, never ignored | ✅ 2D (Navisworks zones: phase 2, skipped) |

## Repository layout
```
backend/vsr/
  catalogue.py         versioned YAML loaders (catalogues, time standards, settings) + validation
  models.py            Section, Area, Obstruction, Project
  reference.py         VSR reference tower (Rev02 slide 7)
  geometry/            hull queries, DXF/DWG import, PDF import, layer heuristics
  engine/              layout, bom, simulate, run (metrics + trace), compare, fleet
  export/excel.py      run & vessel workbooks, trace CSV
  api/app.py           FastAPI (serves the frontend too)
  store.py             SQLite document store (Postgres-ready documents)
data/                  catalogues/, time_standards/, common/tube_and_coupler.yaml, settings.yaml
frontend/              index.html, app.js, style.css, report.html  (no build step)
samples/               generate_sample_block.py, block_B12/ (DXF, PDF, project.json)
scripts/               setup.sh, run.sh, derive_provisional_standards.py
tests/                 validation (1-8) + unit/API tests
docs/TECHNICAL_NOTE.md data model, algorithm, adding a system, calibration, findings, open questions
```

## Changes to the suggested stack (and why)
- **Frontend: static ES-module SPA + SVG, no React/three.js in the MVP.** The MVP is 2D. A no-build frontend installs on-premises without a Node toolchain and keeps the review surface small. React + react-three-fiber come in with the 3D phase (Navisworks), where they pay off.
- **Optimisation: exact DP / breakpoint enumeration instead of OR-Tools.** The per-area search space is small. An exact method is deterministic (test 4 stability) and needs one dependency fewer. OR-Tools stays an option for 3D plan-curvature layouts.
- **Storage: SQLite JSON documents instead of PostgreSQL.** The documents map 1:1 to Postgres JSONB tables, and only `store.py` changes. This keeps the pilot to a single process.
- **Auth: role header (planner / ie / hse / viewer) in the MVP.** OIDC is intended to terminate at the company reverse proxy.
- **SimPy** is not used yet: single-crew sequencing is deterministic. Multi-crew is phase 4.

## Data status, read before using numbers
- **Layher weights are all `estimate`** placeholders until the current Layher price list is loaded. Every report shows the estimate share.
- SM8 standards, ledgers, diagonals, decks, toe boards and brackets are `verified` from the brief. Base jack, tie and end toe boards are estimates.
- Time standards are **provisional**, derived from one trial point (`scripts/derive_provisional_standards.py`).
- Costs (purchase €/t, labour, transport) are placeholders in `data/settings.yaml`. Rental uses the VSR benchmark midpoint (160 €/t/month).
