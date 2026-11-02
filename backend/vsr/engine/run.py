"""Run one area for one or more systems: layout -> items -> BoM -> validation -> simulation -> metrics.

Every metric is returned as {value, unit, formula, inputs} so any number in a report can be traced
back to an area input, catalogue entry, time-standard version or setting.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import defaultdict
from typing import Optional

from shapely.geometry import LineString, box

from ..catalogue import Catalogue, DataBundle
from ..geometry.hull import Hull
from ..models import Area, Section
from .bom import aggregate_bom, generate_items
from .layout import Layout, Violation, _add_infills, generate_layout
from .simulate import add_infill_time, simulate


def M(value, unit, formula, **inputs) -> dict:
    if isinstance(value, float):
        value = round(value, 4)
    return {"value": value, "unit": unit, "formula": formula, "inputs": inputs}


def validate(lay: Layout, cat: Catalogue, area: Area, section: Optional[Section]) -> list[Violation]:
    v: list[Violation] = []
    # load class per bay length
    lc = cat.rules["load_class_by_bay"]
    for L in sorted(set(lay.bays)):
        cls = int(lc.value[f"{L:.2f}"])
        if cls < area.load_class:
            v.append(Violation(rule="load_class", severity="error",
                               message=f"Bay {L:.2f} m rated class {cls} < required class {area.load_class}",
                               ref={"rule": "load_class_by_bay", "status": lc.status, "source": lc.source}))
    # anchorage
    H = cat.lift_height_m * lay.n_lifts
    if area.anchorage == "free_standing":
        base = sum(lay.widths)
        ratio = float(cat.rule("free_standing_max_height_to_base"))
        if H / base > ratio + 1e-9:
            v.append(Violation(rule="free_standing_ratio", severity="error",
                               message=f"Free-standing H/base = {H:.1f}/{base:.2f} = {H/base:.2f} > {ratio:.1f}: "
                                       f"needs ties, outriggers or ballast",
                               ref={"rule": "free_standing_max_height_to_base"}))
    if area.anchorage == "suspended":
        v.append(Violation(rule="suspended", severity="error",
                           message="Suspended scaffolds are not modelled in the MVP — result not valid"))
    # mixing brands: the generator only draws from one catalogue + tube&coupler infill
    # gaps
    for lp in lay.lifts:
        if lp.status == "infill":
            v.append(Violation(rule="gap", severity="warning", message=f"Lift {lp.k}: {lp.reason}"))
    if lay.longitudinal_infill:
        v.append(Violation(rule="run_fill", severity="warning",
                           message=f"Run residual {lay.run_residual_m:.2f} m > tolerance at bounded end: "
                                   f"longitudinal infill on {lay.n_lifts} lifts"))
    # obstruction clashes — always checked, never ignored (avoid mode only moves the layout)
    if area.obstructions:
        hull = Hull(section, area.obstructions)
        y_outer = lay.line_y[0]
        for j, y in enumerate(lay.line_y):
            top = area.z_base + cat.lift_height_m * lay.line_top_lift[j] + 1.0
            hit = hull.clashes(LineString([(y, area.z_base), (y, top)]))
            for name in hit:
                v.append(Violation(rule="clash", severity="error",
                                   message=f"Standard line {j} (y={y:.2f}) clashes with obstruction '{name}'",
                                   ref={"obstruction": name}))
        for lp in lay.lifts:
            edge = lp.edge_y if lp.edge_y is not None else lay.line_y[lp.inner_line]
            deck = box(min(edge, y_outer), lp.z_deck - 0.10, max(edge, y_outer), lp.z_deck + 1.0)
            for name in hull.clashes(deck):
                v.append(Violation(rule="clash", severity="error",
                                   message=f"Lift {lp.k} platform/guardrail zone clashes with obstruction '{name}'",
                                   ref={"obstruction": name}))
    return v


def run_system(area: Area, section: Optional[Section], cat: Catalogue, bundle: DataBundle, crew: int = 5) -> dict:
    ts = bundle.time_standard_for(cat.system_id)
    common = bundle.common
    settings = bundle.settings
    lay = generate_layout(area, cat, section, common)
    items, v_items, extra = generate_items(lay, cat, area, common)
    bom = aggregate_bom(items, lay, cat, common)
    lay.violations += v_items + validate(lay, cat, area, section)
    sim = simulate(items, ts, crew)
    units_by_lift: dict[int, int] = defaultdict(int)
    for inf in lay.infills:
        units_by_lift[inf.lift] += inf.units
    sim = add_infill_time(sim, dict(units_by_lift), ts)

    # ---- metrics
    weight = sum(b.total_weight_kg for b in bom)
    est_w = sum(b.total_weight_kg for b in bom if b.status == "estimate")
    H = cat.lift_height_m * lay.n_lifts
    area_m2 = lay.run_target_m * H
    nodes = extra["nodes"]
    t_wedge = ts.actions["secure_wedge"]
    infill_units = lay.infill_units()
    couplers = sum(i.couplers for i in lay.infills)
    infill_h = infill_units * ts.infill_crew_hours_per_unit
    costs = settings["costs"]
    sc = costs["per_system"].get(cat.system_id, costs["default"])
    t = weight / 1000.0
    rental = t * sc["rental_eur_per_t_month"] * area.rental_months
    purchase = t * sc["purchase_eur_per_t"]
    lab_rate = costs["labour_eur_per_man_h"]["value"]
    labour_h = sim.crew_hours * (1 + ts.dismantle_factor)
    labour = labour_h * lab_rate
    trucks = math.ceil(t / costs["t_per_truck"]["value"] - 1e-9) if t > 0 else 0
    transport = trucks * 2 * costs["truck_eur"]["value"]
    basis = costs.get("cost_basis", "rental")
    material_cost = (rental if basis == "rental" else purchase) + transport
    unsecured_h = nodes * t_wedge / 3600
    unprot_noagr = sim.unprotected_exposure_if_no_agr_h
    unprot = 0.0 if area.advance_guardrail else unprot_noagr
    safety_idx = unsecured_h + infill_h + unprot
    gap_viol = sum(1 for lp in lay.lifts if lp.status == "infill") + (lay.n_lifts if lay.longitudinal_infill else 0)
    tsv = ts.version_stamp()
    catv = cat.version_stamp()

    metrics = {
        "weight_kg": M(weight, "kg", "sum(BoM qty x unit weight)", bom="bom", catalogue=catv),
        "weight_t": M(t, "t", "weight_kg / 1000", weight_kg="weight_kg"),
        "estimate_weight_share": M(est_w / weight if weight else 0.0, "ratio",
                                   "weight of `estimate` components / total weight", bom="bom"),
        "area_m2": M(area_m2, "m2", "run_target x lift_height x n_lifts", run_target=lay.run_target_m,
                     lift_height=cat.lift_height_m, n_lifts=lay.n_lifts, area=area.id),
        "crew_hours": M(sim.crew_hours, "man-h", "sum(action qty x man-seconds) / 3600 + infill units x crew-h/unit",
                        time_standard=tsv, items="trace"),
        "elapsed_h": M(sim.elapsed_min / 60, "h", "crew_hours / (crew x efficiency(crew))", crew=crew,
                       efficiency=sim.crew_efficiency, time_standard=tsv),
        "elapsed_min": M(sim.elapsed_min, "min", "crew_hours x 60 / (crew x efficiency)", crew=crew, time_standard=tsv),
        "crew_hours_per_m2": M(sim.crew_hours / area_m2 if area_m2 else 0.0, "man-h/m2", "crew_hours / area_m2",
                               crew_hours="crew_hours", area_m2="area_m2"),
        "m2_per_man_hour": M(area_m2 / sim.crew_hours if sim.crew_hours else 0.0, "m2/man-h", "area_m2 / crew_hours",
                             crew_hours="crew_hours", area_m2="area_m2"),
        "kg_per_m2": M(weight / area_m2 if area_m2 else 0.0, "kg/m2", "weight_kg / area_m2",
                       weight_kg="weight_kg", area_m2="area_m2"),
        "nodes": M(nodes, "count", "distinct node positions with >=1 connection", layout="layout"),
        "wedges": M(sim.wedges, "count", "sum(connection ends of ledgers, transoms, guardrails, diagonals, brackets)",
                    items="trace"),
        "infill_units": M(infill_units, "count", "longitudinal: 1 per lift; transverse: 1 per bay per lift",
                          layout="layout", common=common["version"]),
        "infill_couplers": M(couplers, "count", "infill tubes x couplers per tube", common=common["version"]),
        "infill_crew_hours": M(infill_h, "man-h", "infill_units x infill_crew_hours_per_unit",
                               infill_crew_hours_per_unit=ts.infill_crew_hours_per_unit, time_standard=tsv),
        "ties": M(extra.get("ties", 0), "count", "ceil(run_covered x height / tie_area_m2)",
                  tie_area_m2=cat.rule("tie_area_m2"), anchorage=area.anchorage),
        "unsecured_exposure_h": M(unsecured_h, "man-h", "nodes x secure_wedge seconds / 3600",
                                  nodes="nodes", secure_wedge_s=t_wedge, time_standard=tsv),
        "unprotected_exposure_h": M(unprot, "man-h", "0 if advance guardrail modelled else deck+guardrail time on lifts >=1",
                                    advance_guardrail=area.advance_guardrail),
        "unprotected_exposure_if_no_agr_h": M(unprot_noagr, "man-h", "deck + guardrail placement time on lifts >= 1",
                                              time_standard=tsv),
        "safety_index_h": M(safety_idx, "man-h", "unsecured_exposure_h + infill_crew_hours + unprotected_exposure_h",
                            unsecured_exposure_h="unsecured_exposure_h", infill_crew_hours="infill_crew_hours",
                            unprotected_exposure_h="unprotected_exposure_h"),
        "gap_violations": M(gap_viol, "count", "lifts needing transverse infill + lifts with longitudinal infill",
                            layout="layout"),
        "rental_eur": M(rental, "EUR", "weight_t x rental EUR/t/month x months",
                        rate=sc["rental_eur_per_t_month"], months=area.rental_months, status=sc["status"],
                        settings=settings["version"]),
        "purchase_eur": M(purchase, "EUR", "weight_t x purchase EUR/t", rate=sc["purchase_eur_per_t"],
                          status=sc["status"], settings=settings["version"]),
        "labour_eur": M(labour, "EUR", "crew_hours x (1 + dismantle_factor) x EUR/man-h",
                        dismantle_factor=ts.dismantle_factor, rate=lab_rate, settings=settings["version"]),
        "transport_eur": M(transport, "EUR", "ceil(weight_t / t_per_truck) x 2 trips x EUR/truck",
                           trucks=trucks, settings=settings["version"]),
        "material_cost_eur": M(material_cost, "EUR", f"{basis} + transport", basis=basis,
                               rental_eur="rental_eur", purchase_eur="purchase_eur", transport_eur="transport_eur"),
        "total_cost_eur": M(material_cost + labour, "EUR", "material_cost_eur + labour_eur",
                            material_cost_eur="material_cost_eur", labour_eur="labour_eur"),
    }
    errors = [x for x in lay.violations if x.severity == "error"]
    return {
        "system_id": cat.system_id, "system_name": cat.name,
        "layout": lay.model_dump(), "bom": [b.model_dump() for b in bom],
        "simulation": sim.model_dump(), "metrics": metrics,
        "valid": not errors, "versions": {"catalogue": catv, "time_standard": tsv},
    }


def snapshot_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def run_area(area: Area, section: Optional[Section], bundle: DataBundle, systems: Optional[list[str]] = None,
             crew: int = 5) -> dict:
    from .compare import compare
    systems = systems or sorted(bundle.catalogues)
    eng_section = section
    eng_area = area
    if section is not None and area.face == "inboard":
        # engine works with the scaffold on the +y side of the surface; mirror inboard faces
        eng_section = section.mirrored()
        eng_area = area.model_copy(update={"obstructions": [o.model_copy(update={"points": [(-y, z) for y, z in o.points]})
                                                            for o in area.obstructions]})
    results = {s: run_system(eng_area, eng_section, bundle.catalogues[s], bundle, crew) for s in systems}
    for r in results.values():
        r["layout"]["mirrored"] = eng_section is not section
    conf = section.confidence if section is not None else ("high" if area.area_type == "tower" else "low")
    snapshot = {
        "area": area.model_dump(),
        "geometry": {"section_id": section.id if section else None,
                     "frame": section.frame if section else None,
                     "source": section.source if section else "none",
                     "source_file": section.source_file if section else None,
                     "hash": section.geometry_hash() if section else None, "confidence": conf},
        "versions": {s: results[s]["versions"] for s in systems},
        "settings": {"version": bundle.settings["version"], "sha256": bundle.settings["sha256"]},
        "common": {"version": bundle.common["version"], "sha256": bundle.common["sha256"]},
        "crew": crew,
    }
    run = {
        "run_id": snapshot_hash(snapshot),
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "snapshot": snapshot,
        "geometry_confidence": conf,
        "results": results,
        "disclaimer": bundle.settings["disclaimer"],
    }
    run["comparison"] = compare(run, bundle)
    return run
