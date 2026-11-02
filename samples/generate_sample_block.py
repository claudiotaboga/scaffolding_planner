"""Generate the sample project: block B12 (fore body), three frame sections on one DXF sheet,
its PDF export (vector, as a CAD plot would be) and the project definition (areas, mappings).

Synthetic geometry, representative of a 19 m beam / 14 m depth vessel; NOT a VARD design.
Run: python samples/generate_sample_block.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "block_B12"
FRAME_SPACING = 0.70
VIEW_DX = 15000.0   # mm between views on the sheet
FRAMES = [128, 140, 152]


def hull_entities(msp, fr: int, cx: float):
    """Starboard half-section in mm, origin at (cx, 0) = CL/BL."""
    a = {"layer": "HULL_SHELL"}
    if fr == 128:   # near-parallel side, bilge as LWPOLYLINE bulge arc (r = 1500)
        msp.add_lwpolyline([(cx + 0, 0, 0), (cx + 7500, 0, 0.41421356), (cx + 9000, 1500, 0), (cx + 9000, 14000, 0)],
                           format="xyb", dxfattribs=a)
    elif fr == 140:  # moderate flare: bottom line + bilge arc + spline side
        msp.add_lwpolyline([(cx + 0, 0, 0), (cx + 5000, 0, 0.41421356), (cx + 6800, 1800, 0)], format="xyb", dxfattribs=a)
        msp.add_spline(fit_points=[(cx + 6800, 1800), (cx + 7000, 4000), (cx + 7400, 7000), (cx + 7900, 10000),
                                   (cx + 8600, 14000)], dxfattribs=a)
    elif fr == 152:  # strong bow flare
        msp.add_line((cx + 0, 0), (cx + 1500, 0), dxfattribs=a)
        msp.add_spline(fit_points=[(cx + 1500, 0), (cx + 2200, 1500), (cx + 3000, 3500), (cx + 4000, 6000),
                                   (cx + 5200, 9000), (cx + 6500, 12000), (cx + 7300, 14000)], dxfattribs=a)


def build_dxf(path: Path):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, color in [("HULL_SHELL", 1), ("CL", 3), ("BL", 5), ("FRAME_NO", 7), ("DIM", 2), ("DECK", 4),
                        ("OUTFIT_OBST", 6), ("TITLE", 8)]:
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    for i, fr in enumerate(FRAMES):
        cx = i * VIEW_DX
        msp.add_line((cx, -1000), (cx, 15000), dxfattribs={"layer": "CL"})            # 16.000 m
        msp.add_line((cx - 1000, 0), (cx + 11000, 0), dxfattribs={"layer": "BL"})      # 12.000 m
        hull_entities(msp, fr, cx)
        msp.add_line((cx, 14000), (cx + {128: 9000, 140: 8600, 152: 7300}[fr], 14000), dxfattribs={"layer": "DECK"})
        msp.add_text(f"FR {fr}", height=350, dxfattribs={"layer": "FRAME_NO"}).set_placement(
            (cx + 4000, -1800), align=TextEntityAlignment.MIDDLE_CENTER)
        dim = msp.add_linear_dim(base=(cx + 10500, 0), p1=(cx + 10000, 0), p2=(cx + 10000, 14000), angle=90,
                                 text="14000", dxfattribs={"layer": "DIM"})
        dim.render()
    # outfitting obstruction at FR 128: overboard discharge fitting protruding 0.35 m from shell at z 6.0-6.6
    cx = 0.0
    msp.add_lwpolyline([(cx + 9000, 6000), (cx + 9350, 6000), (cx + 9350, 6600), (cx + 9000, 6600)], close=True,
                       dxfattribs={"layer": "OUTFIT_OBST"})
    msp.add_text("SAMPLE BLOCK B12 — FRAME SECTIONS (synthetic)", height=400, dxfattribs={"layer": "TITLE"}).set_placement(
        (0, 17000))
    doc.saveas(path)


def build_pdf(dxf_path: Path, pdf_path: Path):
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
    from ezdxf.addons.drawing import pymupdf as pmb
    doc = ezdxf.readfile(dxf_path)
    backend = pmb.PyMuPdfBackend()
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                               lineweight_policy=config.LineweightPolicy.ABSOLUTE)
    Frontend(RenderContext(doc), backend, config=cfg).draw_layout(doc.modelspace())
    page = layout.Page(841, 594, layout.Units.mm, margins=layout.Margins.all(10))   # A1 plot
    pdf_path.write_bytes(backend.get_pdf_bytes(page))


LAYER_MAPPING = {"HULL_SHELL": "hull_shell", "CL": "centreline", "BL": "baseline", "FRAME_NO": "frame_text",
                 "DIM": "dimension", "DECK": "deck", "OUTFIT_OBST": "obstruction", "TITLE": "ignore"}

AREAS = [
    {"id": "B12-A1", "name": "B12 SB side shell Fr128-140", "area_type": "flat_shell", "section_id": "FR128",
     "frame_from": 128, "frame_to": 140, "frame_spacing_m": FRAME_SPACING, "z_base": -1.4, "z_top": 14.0,
     "anchorage": "tied", "use_drawing_obstructions": True},
    {"id": "B12-A2", "name": "B12 SB bow flare Fr148-156", "area_type": "bow_flare", "section_id": "FR152",
     "frame_from": 148, "frame_to": 156, "frame_spacing_m": FRAME_SPACING, "z_base": -1.4, "z_top": 14.0,
     "n_lifts": 7, "anchorage": "tied"},
    {"id": "B12-A3", "name": "B12 SB fore shoulder Fr140-148", "area_type": "curved_shell", "section_id": "FR140",
     "frame_from": 140, "frame_to": 148, "frame_spacing_m": FRAME_SPACING, "z_base": -1.4, "z_top": 14.0,
     "anchorage": "tied"},
    {"id": "B12-A4", "name": "Tank T12 SB inner shell, between bulkheads Fr130-139", "area_type": "internal_compartment",
     "section_id": "FR128", "face": "inboard", "frame_from": 130, "frame_to": 139, "frame_spacing_m": FRAME_SPACING,
     "run_start": "bounded", "run_end": "bounded", "z_base": 1.5, "z_top": 9.5, "anchorage": "tied"},
    {"id": "REF-TOWER", "name": "Reference tower (Rev02 slide 7)", "area_type": "tower", "tower_bays": 4,
     "tower_bay_target_m": 2.5, "tower_width_target_m": 1.1, "n_lifts": 4, "z_base": 0.0, "z_top": 10.0,
     "anchorage": "tied", "protection": "all_sides"},
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dxf = OUT / "B12_frame_sections.dxf"
    pdf = OUT / "B12_frame_sections.pdf"
    build_dxf(dxf)
    build_pdf(dxf, pdf)
    project = {"id": "SAMPLE-B12", "name": "Sample vessel — block B12 (fore body)", "vessel": "SAMPLE (synthetic)",
               "frame_spacing_m": FRAME_SPACING, "drawings": [
                   {"file": dxf.name, "kind": "dxf", "layer_mapping": LAYER_MAPPING, "template": "SAMPLE-SECTIONS"},
                   {"file": pdf.name, "kind": "pdf", "page": 0, "note": "vector export of the DXF (A1 plot)"}],
               "areas": AREAS}
    (OUT / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    print("wrote", dxf, pdf, OUT / "project.json")


if __name__ == "__main__":
    sys.exit(main())
