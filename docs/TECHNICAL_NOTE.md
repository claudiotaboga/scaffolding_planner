# VSR Scaffold Planner — Technical note (MVP, 2D sections)

## 1. Problem in 10 lines
1. VSR must pick a standard modular scaffold family (Layher Allround LW vs Marcegaglia SM8), or justify keeping both and say where each one is used.
2. The choice depends on geometry. Each system's bay/width/bracket grid fits hull curvature and flare differently, and every mismatch costs a tube-and-coupler infill (slow, unsafe, expensive).
3. The engine reduces any geometry source to a per-lift requirement: run length along the ship, and deck-edge-to-hull gap.
4. It fits each system's discrete grid to that requirement exactly, then derives BoM → erection time → cost and safety → a transparent score.
5. Geometry sources (DWG via ODA → DXF, vector PDF, later Navisworks) feed one ship coordinate system and carry a confidence flag.
6. Catalogues, time standards and settings are versioned YAML with sha256. A third system is a new file, not new code.
7. Time standards are provisional. They are anchored on a single trial point (Rev02: 76 / 52 min, 5 fitters).
8. Every number is traceable: metric → formula → inputs (area field, catalogue entry and status, time-standard version, setting).
9. Rules are flagged, never silently fixed. The tool is a planning aid, not structural design.
10. MVP scope is one section at a time, prismatic over a frame range. 3D, calibration fitting, multi-crew and fleet scheduling come later.

## 2. Data model
```
Project ─┬─ Drawing (file, kind dxf|dwg|pdf, layer/style mapping, template, scale report)
         ├─ Section (id, frame, x, points[(y,z)], source, source_file, confidence, notes)
         ├─ obstructions_by_frame {frame: [Obstruction(name, polygon (y,z))]}
         └─ Area (section_id, frame range | run length, side, face outboard|inboard, run ends free|bounded,
                  z_base, z_top, n_lifts, working_levels, clearance_target, gap_min, max_gap,
                  load_class, anchorage, protection, advance_guardrail, obstructions, rental_months, tower_*)
Run (immutable; run_id = hash of snapshot)
  snapshot: area + geometry hash/source/confidence + catalogue & time-standard versions/sha + settings sha + crew
  results[system]: layout (bays, widths, line positions & tops, per-lift plan, infills, violations, explanation)
                   bom[code, qty, unit kg, status, source, catalogue version]
                   simulation (ordered steps with man-seconds from the time standard, cumulative crew-h / elapsed)
                   metrics {name: {value, unit, formula, inputs}}
  comparison: table (raw / normalised / weighted per criterion), totals, recommended, margin, reasons, sensitivity
Catalogue YAML: system_id, version, node, lift, bay_lengths, bay_widths, rules{value,status,source}, hatch, components[]
TimeStandard YAML: system_id, version, status, actions{man-seconds}, infill crew-h/unit, dismantle factor, crew efficiency
```
Storage: SQLite JSON documents in the MVP (`var/vsr.sqlite`). They map 1:1 to PostgreSQL JSONB tables (projects, drawings, runs, mappings).

## 3. Layout algorithm
Coordinates: Y outboard positive (half-breadth), Z from baseline. `face: inboard` (tanks, engine room) mirrors the section so the same engine applies.

**Lifts.** Decks at `z_base + 2k`, k = 1..n. The default n puts the top deck at or above `z_top − 2.0` m (reach).

**Longitudinal (along X): exact DP at 1 cm.**
```
both ends bounded: Σbays ∈ [L − tol, L]; otherwise Σbays ∈ [L − tol, L + overhang]
objective: fewest bays, then |Σ − L|
window empty & bounded → longest Σ ≤ L, longitudinal infill on every lift (residual > tol)
```
Posts are continuous standards, so the same bay sequence applies to every lift.

**Transverse (section): exact over the outer-line position, enumerated over width configurations.**
```
for base width w1 ≥ min_platform_width, for extra stepped lines (0..max_extra_rows) from the width grid:
  line j at y0 − Σw; line j stands to the highest lift k where it clears the hull over [z_base, z_k + ext] + gap_min
     (ext = 1.0 m for guardrail lines, 0.5 m for inner lines); lines 0 and 1 must clear full height
  per lift: edge = innermost line − bracket b, b ∈ {0, catalogue brackets}; bracket must clear hull over [z_k−0.5, z_k]
            feasible if gap_min ≤ edge − hull(z_k) ≤ max_gap; choose closest to target; none → transverse infill
  y0 candidates = every breakpoint where any lift outcome can change (gap window edges, line-top changes,
                  bracket clash) + target points + midpoints → minimum infill count is exact
  cost = 1000·infill_units + 10·Σ|gap − target| + 0.05·material proxy
```
Implemented vectorised in numpy: about 0.1–0.7 s per area and system.

**Component rules (deterministic, so a hand count can reproduce them).**
- Columns: `posts × lines`. Height `2·T_j + ext`, built greedily from standard lengths.
- One base jack per column.
- Base ledgers and transoms at level 0. Per lift: deck ledgers on every line, transoms per post per bay across.
- Diagonals every N bays (catalogue rule) on the outer face. Inner face too when free-standing or a tower.
- Decks: `decks_per_width` per bay across. One hatch per lift where a bay matches the hatch length; otherwise an access warning.
- Guardrails (2 rails) and toe boards on the outer line. Inner line too when protection is all_sides or the lift is open. End frames at free ends.
- Brackets: one per post on the inner line, plus their decks.
- Ties: `ceil(face / tie_area)`.
- Infill: tubes and couplers per the common tube-and-coupler file.
- Wedges: 2 per ledger, transom, guardrail or diagonal; 1 per bracket. Nodes = distinct (line, post, level) positions in use.

**Validation (flag only).** Load class per bay length; free-standing H/base; suspended (not modelled); gaps → infill warnings; obstruction clash (standards and platform zone vs obstruction polygons). In `avoid` mode the layout treats obstructions as part of the hull envelope. In `flag_only` mode clashes are errors and the system becomes ineligible.

## 4. Simulation and metrics
The sequence runs lift by lift: base jacks → standards → ledgers → transoms → diagonals → brackets → **advance guardrail** → decks → guardrails → toe boards → ties → wedge securing → infills.
- man-seconds = qty × time standard. Elapsed = man-time / (crew × efficiency(crew)).
- Unsecured-connection exposure = nodes × wedge-securing time.
- Unprotected exposure if no AGR = deck + guardrail placement time on lifts ≥ 1. It is 0 when AGR is modelled.
- Cost = rental (or purchase) + transport + labour (erection × (1 + dismantle factor)).

## 5. Recommendation
Criteria, all lower-is-better:
- productivity (crew-h/m²)
- material € (rental + transport)
- safety (unsecured exposure + infill crew-h + unprotected exposure)
- fit (infill units + gap violations)
- fleet fit (user-set)

Normalisation is `best/value`, and `(1+best)/(1+value)` for fit. Total = weighted mean.
- Systems with error-level violations are ineligible unless every system has them.
- Reasons = the three largest weighted contributions in favour of the winner.
- Sensitivity = the erection-time multiplier, found by bisection, at which the winner flips.
- The vessel summary compares 100 % A, 100 % B and the mixed optimum, with the complexity cost (€/yr × build months) applied to the mixed policy.

## 6. How to add a system
1. Copy `data/catalogues/sm8.yaml` to `data/catalogues/<new>.yaml` and set `system_id`, grids, rules (value/status/source) and components. Every bay length needs a ledger, deck, toe board and diagonal; every width needs a ledger, toe board and a `decks_per_width` entry. The loader rejects incomplete catalogues with a clear message.
2. Optionally add `data/time_standards/<new>.yaml`. Without it, `_generic.yaml` is used and stamped as `provisional-generic`.
3. Restart nothing: catalogues are reloaded per request. Test 5 does exactly this with a fictional system.

## 7. How to calibrate time standards
- **MVP (provisional):** `scripts/derive_provisional_standards.py` uses the same relative action weights for both systems and one scale factor per system, chosen so the reference tower reproduces the trial (76 / 52 min). One trial number calibrates one parameter, so splitting the difference between actions (e.g. AutoLock vs manual wedge) needs phase-level data. Test 2 guards this calibration point; it does not validate prediction.
- **Phase 3 (Annex A):**
  1. Import the field sheets (stage, run, system, crew, area, phase start/end, infills, Borg, first-time-right).
  2. Build per-phase action counts from the engine for each observed configuration.
  3. Fit man-seconds per action with non-negative least squares on phase durations, with a ridge penalty towards the provisional values.
  4. Report before/after MAPE per phase and system.
  5. Write a new versioned time-standard file. Runs stamp the version they used.

## 8. Findings from building the MVP (decision-relevant)
- **Test 4 (raked stem / bow) is not universally true in this model.**
  - On moderate curvature SM8's coarser grid needs more infills. Over 60 seeded flare sections SM8 needs 1.6× the infill lifts of Layher (163 vs 102), and the FR140 shoulder agrees.
  - On the strong-flare FR152 bow (about 0.8 m hull step per lift), SM8's long brackets (0.81/1.14 m) close steps that Layher's 0.39/0.73 m cannot: **3 vs 3 infill lifts** at default settings, and SM8 fewer if more stepped lines are allowed.
  - This is kept as a strict `xfail` test, not tuned away. With a 1.09 m Layher console (not in the brief data) the bow becomes a tie at worst, and Layher's aggregate advantage widens (88 vs 172).
  - **Action for VSR:** confirm Layher's bracket range.
- **Small geometry differences can change discrete choices.** The exact search makes DXF and PDF give identical layouts on the sample. Real drawings with ±20 mm noise can still flip a lift at a hard threshold (gap = 0.20 m). Treat lifts within 20 mm of a threshold as "marginal" (phase 2 UI flag).
- **Layher weights are 100 % estimates; SM8's about 3–7 %.** Material-cost conclusions are provisional until the Layher price list is loaded. The tool shows this on every result.

## 9. Limitations (MVP)
- 2D prismatic: a section stands for its whole frame range. Plan curvature at the bow/stern (waterline wrap) needs 3D (phase 2).
- An obstruction in a section is treated as continuous along the run, which is conservative.
- No stepped lines that start above ground (cantilever/suspended), no stair towers in the BoM, no ballast/outrigger design.
- Peak tonnage = sum of areas (upper bound) until the vessel schedule is modelled (phase 4).
- Auth is role-header based (OIDC to be terminated at the reverse proxy).

## 10. Open questions for VSR
1. DWG layer standard per design office/vessel? Are sections in true ship coordinates (body plan) or per-view CL/BL? Units?
2. PDFs: CAD exports or scans? Is text real text or SHX outlines (the sample shows outlines → frame-per-view input)?
3. Navisworks Manage version; selection/search sets per block; do properties carry block ID and discipline?
4. SM8 decks per width (2 × 330 mm on 0.81 m, 3 on 1.14 m?); SM8 base jack/tie/end toe-board data.
5. Layher: bracket range (1.09 m?), max wall distance without brackets, tie pattern, load class per bay for the LW decks used.
6. Transverse infill unit: per bay per lift (current) or per lift? Is 4.5 crew-h realistic for each?
7. Was the Rev02 reference tower tied, guardrailed on all sides, with a hatch per lift? These assumptions affect the calibration.
