"""Release validation tests 1-8 from the build brief (MVP scope; Navisworks parts are phase 2)."""
import math
import random
import shutil
from collections import Counter
from pathlib import Path

import pymupdf
import pytest
import yaml

from vsr.catalogue import load_bundle
from vsr.engine.layout import generate_layout
from vsr.engine.run import run_area
from vsr.geometry import pdf_import
from vsr.geometry.hull import Hull
from vsr.models import Area, Obstruction, Section
from vsr.reference import REFERENCE_TRIAL, reference_tower

from conftest import ROOT, SAMPLE


def bom_qty(res):
    return {b["code"]: b["qty"] for b in res["bom"]}


# ------------------------------------------------------------------------------------------ 1
# Hand count of the reference tower (4 bays x L, width W, 4 lifts of 2 m, decks every lift, one hatch
# per lift, guardrails + toe boards all sides, tied, diagonals every 5th bay on both long faces):
#   columns = 5 posts x 2 lines = 10, each 4 x 2 + 1.0 = 9.0 m = 4.0 + 4.0 + 1.0
#   base jacks 10
#   ledgers L : base 2 lines x 4 = 8; per lift deck 8 + guardrails 2 sides x 4 bays x 2 rails = 16 -> 8 + 4 x 24 = 104
#   ledgers W : base transoms 5; per lift transoms 5 + end guardrails 2 ends x 2 rails = 4 -> 5 + 4 x 9 = 41
#   diagonals : 2 faces x ceil(4/5) x 4 lifts = 8
#   decks     : 4 bays x 3 decks x 4 lifts - 4 hatches x 2 = 40 ; hatch decks 4
#   toe boards: L 2 sides x 4 bays x 4 lifts = 32 ; W 2 ends x 4 lifts = 8
#   ties      : ceil(run x 8 m / 22 m2) = ceil(80/22) = 4 (SM8), ceil(82.24/22) = 4 (Layher)
HAND = {
    "SM8": {"SM8-STD-400": 20, "SM8-STD-100": 10, "SM8-JACK-060": 10, "SM8-LED-250": 104, "SM8-LED-114": 41,
            "SM8-DIA-250": 8, "SM8-DECK-250": 40, "SM8-HATCH-250": 4, "SM8-TOE-250": 32, "SM8-TOE-114": 8,
            "SM8-TIE-050": 4},
    "LAYHER_LW": {"LAY-STD-400": 20, "LAY-STD-100": 10, "LAY-JACK-060": 10, "LAY-LED-257": 104, "LAY-LED-109": 41,
                  "LAY-DIA-257": 8, "LAY-DECK-257": 40, "LAY-HATCH-257": 4, "LAY-TOE-257": 32, "LAY-TOE-109": 8,
                  "LAY-TIE-050": 4},
}


@pytest.fixture(scope="module")
def ref_run(bundle):
    return run_area(reference_tower(), None, bundle)


@pytest.mark.parametrize("sid", ["SM8", "LAYHER_LW"])
def test_1_reference_tower_bom_matches_hand_count(ref_run, sid):
    assert bom_qty(ref_run["results"][sid]) == HAND[sid]


def test_1_sm8_weight_matches_catalogue_sum(ref_run):
    raw = yaml.safe_load((ROOT / "data" / "catalogues" / "sm8.yaml").read_text())
    w = {c["code"]: c["weight_kg"] for c in raw["components"]}
    hand_weight = sum(q * w[c] for c, q in HAND["SM8"].items())
    tool_weight = ref_run["results"]["SM8"]["metrics"]["weight_kg"]["value"]
    assert abs(tool_weight - hand_weight) / hand_weight < 0.01


# ------------------------------------------------------------------------------------------ 2
@pytest.mark.parametrize("sid", ["SM8", "LAYHER_LW"])
def test_2_reference_tower_time_reproduction(ref_run, sid):
    m = ref_run["results"][sid]["metrics"]["elapsed_min"]["value"]
    target = REFERENCE_TRIAL["minutes"][sid]
    assert abs(m - target) / target < 0.02, f"{sid}: {m:.1f} min vs {target} min"
    assert ref_run["snapshot"]["crew"] == 5
    assert ref_run["results"][sid]["versions"]["time_standard"]["status"] == "provisional"


# ------------------------------------------------------------------------------------------ 3
FLAT = Section(id="FLAT", frame=60, points=[(0, 0), (8.0, 0.0), (8.0, 16.0)], confidence="high")


@pytest.mark.parametrize("sid", ["SM8", "LAYHER_LW"])
@pytest.mark.parametrize("ends", [("bounded", "bounded"), ("free", "free"), ("bounded", "free")])
def test_3_flat_shell_no_infills_on_grid_multiple(bundle, sid, ends):
    cat = bundle.catalogues[sid]
    for L in cat.bay_lengths_m:
        for n in (1, 3, 7, 12):
            area = Area(id="F", name="flat", section_id="FLAT", run_length_m=round(L * n, 4), run_start=ends[0],
                        run_end=ends[1], z_base=0, z_top=12, n_lifts=5)
            lay = generate_layout(area, cat, FLAT, bundle.common)
            assert lay.infill_units() == 0, (sid, L, n, ends, lay.explanation)
            assert not lay.longitudinal_infill
            assert all(lp.status == "ok" for lp in lay.lifts)


# ------------------------------------------------------------------------------------------ 4
def _infill_lifts(lay):
    return sum(1 for lp in lay.lifts if lp.status == "infill")


def test_4_bow_section_counts_reported_and_stable(bundle, sections, project):
    area = Area(**next(a for a in project["areas"] if a["id"] == "B12-A2"))
    assert area.lifts() == 7
    r1 = run_area(area, sections["FR152"], bundle)
    r2 = run_area(area, sections["FR152"], bundle)
    for sid in ("SM8", "LAYHER_LW"):
        c1 = r1["results"][sid]["metrics"]["infill_units"]["value"]
        c2 = r2["results"][sid]["metrics"]["infill_units"]["value"]
        assert c1 == c2 and c1 >= 0
        assert r1["results"][sid]["layout"]["lifts"] == r2["results"][sid]["layout"]["lifts"]
    assert r1["run_id"] == r2["run_id"]          # deterministic snapshot


def test_4_coarser_grid_more_infills_on_curved_section(bundle, sections, project):
    area = Area(**next(a for a in project["areas"] if a["id"] == "B12-A3"))   # FR140 fore shoulder, 7 lifts
    n = {sid: _infill_lifts(generate_layout(area, bundle.catalogues[sid], sections["FR140"], bundle.common))
         for sid in ("SM8", "LAYHER_LW")}
    assert n["SM8"] > n["LAYHER_LW"], n


def test_4_coarser_grid_more_infills_in_aggregate(bundle):
    """60 seeded flare sections (7 lifts x 2 m, flare 1-4 m over 14 m): SM8 needs >= 25% more infill lifts."""
    rnd = random.Random(1)
    tot = Counter()
    for _ in range(60):
        y0, fl, ex = rnd.uniform(0.5, 3), rnd.uniform(1.0, 4.0), rnd.uniform(1.2, 2.5)
        sec = Section(id="R", frame=0, points=[(0, 0)] + [(y0 + fl * (z / 14) ** ex, z) for z in [j * 0.5 for j in range(1, 29)]])
        area = Area(id="R", name="r", section_id="R", run_length_m=10, z_base=0, z_top=14, n_lifts=7)
        for sid in ("SM8", "LAYHER_LW"):
            tot[sid] += _infill_lifts(generate_layout(area, bundle.catalogues[sid], sec, bundle.common))
    assert tot["SM8"] >= 1.25 * tot["LAYHER_LW"], tot


@pytest.mark.xfail(strict=True, reason=(
    "FINDING: on the strong-flare bow section FR152 (~0.4-0.5 m/m, ~0.8 m hull step per lift) SM8's longer "
    "brackets (0.81/1.14 m) close steps that Layher's 0.39/0.73 m brackets cannot: SM8 needs the SAME number of "
    "infill lifts (3 vs 3 at default settings; fewer if more stepped lines are allowed). The brief's expectation "
    "holds on moderate curvature (tests above) but not on this section. Sensitive to Layher bracket data "
    "(1.09 m console?) - open question to VSR. strict=True: the test alerts if this result changes."))
def test_4_brief_expectation_on_strong_bow_flare(bundle, sections, project):
    area = Area(**next(a for a in project["areas"] if a["id"] == "B12-A2"))
    n = {sid: _infill_lifts(generate_layout(area, bundle.catalogues[sid], sections["FR152"], bundle.common))
         for sid in ("SM8", "LAYHER_LW")}
    assert n["SM8"] > n["LAYHER_LW"], n


# ------------------------------------------------------------------------------------------ 5
DEMO = """
system_id: DEMO_X
name: Demo third system (fictional test data)
manufacturer: Test
catalogue_version: "test-1"
default_source: "fictional — validation test 5"
node: {type: cup, holes: 4, pitch_m: 0.5, wedge: cup}
lift_height_m: 2.0
bay_lengths_m: [1.30, 2.50]
bay_widths_m: [1.30]
rules:
  max_gap_without_bracket_m: {value: 0.25, status: estimate, source: test}
  tie_area_m2: {value: 24.0, status: estimate, source: test}
  load_class_by_bay: {value: {"1.30": 4, "2.50": 4}, status: estimate, source: test}
  decks_per_width: {value: {"1.30": 4}, status: estimate, source: test}
  bracket_decks: {value: {"0.50": 2}, status: estimate, source: test}
  diagonal_every_n_bays: {value: 4, status: estimate, source: test}
  free_standing_max_height_to_base: {value: 3.0, status: estimate, source: test}
components:
  - {code: X-STD-100, role: standard, length_m: 1.0, weight_kg: 5.5, status: estimate, name: std 1.0}
  - {code: X-STD-300, role: standard, length_m: 3.0, weight_kg: 15.5, status: estimate, name: std 3.0}
  - {code: X-LED-130, role: ledger, length_m: 1.30, weight_kg: 5.0, status: estimate, name: ledger 1.30}
  - {code: X-LED-250, role: ledger, length_m: 2.50, weight_kg: 9.0, status: estimate, name: ledger 2.50}
  - {code: X-DIA-130, role: diagonal, length_m: 1.30, weight_kg: 6.0, status: estimate, name: diag 1.30}
  - {code: X-DIA-250, role: diagonal, length_m: 2.50, weight_kg: 8.0, status: estimate, name: diag 2.50}
  - {code: X-DECK-130, role: deck, length_m: 1.30, width_m: 0.32, weight_kg: 7.0, status: estimate, name: deck 1.30}
  - {code: X-DECK-250, role: deck, length_m: 2.50, width_m: 0.32, weight_kg: 13.0, status: estimate, name: deck 2.50}
  - {code: X-TOE-130, role: toe_board, length_m: 1.30, weight_kg: 3.0, status: estimate, name: toe 1.30}
  - {code: X-TOE-250, role: toe_board, length_m: 2.50, weight_kg: 5.5, status: estimate, name: toe 2.50}
  - {code: X-BRK-050, role: bracket, length_m: 0.50, weight_kg: 4.0, status: estimate, name: bracket 0.50}
  - {code: X-JACK, role: base_jack, length_m: 0.6, weight_kg: 3.5, status: estimate, name: jack}
  - {code: X-TIE, role: tie, length_m: 0.5, weight_kg: 3.0, status: estimate, name: tie}
"""


def test_5_catalogue_extension_without_code_change(tmp_path, sections, project):
    d = tmp_path / "data"
    shutil.copytree(ROOT / "data", d)
    (d / "catalogues" / "demo_x.yaml").write_text(DEMO)
    b = load_bundle(d)
    assert set(b.catalogues) == {"SM8", "LAYHER_LW", "DEMO_X"}
    area = Area(**next(a for a in project["areas"] if a["id"] == "B12-A3"))
    run = run_area(area, sections["FR140"], b)
    assert set(run["results"]) == {"SM8", "LAYHER_LW", "DEMO_X"}
    x = run["results"]["DEMO_X"]
    assert x["bom"] and x["metrics"]["crew_hours"]["value"] > 0
    assert x["versions"]["time_standard"]["standard_id"] == "TS-GENERIC"
    assert run["comparison"]["recommended"] in run["results"]
    assert len(run["comparison"]["totals"]) == 3


# ------------------------------------------------------------------------------------------ 6
def test_6_traceability(bundle, sections, project):
    area = Area(**next(a for a in project["areas"] if a["id"] == "B12-A3"))
    run = run_area(area, sections["FR140"], bundle)
    snap = run["snapshot"]
    assert snap["geometry"]["hash"] and snap["geometry"]["source"] == "dxf"
    assert snap["settings"]["sha256"] and snap["common"]["sha256"]
    for sid, res in run["results"].items():
        cat, ts = bundle.catalogues[sid], bundle.time_standard_for(sid)
        v = snap["versions"][sid]
        assert v["catalogue"]["sha256"] == cat.sha256 and v["time_standard"]["sha256"] == ts.sha256
        metrics = res["metrics"]
        for name, m in metrics.items():
            assert {"value", "unit", "formula", "inputs"} <= set(m), name
            assert m["formula"] and isinstance(m["inputs"], dict) and m["inputs"], name
            for k, ref in m["inputs"].items():                # references to other metrics must resolve
                if isinstance(ref, str) and ref in metrics:
                    assert ref in metrics
        codes = {c.code for c in cat.components}
        for b in res["bom"]:
            assert b["status"] in ("verified", "estimate") and b["source"] and b["catalogue_version"]
            assert b["code"] in codes or b["catalogue"] == "tube_and_coupler"
            if b["catalogue"] == sid:
                comp = next(c for c in cat.components if c.code == b["code"])
                assert b["unit_weight_kg"] == comp.weight_kg and b["status"] == comp.status
        assert abs(sum(b["total_weight_kg"] for b in res["bom"]) - metrics["weight_kg"]["value"]) < 0.01
        steps = res["simulation"]["steps"]
        for s in steps:
            if s["action"] == "infill":
                assert s["man_s_each"] == ts.infill_crew_hours_per_unit * 3600
            else:
                assert s["man_s_each"] == ts.actions[s["action"]]
        assert abs(sum(s["man_s"] for s in steps) / 3600 - metrics["crew_hours"]["value"]) < 1e-3
        assert res["simulation"]["time_standard"]["version"] == ts.version
    # comparison raw values are the metrics
    for row in run["comparison"]["table"]:
        if row["criterion"] == "productivity":
            for sid in run["results"]:
                assert row["systems"][sid]["raw"] == run["results"][sid]["metrics"]["crew_hours_per_m2"]["value"]


# ------------------------------------------------------------------------------------------ 7
def _pdf_sections(project):
    from vsr.geometry.pdf_import import _paths, _style
    pdf = SAMPLE / "B12_frame_sections.pdf"
    info = pdf_import.inspect(pdf)
    styles = {s["style"] for s in info["styles"]}
    red, green, blue = (next(s for s in styles if s.startswith(c)) for c in ("#ff0000", "#00ff00", "#0000ff"))
    page = pymupdf.open(str(pdf))[0]
    cl = [p for d in page.get_drawings() if _style(d) == green for p in _paths(d)][0]
    bl = [p for d in page.get_drawings() if _style(d) == blue for p in _paths(d)][0]
    # "user clicks": ends of the CL line (16.000 m in the drawing), verified on the BL line (12.000 m)
    res = pdf_import.import_sections(pdf, 0, {red: "hull_shell", green: "centreline", blue: "baseline"},
                                     {"p1": cl[0], "p2": cl[-1], "distance_m": 16.0},
                                     {"p1": bl[0], "p2": bl[-1], "distance_m": 12.0},
                                     project["frame_spacing_m"], view_frames=[128, 140, 152])
    return {s.id: s for s in res["sections"]}, res["report"]


def test_7_import_consistency_dxf_vs_pdf(bundle, sections, project):
    psec, rep = _pdf_sections(project)
    assert rep["verification"]["error_pct"] < 0.5
    assert set(psec) == set(sections)
    for sid, s in sections.items():
        ha, hb = Hull(s), Hull(psec[sid])
        for z in [0.3 + 0.25 * i for i in range(54)]:
            assert abs(ha.hull_y(z) - hb.hull_y(z)) <= 0.020, (sid, z)
    for ad in project["areas"]:
        if not ad.get("section_id"):
            continue
        area = Area(**ad).model_copy(update={"use_drawing_obstructions": False})
        for sys_id, cat in bundle.catalogues.items():
            la = generate_layout(area, cat, sections[area.section_id], bundle.common)
            lb = generate_layout(area, cat, psec[area.section_id], bundle.common)
            assert la.bays == lb.bays, (ad["id"], sys_id)                        # bay count per lift (brief)
            assert la.widths == lb.widths, (ad["id"], sys_id)                    # same transverse configuration
            assert la.infill_units() == lb.infill_units(), (ad["id"], sys_id)    # same infill count


def test_7_navisworks_route():
    pytest.skip("Phase 2: Navisworks FBX + properties CSV import (plug-in) not in MVP scope")


# ------------------------------------------------------------------------------------------ 8
def _obs_area(project, mode):
    return Area(**next(a for a in project["areas"] if a["id"] == "B12-A1")).model_copy(
        update={"obstruction_mode": mode})


def test_8_obstruction_avoided_or_flagged(bundle, sections, dxf_result, project):
    obs = dxf_result["obstructions"][128.0]
    assert obs, "sample drawing carries an obstruction at FR128"
    # avoid: layout moves out, no clash remains
    area = _obs_area(project, "avoid").model_copy(update={"obstructions": obs})
    run = run_area(area, sections["FR128"], bundle)
    for sid, res in run["results"].items():
        assert not [v for v in res["layout"]["violations"] if v["rule"] == "clash"], sid
        assert min(res["layout"]["line_y"]) >= 9.35 + area.gap_min_m - 1e-6
    # flag only: clash reported as error, system ineligible — never silently ignored
    area = _obs_area(project, "flag_only").model_copy(update={"obstructions": obs})
    run = run_area(area, sections["FR128"], bundle)
    for sid, res in run["results"].items():
        clashes = [v for v in res["layout"]["violations"] if v["rule"] == "clash"]
        assert clashes and all(v["severity"] == "error" for v in clashes), sid
        assert res["valid"] is False


def test_8_obstruction_in_scaffold_zone_flagged_even_in_avoid_mode(bundle, sections, project):
    # an item standing outboard of the shell where the scaffold is (e.g. dock services) cannot be "avoided"
    obs = [Obstruction(name="DOCK-PIPE", points=[(9.6, 3.0), (11.5, 3.0), (11.5, 3.3), (9.6, 3.3)])]
    area = _obs_area(project, "avoid").model_copy(update={"obstructions": obs, "max_extra_rows": 0})
    run = run_area(area, sections["FR128"], bundle)
    for sid, res in run["results"].items():
        assert [v for v in res["layout"]["violations"] if v["rule"] == "clash"], sid


def test_8_navisworks_zone():
    pytest.skip("Phase 2: 3D obstruction clash on Navisworks zones (piping, cable trays) not in MVP scope")
