"""DXF (and DWG via ODA File Converter) import of frame-section drawings.

Workflow:
  1. inspect(path)        -> layers with entity counts + guessed meaning, units, dimensions (for the wizard)
  2. import_sections(path, mapping, ...) -> Section list in ship coordinates + scale check report

Views: each frame section view is located by its centreline (vertical line on a `centreline` layer)
and baseline (horizontal line on a `baseline` layer). Hull points are measured from that CL/BL origin,
so sections drawn side by side on one sheet are each registered correctly. Without CL/BL layers the
drawing origin is used (and a warning is raised).
"""
from __future__ import annotations

import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import ezdxf
from ezdxf import path as ezpath

from ..models import Obstruction, Section
from .mapping import guess_meaning, parse_frame

INSUNITS_TO_M = {0: None, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 14: 0.1}


def read_doc(path: str | Path):
    p = Path(path)
    if p.suffix.lower() == ".dwg":
        return read_dwg(p)
    return ezdxf.readfile(str(p))


def read_dwg(p: Path):
    """DWG -> DXF with the ODA File Converter (server-side). Configure ODA_FILE_CONVERTER to the binary."""
    from ezdxf.addons import odafc
    exe = os.environ.get("ODA_FILE_CONVERTER")
    if exe:
        ezdxf.options.set("odafc-addon", "unix_exec_path" if os.name != "nt" else "win_exec_path", exe)
    if not odafc.is_installed():
        raise RuntimeError("DWG import needs the ODA File Converter. Install it on the server and set "
                           "ODA_FILE_CONVERTER=/path/to/ODAFileConverter (LibreDWG is not used for production).")
    return odafc.readfile(str(p))


def _entities(msp):
    """Model-space entities with block inserts exploded (recursively)."""
    for e in msp:
        if e.dxftype() == "INSERT":
            try:
                for v in e.virtual_entities():
                    if v.dxftype() == "INSERT":
                        yield from _entities([v])
                    else:
                        yield v
            except Exception:
                continue
        else:
            yield e


def inspect(path: str | Path) -> dict:
    doc = read_doc(path)
    msp = doc.modelspace()
    counts: Counter = Counter()
    types: dict[str, Counter] = defaultdict(Counter)
    texts = []
    dims = []
    for e in _entities(msp):
        layer = e.dxf.layer
        counts[layer] += 1
        types[layer][e.dxftype()] += 1
        if e.dxftype() in ("TEXT", "MTEXT"):
            t = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
            texts.append({"layer": layer, "text": t})
        if e.dxftype() == "DIMENSION":
            dims.append(_dim_check(e, 1.0))
    units = doc.header.get("$INSUNITS", 0)
    return {
        "layers": [{"name": n, "entities": c, "types": dict(types[n]), "guess": guess_meaning(n)}
                   for n, c in sorted(counts.items())],
        "insunits": units, "unit_to_m": INSUNITS_TO_M.get(units),
        "texts_sample": texts[:40], "dimensions": dims[:40],
        "frames_found": sorted({f for t in texts if (f := parse_frame(t["text"])) is not None}),
    }


def _dim_check(e, f: float) -> dict:
    """Compare the dimension's displayed text (if numeric override) with its measured geometry."""
    try:
        meas = e.get_measurement()
        meas = float(meas) if not hasattr(meas, "magnitude") else float(meas.magnitude)
    except Exception:
        meas = None
    txt = (e.dxf.get("text", "") or "").strip()
    out = {"measured_drawing_units": meas, "text": txt, "measured_m": meas * f if meas is not None else None}
    try:
        val = float(txt.replace(",", "."))
        out["text_value"] = val
        if meas:
            out["ratio_text_over_measured"] = val / meas
    except ValueError:
        pass
    return out


def _to_polyline(e, tol: float) -> list[tuple[float, float]]:
    t = e.dxftype()
    if t == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    try:
        p = ezpath.make_path(e)
    except (TypeError, ValueError):
        return []
    return [(v.x, v.y) for v in p.flattening(distance=tol)]


def _chain(polys: list[list[tuple[float, float]]], tol: float) -> list[list[tuple[float, float]]]:
    """Join polyline fragments end-to-end."""
    polys = [list(p) for p in polys if len(p) >= 2]
    out = []
    while polys:
        cur = polys.pop(0)
        changed = True
        while changed:
            changed = False
            for i, p in enumerate(polys):
                d = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])
                if d(cur[-1], p[0]) < tol:
                    cur += p[1:]
                elif d(cur[-1], p[-1]) < tol:
                    cur += p[::-1][1:]
                elif d(cur[0], p[-1]) < tol:
                    cur = p[:-1] + cur
                elif d(cur[0], p[0]) < tol:
                    cur = p[::-1][:-1] + cur
                else:
                    continue
                polys.pop(i)
                changed = True
                break
        out.append(cur)
    return out


def import_sections(path: str | Path, mapping: dict[str, str], frame_spacing_m: float = 0.70,
                    unit_to_m: Optional[float] = None, known_dimension: Optional[dict] = None,
                    source_label: Optional[str] = None) -> dict:
    """Return {"sections": [...], "obstructions": {frame: [...]}, "report": {...}}."""
    p = Path(path)
    doc = read_doc(p)
    msp = doc.modelspace()
    warnings: list[str] = []
    units = doc.header.get("$INSUNITS", 0)
    f = unit_to_m or INSUNITS_TO_M.get(units)
    if f is None:
        f = 0.001
        warnings.append("Drawing units not set ($INSUNITS=0): assumed millimetres — verify with a known dimension.")
    tol_flat = 0.005 / f            # 5 mm chordal tolerance in drawing units
    by_meaning: dict[str, list] = defaultdict(list)
    for e in _entities(msp):
        m = mapping.get(e.dxf.layer, "ignore")
        if m != "ignore":
            by_meaning[m].append(e)

    # scale check
    dims = [_dim_check(e, f) for e in by_meaning.get("dimension", [])]
    for e in msp.query("DIMENSION"):
        if e.dxf.layer not in mapping or mapping.get(e.dxf.layer) != "dimension":
            dims.append(_dim_check(e, f))
    scale_ok = True
    for d in dims:
        r = d.get("ratio_text_over_measured")
        if r is not None and abs(r - 1.0) > 0.005:
            scale_ok = False
            warnings.append(f"Dimension text {d['text']} vs measured {d['measured_drawing_units']:.1f}: ratio {r:.4f} — "
                            f"drawing may not be at 1:1 in model space.")
    if known_dimension:
        (x1, y1), (x2, y2) = known_dimension["p1"], known_dimension["p2"]
        meas = math.hypot(x2 - x1, y2 - y1) * f
        err = abs(meas - known_dimension["value_m"]) / known_dimension["value_m"]
        if err > 0.005:
            scale_ok = False
            warnings.append(f"Known dimension check failed: measured {meas:.3f} m vs {known_dimension['value_m']:.3f} m "
                            f"({err*100:.2f}%).")

    # views (CL / BL)
    cls = [(e.dxf.start.x + e.dxf.end.x) / 2 for e in by_meaning.get("centreline", []) if e.dxftype() == "LINE"]
    bls = [(e.dxf.start.y + e.dxf.end.y) / 2 for e in by_meaning.get("baseline", []) if e.dxftype() == "LINE"]
    if not cls or not bls:
        warnings.append("No centreline/baseline layer mapped: drawing origin used as (CL, BL).")
        cls, bls = cls or [0.0], bls or [0.0]

    def origin_for(pts):
        """View origin: CL immediately left of the geometry (sections drawn to starboard of their CL);
        falls back to the nearest CL. BL nearest to the lowest point."""
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        tol = 0.05 / f
        left = [c for c in cls if c <= min(xs) + tol]
        cx = max(left) if left else min(cls, key=lambda c: min(abs(x - c) for x in xs))
        by = min(bls, key=lambda b: abs(min(ys) - b))
        return cx, by

    hull_polys = [pl for e in by_meaning.get("hull_shell", []) if (pl := _to_polyline(e, tol_flat))]
    chains = _chain(hull_polys, tol=0.002 / f)
    texts = []
    for e in by_meaning.get("frame_text", []):
        t = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
        fr = parse_frame(t)
        if fr is not None:
            ins = e.dxf.insert
            texts.append((fr, ins.x, ins.y))
    sections = []
    used_frames = set()
    view_frame: dict[float, float] = {}
    for idx, ch in enumerate(chains):
        cx, by = origin_for(ch)
        # nearest frame text to this view's CL
        nxt = min([c for c in cls if c > cx + 1e-6], default=math.inf)
        inview = [t for t in texts if cx - 0.5 / f <= t[1] < nxt] or texts
        cands = sorted(inview, key=lambda t: abs(t[1] - cx) + 0.2 * abs(t[2] - by))
        fr = cands[0][0] if cands else float(idx)
        if not cands:
            warnings.append(f"No frame number text found for hull chain {idx}; assigned frame {idx}.")
        if fr in used_frames:
            warnings.append(f"Frame {fr} matched more than one hull chain; check the frame-text mapping.")
        used_frames.add(fr)
        view_frame[round(cx, 3)] = fr
        pts = [(round(abs(x - cx) * f, 4), round((y - by) * f, 4)) for x, y in ch]
        if pts[0][1] > pts[-1][1]:
            pts = pts[::-1]
        sections.append(Section(id=f"FR{fr:g}", frame=fr, x=round(fr * frame_spacing_m, 3), points=pts,
                                source=source_label or ("dwg" if p.suffix.lower() == ".dwg" else "dxf"),
                                source_file=p.name, confidence="high" if scale_ok else "medium",
                                notes=list(warnings)))
    obstructions: dict[float, list[Obstruction]] = defaultdict(list)
    for e in by_meaning.get("obstruction", []):
        pl = _to_polyline(e, tol_flat)
        if len(pl) < 3:
            continue
        cx, by = origin_for(pl)
        fr = view_frame.get(round(cx, 3), sections[0].frame if sections else 0.0)
        obstructions[fr].append(Obstruction(name=f"{e.dxf.layer}-{len(obstructions[fr]) + 1}",
                                            points=[(abs(x - cx) * f, (y - by) * f) for x, y in pl]))
    sections.sort(key=lambda s: s.frame)
    return {"sections": sections, "obstructions": {k: v for k, v in obstructions.items()},
            "report": {"units": units, "unit_to_m": f, "scale_ok": scale_ok, "dimensions": dims,
                       "warnings": warnings, "views": len(cls), "chains": len(chains)}}
