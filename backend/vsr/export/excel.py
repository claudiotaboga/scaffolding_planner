"""Excel export (openpyxl): per-area run workbook and vessel summary workbook.
Estimate weights are highlighted; every sheet carries versions and the disclaimer."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

EST = PatternFill("solid", fgColor="FFF2CC")
BAD = PatternFill("solid", fgColor="F8CBAD")
HDR = Font(bold=True)


def _sheet(wb, title, header, rows, widths=None):
    ws = wb.create_sheet(title[:31])
    ws.append(header)
    for c in ws[1]:
        c.font = HDR
    for r in rows:
        ws.append(r)
    for i, h in enumerate(header, 1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(i, max(12, min(60, len(str(h)) + 4)))
    ws.freeze_panes = "A2"
    return ws


def run_workbook(run: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    snap = run["snapshot"]
    cmp_ = run["comparison"]
    ws.append(["VSR Scaffold Planner — area comparison"])
    ws["A1"].font = Font(bold=True, size=14)
    for k, v in [("Area", snap["area"]["name"]), ("Area id", snap["area"]["id"]), ("Run id", run["run_id"]),
                 ("Created (UTC)", run["created"]), ("Geometry confidence", run["geometry_confidence"]),
                 ("Geometry source", f"{snap['geometry']['source']} {snap['geometry'].get('source_file') or ''}"),
                 ("Crew", snap["crew"]), ("Recommended", cmp_["recommended"]), ("Margin %", cmp_.get("margin_pct")),
                 ("Settings version", f"{snap['settings']['version']} ({snap['settings']['sha256']})")]:
        ws.append([k, v])
    ws.append([])
    ws.append(["Reasons"])
    for r in cmp_.get("reasons", []):
        ws.append(["", r])
    ws.append(["Sensitivity"])
    for s in cmp_.get("sensitivity", []):
        ws.append(["", s["text"]])
    ws.append([])
    ws.append(["Versions"])
    for s, v in snap["versions"].items():
        ws.append([s, f"catalogue {v['catalogue']['catalogue_version']} ({v['catalogue']['sha256']}), "
                      f"{v['catalogue']['estimates']} estimate items",
                   f"time standard {v['time_standard']['version']} [{v['time_standard']['status']}] ({v['time_standard']['sha256']})"])
    ws.append([])
    ws.append(["DISCLAIMER", run["disclaimer"]])
    ws["B" + str(ws.max_row)].alignment = Alignment(wrap_text=True)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 90
    ws.column_dimensions["C"].width = 60

    systems = list(run["results"])
    # comparison table
    rows = []
    for row in cmp_["table"]:
        r = [row["label"], row["unit"], row["weight"]]
        for s in systems:
            v = row["systems"][s]
            r += [v["raw"], v["normalised"], v["weighted"]]
        rows.append(r)
    rows.append(["TOTAL", "", ""] + sum([["", "", cmp_["totals"][s]] for s in systems], []))
    _sheet(wb, "Scoring", ["Criterion", "Unit", "Weight"] + sum([[f"{s} raw", f"{s} norm", f"{s} weighted"] for s in systems], []), rows)
    # metrics with trace
    mrows = []
    for name in run["results"][systems[0]]["metrics"]:
        r = [name, run["results"][systems[0]]["metrics"][name]["unit"]]
        for s in systems:
            r.append(run["results"][s]["metrics"][name]["value"])
        r.append(run["results"][systems[0]]["metrics"][name]["formula"])
        mrows.append(r)
    _sheet(wb, "Metrics", ["Metric", "Unit"] + systems + ["Formula / trace"], mrows, {len(systems) + 3: 80})
    for s in systems:
        res = run["results"][s]
        ws_b = _sheet(wb, f"BoM {s}", ["Code", "Description", "Role", "Qty", "Unit kg", "Total kg", "Status", "Source",
                                       "Catalogue", "Version"],
                      [[b["code"], b["name"], b["role"], b["qty"], b["unit_weight_kg"], b["total_weight_kg"], b["status"],
                        b["source"], b["catalogue"], b["catalogue_version"]] for b in res["bom"]], {2: 40, 8: 50})
        for row in ws_b.iter_rows(min_row=2):
            if row[6].value == "estimate":
                for c in row:
                    c.fill = EST
        ws_b.append([])
        ws_b.append(["TOTAL", "", "", "", "", round(sum(b["total_weight_kg"] for b in res["bom"]), 2)])
        ws_b.append(["Rows highlighted = weight status `estimate` (not verified)."])
        lay = res["layout"]
        lrows = [[lp["k"], lp["z_deck"], lp["status"], lp["gap_m"], lp["bracket_m"], len(lp["lines_present"]),
                  lp.get("infill_width_m"), lp["reason"]] for lp in lay["lifts"]]
        ws_l = _sheet(wb, f"Layout {s}", ["Lift", "Deck z (m)", "Status", "Gap (m)", "Bracket (m)", "Lines", "Infill (m)",
                                         "Reason"], lrows, {8: 90})
        for row in ws_l.iter_rows(min_row=2):
            if row[2].value == "infill":
                for c in row:
                    c.fill = BAD
        ws_l.append([])
        ws_l.append(["Bays", ", ".join(f"{b:.2f}" for b in lay["bays"])])
        ws_l.append(["Widths", ", ".join(f"{w:.2f}" for w in lay["widths"])])
        for e in lay["explanation"]:
            ws_l.append(["", e])
        _sheet(wb, f"Rules {s}", ["Rule", "Severity", "Message"],
               [[v["rule"], v["severity"], v["message"]] for v in lay["violations"]], {3: 100})
        _sheet(wb, f"Trace {s}", ["Seq", "Lift", "Phase", "Action", "Code", "Qty", "Man-s each", "Man-s", "Cum crew-h",
                                  "Cum elapsed min", "Note"],
               [[t["seq"], t["lift"], t["phase"], t["action"], t["code"], t["qty"], t["man_s_each"], t["man_s"],
                 t["cum_crew_h"], t["cum_elapsed_min"], t["note"]] for t in res["simulation"]["steps"]])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def summary_workbook(summary: dict, project: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Vessel summary"
    ws.append([f"VSR Scaffold Planner — vessel summary: {project['name']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(["Policy", "Crew-hours", "Peak t (upper bound)", "Cost EUR", "Complexity EUR", "Infill units",
               "Areas with rule violations"] + [f"share {s}" for s in summary["systems"]])
    for c in ws[3]:
        c.font = HDR
    for name, p in summary["policies"].items():
        ws.append([name, round(p["crew_hours"], 1), round(p["peak_t"], 2), round(p["cost_eur"]), round(p["complexity_cost_eur"]),
                   p["infill_units"], p["invalid_areas"]] + [p["share_by_system"][s] for s in summary["systems"]])
    ws.append([])
    ws.append(["Cheapest policy", summary["cheapest_policy"]])
    ws.append(["Peak tonnage", summary["assumptions"]["peak_t"]])
    ws.append(["DISCLAIMER", summary["disclaimer"]])
    ws.column_dimensions["A"].width = 26
    rows = []
    for a in summary["areas"]:
        r = [a["area_id"], a["name"], a["confidence"], a["recommended"], a["margin_pct"]]
        for s in summary["systems"]:
            v = a["systems"].get(s, {})
            r += [v.get("crew_hours"), v.get("weight_t"), v.get("total_cost_eur"), v.get("infill_units")]
        rows.append(r)
    _sheet(wb, "Areas", ["Area", "Name", "Confidence", "Recommended", "Margin %"] +
           sum([[f"{s} crew-h", f"{s} t", f"{s} EUR", f"{s} infills"] for s in summary["systems"]], []), rows, {2: 40})
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def trace_csv(run: dict, system: str) -> str:
    import csv
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["run_id", "system", "time_standard", "seq", "lift", "phase", "action", "code", "qty", "man_s_each",
                "man_s", "cum_crew_h", "cum_elapsed_min", "note"])
    res = run["results"][system]
    tsv = res["versions"]["time_standard"]["version"]
    for t in res["simulation"]["steps"]:
        w.writerow([run["run_id"], system, tsv, t["seq"], t["lift"], t["phase"], t["action"], t["code"], t["qty"],
                    t["man_s_each"], t["man_s"], t["cum_crew_h"], t["cum_elapsed_min"], t["note"]])
    return out.getvalue()
