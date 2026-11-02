"""FastAPI application: projects, drawings import (DXF/DWG/PDF), sections, areas, runs, exports.

Auth: OIDC-ready. In the MVP (VSR_AUTH=off) the role comes from the X-VSR-Role header (default planner).
Roles: planner (all), ie (time standards, runs), hse (read + runs), viewer (read only).
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..catalogue import load_bundle
from ..engine.compare import compare
from ..engine.fleet import vessel_summary
from ..engine.run import run_area
from ..export.excel import run_workbook, summary_workbook, trace_csv
from ..geometry import dxf_import, pdf_import
from ..geometry.mapping import MEANINGS
from ..models import Area, Obstruction, Section
from ..store import Store

ROOT = Path(__file__).resolve().parents[3]
store = Store()


@asynccontextmanager
async def lifespan(_app):
    if os.environ.get("VSR_SEED_SAMPLE", "1") == "1" and not store.list_projects():
        seed_sample()
    yield


app = FastAPI(title="VSR Scaffold Planner", version="0.1.0-mvp", lifespan=lifespan)
WRITE_ROLES = {"planner", "ie"}


def role(x_vsr_role: Optional[str] = Header(default=None)) -> str:
    if os.environ.get("VSR_AUTH", "off") == "oidc":
        raise HTTPException(501, "OIDC validation is configured at the reverse proxy in this release")
    return (x_vsr_role or "planner").lower()


def writer(r: str = Depends(role)) -> str:
    if r not in WRITE_ROLES:
        raise HTTPException(403, f"role {r} is read-only")
    return r


def bundle():
    return load_bundle()   # reloaded per request: catalogue edits take effect immediately and are hashed


def _project(pid: str) -> dict:
    p = store.get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    # normalise areas through the model so every field (and its default) is explicit
    p["areas"] = [Area(**a).model_dump() for a in p.get("areas", [])]
    return p


# ------------------------------------------------------------------ meta / catalogues
@app.get("/api/meta")
def meta():
    b = bundle()
    return {"catalogues": {k: c.version_stamp() | {"name": c.name, "bay_lengths_m": c.bay_lengths_m,
                                                   "bay_widths_m": c.bay_widths_m, "node": c.node}
                           for k, c in b.catalogues.items()},
            "time_standards": {k: t.version_stamp() for k, t in b.time_standards.items()},
            "settings": {k: v for k, v in b.settings.items()}, "meanings": MEANINGS,
            "disclaimer": b.settings["disclaimer"]}


@app.get("/api/catalogues/{sid}")
def catalogue(sid: str):
    b = bundle()
    if sid not in b.catalogues:
        raise HTTPException(404)
    return b.catalogues[sid].model_dump()


@app.get("/api/time-standards/{sid}")
def time_standard(sid: str):
    return bundle().time_standard_for(sid).model_dump()


# ------------------------------------------------------------------ projects
class NewProject(BaseModel):
    name: str
    vessel: str = ""
    frame_spacing_m: float = 0.70


@app.get("/api/projects")
def projects():
    return [{"id": p["id"], "name": p["name"], "vessel": p.get("vessel", ""), "areas": len(p.get("areas", [])),
             "sections": len(p.get("sections", []))} for p in store.list_projects()]


@app.post("/api/projects")
def new_project(body: NewProject, _: str = Depends(writer)):
    pid = "P-" + uuid.uuid4().hex[:8].upper()
    doc = {"id": pid, "name": body.name, "vessel": body.vessel, "frame_spacing_m": body.frame_spacing_m,
           "sections": [], "obstructions_by_frame": {}, "areas": []}
    store.save_project(doc)
    return doc


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    p = _project(pid)
    p["drawings"] = store.list_drawings(pid)
    p["runs"] = store.list_runs(pid)
    return p


@app.delete("/api/projects/{pid}")
def delete_project(pid: str, _: str = Depends(writer)):
    store.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/sample")
def load_sample(_: str = Depends(writer)):
    return seed_sample(force=True)


def seed_sample(force: bool = False) -> dict:
    sdir = ROOT / "samples" / "block_B12"
    pj = json.loads((sdir / "project.json").read_text())
    if store.get_project(pj["id"]) and not force:
        return store.get_project(pj["id"])
    d = pj["drawings"][0]
    res = dxf_import.import_sections(sdir / d["file"], d["layer_mapping"], pj["frame_spacing_m"])
    store.save_mapping(d["template"], "dxf", d["layer_mapping"])
    did = "D-" + uuid.uuid4().hex[:8].upper()
    dst = store.files_dir / f"{did}_{d['file']}"
    shutil.copy(sdir / d["file"], dst)
    store.save_drawing({"id": did, "project_id": pj["id"], "file": d["file"], "path": str(dst), "kind": "dxf",
                        "template": d["template"], "mapping": d["layer_mapping"], "report": res["report"]})
    doc = {"id": pj["id"], "name": pj["name"], "vessel": pj["vessel"], "frame_spacing_m": pj["frame_spacing_m"],
           "sections": [s.model_dump() for s in res["sections"]],
           "obstructions_by_frame": {str(k): [o.model_dump() for o in v] for k, v in res["obstructions"].items()},
           "areas": pj["areas"]}
    store.save_project(doc)
    return doc


# ------------------------------------------------------------------ drawings
@app.post("/api/projects/{pid}/drawings")
async def upload_drawing(pid: str, file: UploadFile = File(...), _: str = Depends(writer)):
    _project(pid)
    ext = Path(file.filename).suffix.lower()
    if ext not in (".dxf", ".dwg", ".pdf"):
        raise HTTPException(400, "Supported: .dwg (via ODA), .dxf, .pdf. Navisworks import is phase 2.")
    did = "D-" + uuid.uuid4().hex[:8].upper()
    dst = store.files_dir / f"{did}_{Path(file.filename).name}"
    dst.write_bytes(await file.read())
    try:
        info = pdf_import.inspect(dst) if ext == ".pdf" else dxf_import.inspect(dst)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Cannot read drawing: {e}")
    doc = {"id": did, "project_id": pid, "file": file.filename, "path": str(dst), "kind": ext[1:], "inspect": info}
    store.save_drawing(doc)
    return doc


class ImportReq(BaseModel):
    mapping: dict[str, str]                # layer (DXF) or style (PDF) -> meaning
    template: Optional[str] = None         # save mapping under this drawing-template name
    unit_to_m: Optional[float] = None
    known_dimension: Optional[dict] = None
    page: int = 0
    calibration: Optional[dict] = None     # PDF: {p1, p2, distance_m}
    verification: Optional[dict] = None    # PDF: second dimension
    view_frames: Optional[list[float]] = None


@app.post("/api/projects/{pid}/drawings/{did}/import")
def import_drawing(pid: str, did: str, req: ImportReq, _: str = Depends(writer)):
    p = _project(pid)
    d = store.get_drawing(did)
    if not d:
        raise HTTPException(404, "drawing not found")
    try:
        if d["kind"] == "pdf":
            if not req.calibration:
                raise HTTPException(400, "PDF import needs a calibration (two points + distance)")
            res = pdf_import.import_sections(d["path"], req.page, req.mapping, req.calibration, req.verification,
                                             p["frame_spacing_m"], req.view_frames)
            res.setdefault("obstructions", {})
        else:
            res = dxf_import.import_sections(d["path"], req.mapping, p["frame_spacing_m"], req.unit_to_m,
                                             req.known_dimension)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, str(e))
    if req.template:
        store.save_mapping(req.template, d["kind"], req.mapping)
    new = [s.model_dump() for s in res["sections"]]
    ids = {s["id"] for s in new}
    p["sections"] = [s for s in p["sections"] if s["id"] not in ids] + new
    for k, v in res["obstructions"].items():
        p.setdefault("obstructions_by_frame", {})[str(k)] = [o.model_dump() for o in v]
    store.save_project(p)
    d.update({"mapping": req.mapping, "report": res["report"], "template": req.template})
    store.save_drawing(d)
    return {"sections": new, "report": res["report"]}


@app.get("/api/mappings")
def mappings():
    return store.list_mappings()


@app.get("/api/drawings/{did}/page/{page}.png")
def drawing_page(did: str, page: int, zoom: float = 1.0):
    """Render a PDF page for click-calibration. 1 px = 1/zoom pt, so the UI converts clicks to PDF points."""
    import pymupdf
    d = store.get_drawing(did)
    if not d or d["kind"] != "pdf":
        raise HTTPException(404)
    pg = pymupdf.open(d["path"])[page]
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return Response(pix.tobytes("png"), media_type="image/png")


@app.get("/api/drawings/{did}/file")
def drawing_file(did: str):
    d = store.get_drawing(did)
    if not d:
        raise HTTPException(404)
    return FileResponse(d["path"], filename=d["file"])


# ------------------------------------------------------------------ sections / areas
@app.post("/api/projects/{pid}/sections")
def save_section(pid: str, sec: Section, _: str = Depends(writer)):
    p = _project(pid)
    p["sections"] = [s for s in p["sections"] if s["id"] != sec.id] + [sec.model_dump()]
    store.save_project(p)
    return sec


@app.post("/api/projects/{pid}/areas")
def save_area(pid: str, area: Area, _: str = Depends(writer)):
    p = _project(pid)
    p["areas"] = [a for a in p["areas"] if a["id"] != area.id] + [area.model_dump()]
    store.save_project(p)
    return area


@app.delete("/api/projects/{pid}/areas/{aid}")
def delete_area(pid: str, aid: str, _: str = Depends(writer)):
    p = _project(pid)
    p["areas"] = [a for a in p["areas"] if a["id"] != aid]
    store.save_project(p)
    return {"ok": True}


def resolve_area(p: dict, aid: str) -> tuple[Area, Optional[Section]]:
    ad = next((a for a in p["areas"] if a["id"] == aid), None)
    if not ad:
        raise HTTPException(404, "area not found")
    area = Area(**ad)
    sec = None
    if area.section_id:
        sd = next((s for s in p["sections"] if s["id"] == area.section_id), None)
        if not sd:
            raise HTTPException(400, f"section {area.section_id} not found in project")
        sec = Section(**sd)
        if area.use_drawing_obstructions:
            extra = [Obstruction(**o) for o in p.get("obstructions_by_frame", {}).get(str(sec.frame), [])]
            names = {o.name for o in area.obstructions}
            area = area.model_copy(update={"obstructions": area.obstructions + [o for o in extra if o.name not in names]})
    return area, sec


class RunReq(BaseModel):
    crew: int = 5
    systems: Optional[list[str]] = None


@app.post("/api/projects/{pid}/areas/{aid}/run")
def run(pid: str, aid: str, req: RunReq = RunReq(), _: str = Depends(role)):
    p = _project(pid)
    area, sec = resolve_area(p, aid)
    try:
        r = run_area(area, sec, bundle(), req.systems, req.crew)
    except ValueError as e:
        raise HTTPException(422, str(e))
    r["project_id"] = pid
    r["section"] = sec.model_dump() if sec else None
    store.save_run(pid, aid, r)
    return r


@app.post("/api/projects/{pid}/run-all")
def run_all(pid: str, req: RunReq = RunReq(), _: str = Depends(role)):
    p = _project(pid)
    out = {}
    for a in p["areas"]:
        out[a["id"]] = run(pid, a["id"], req)["run_id"]
    return out


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    r = store.get_run(rid)
    if not r:
        raise HTTPException(404)
    return r


class Rescore(BaseModel):
    weights: dict[str, float]


@app.post("/api/runs/{rid}/rescore")
def rescore(rid: str, body: Rescore):
    r = get_run(rid)
    return compare(r, bundle(), body.weights)


@app.get("/api/runs/{rid}/excel")
def run_excel(rid: str):
    r = get_run(rid)
    return Response(run_workbook(r), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="VSR_{r["snapshot"]["area"]["id"]}_{rid}.xlsx"'})


@app.get("/api/runs/{rid}/trace/{system}.csv")
def run_trace(rid: str, system: str):
    r = get_run(rid)
    if system not in r["results"]:
        raise HTTPException(404)
    return PlainTextResponse(trace_csv(r, system), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="trace_{system}_{rid}.csv"'})


@app.get("/api/projects/{pid}/summary")
def summary(pid: str):
    _project(pid)
    return vessel_summary(store.latest_runs(pid), bundle())


@app.get("/api/projects/{pid}/summary/excel")
def summary_excel(pid: str):
    p = _project(pid)
    s = vessel_summary(store.latest_runs(pid), bundle())
    return Response(summary_workbook(s, p), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="VSR_summary_{pid}.xlsx"'})


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
