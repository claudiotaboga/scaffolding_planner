"""Vector PDF import (CAD exports). Scanned PDFs are a phase-2 feature (trace tool + OCR) and are refused
here rather than guessed: raster-derived geometry is never used without user confirmation.

Workflow:
  1. inspect(path, page)  -> pages, path styles (stroke colour / width) with counts, frame texts, raster flag
  2. import_sections(path, page, style_mapping, calibration, verification) -> Section list
Calibration: two points (PDF coordinates, pt) and their real distance (m); verified with a second pair.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import pymupdf

from ..models import Section
from .dxf_import import _chain
from .mapping import parse_frame


def _style(d: dict) -> str:
    c = d.get("color") or (0, 0, 0)
    w = d.get("width") or 0.0
    return "#%02x%02x%02x/%.2f" % (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), w)


def _paths(d: dict, n_bezier: int = 12) -> list[list[tuple[float, float]]]:
    out, cur = [], []
    for it in d["items"]:
        kind = it[0]
        if kind == "l":
            a, b = it[1], it[2]
            if cur and math.hypot(cur[-1][0] - a.x, cur[-1][1] - a.y) < 1e-3:
                cur.append((b.x, b.y))
            else:
                if len(cur) > 1:
                    out.append(cur)
                cur = [(a.x, a.y), (b.x, b.y)]
        elif kind == "c":
            p0, p1, p2, p3 = it[1:5]
            pts = []
            for i in range(n_bezier + 1):
                t = i / n_bezier
                x = (1 - t) ** 3 * p0.x + 3 * (1 - t) ** 2 * t * p1.x + 3 * (1 - t) * t ** 2 * p2.x + t ** 3 * p3.x
                y = (1 - t) ** 3 * p0.y + 3 * (1 - t) ** 2 * t * p1.y + 3 * (1 - t) * t ** 2 * p2.y + t ** 3 * p3.y
                pts.append((x, y))
            if cur and math.hypot(cur[-1][0] - pts[0][0], cur[-1][1] - pts[0][1]) < 1e-3:
                cur += pts[1:]
            else:
                if len(cur) > 1:
                    out.append(cur)
                cur = pts
        elif kind == "re":
            r = it[1]
            if len(cur) > 1:
                out.append(cur)
            cur = []
            out.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
    if len(cur) > 1:
        out.append(cur)
    return out


def inspect(path: str | Path, page_no: int = 0) -> dict:
    doc = pymupdf.open(str(path))
    page = doc[page_no]
    drawings = page.get_drawings()
    styles = Counter(_style(d) for d in drawings)
    words = page.get_text("words")
    frames = []
    for i, w in enumerate(words):
        txt = w[4] if parse_frame(w[4]) is not None else (w[4] + " " + words[i + 1][4] if i + 1 < len(words) else w[4])
        fr = parse_frame(txt)
        if fr is not None:
            frames.append({"frame": fr, "x": (w[0] + w[2]) / 2, "y": (w[1] + w[3]) / 2})
    raster = len(drawings) < 5 and len(page.get_images()) > 0
    return {"pages": len(doc), "page": page_no, "size_pt": [page.rect.width, page.rect.height],
            "styles": [{"style": s, "paths": n} for s, n in styles.most_common()],
            "frames": frames, "raster_only": raster}


def import_sections(path: str | Path, page_no: int, style_mapping: dict[str, str], calibration: dict,
                    verification: Optional[dict] = None, frame_spacing_m: float = 0.70,
                    view_frames: Optional[list[float]] = None) -> dict:
    """view_frames: frame numbers of the detected views ordered left -> right (needed when the PDF
    carries text as vector outlines, common for SHX fonts in CAD plots)."""
    doc = pymupdf.open(str(path))
    page = doc[page_no]
    drawings = page.get_drawings()
    warnings: list[str] = []
    if len(drawings) < 5 and page.get_images():
        raise ValueError("Page looks scanned (raster only). Scanned-PDF tracing is phase 2; use the manual editor or "
                         "a vector export.")
    (x1, y1), (x2, y2) = calibration["p1"], calibration["p2"]
    d_pt = math.hypot(x2 - x1, y2 - y1)
    s = calibration["distance_m"] / d_pt                     # metres per pt
    ver = None
    conf = "medium"
    if verification:
        (a1, b1), (a2, b2) = verification["p1"], verification["p2"]
        meas = math.hypot(a2 - a1, b2 - b1) * s
        err = abs(meas - verification["distance_m"]) / verification["distance_m"]
        ver = {"measured_m": meas, "expected_m": verification["distance_m"], "error_pct": err * 100}
        if err > 0.005:
            warnings.append(f"Scale verification error {err*100:.2f}% > 0.5%: check calibration points.")
            conf = "low"
    else:
        warnings.append("No second dimension given: scale not verified.")
    groups: dict[str, list] = defaultdict(list)
    for d in drawings:
        m = style_mapping.get(_style(d), "ignore")
        if m != "ignore":
            groups[m].extend(_paths(d))
    # CL = vertical, BL = horizontal paths
    cls = [(p[0][0] + p[-1][0]) / 2 for p in groups.get("centreline", []) if abs(p[0][0] - p[-1][0]) < 1.0]
    bls = [(p[0][1] + p[-1][1]) / 2 for p in groups.get("baseline", []) if abs(p[0][1] - p[-1][1]) < 1.0]
    if not cls or not bls:
        raise ValueError("Map a centreline and a baseline style (or draw them) so each view can be registered.")
    words = page.get_text("words")
    texts = []
    for i, w in enumerate(words):
        txt = w[4]
        fr = parse_frame(txt)
        if fr is None and i + 1 < len(words):
            fr = parse_frame(txt + " " + words[i + 1][4])
        if fr is not None:
            texts.append((fr, (w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
    chains = _chain(groups.get("hull_shell", []), tol=0.5)
    cls_sorted = sorted(set(round(c, 2) for c in cls))
    if view_frames is not None and len(view_frames) != len(cls_sorted):
        raise ValueError(f"{len(cls_sorted)} views detected but {len(view_frames)} frame numbers given")
    sections = []
    for idx, ch in enumerate(chains):
        xs = [q[0] for q in ch]
        left = [c for c in cls_sorted if c <= min(xs) + 1.0]
        cx = max(left) if left else min(cls_sorted, key=lambda c: min(abs(x - c) for x in xs))
        by = min(bls, key=lambda b: abs(max(q[1] for q in ch) - b))     # PDF y grows downward
        if view_frames is not None:
            fr = float(view_frames[cls_sorted.index(cx)])
        else:
            nxt = min([c for c in cls_sorted if c > cx], default=math.inf)
            inview = [t for t in texts if cx - 5 <= t[1] < nxt]
            cands = sorted(inview, key=lambda t: abs(t[1] - cx) + 0.2 * abs(t[2] - by))
            if not cands:
                raise ValueError("No frame text found in a view (text may be vector outlines): pass view_frames.")
            fr = cands[0][0]
        pts = [(round(abs(x - cx) * s, 4), round((by - y) * s, 4)) for x, y in ch]
        if pts[0][1] > pts[-1][1]:
            pts = pts[::-1]
        sections.append(Section(id=f"FR{fr:g}", frame=fr, x=round(fr * frame_spacing_m, 3), points=pts,
                                source="pdf_vector", source_file=Path(path).name, confidence=conf,
                                notes=list(warnings)))
    sections.sort(key=lambda q: q.frame)
    return {"sections": sections, "report": {"m_per_pt": s, "verification": ver, "warnings": warnings,
                                             "chains": len(chains), "views": len(cls)}}
