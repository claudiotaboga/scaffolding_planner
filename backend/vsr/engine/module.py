"""Module comparison card: two (or more) systems at one fixed bay x width module, on a straight
reference facade. Everything is computed from the catalogues and time standards — no hard-coded figures."""
from __future__ import annotations

from typing import Optional

from ..catalogue import Catalogue, DataBundle
from ..models import Area
from .run import run_system

DEFAULT_MODULES = {"SM8": (2.50, 1.14), "LAYHER_LW": (2.57, 1.09)}


def _area(bays: int, lifts: int, L: float, W: float) -> Area:
    return Area(id="MODULE", name=f"Reference facade {bays} bays x {lifts} lifts", area_type="tower",
                tower_bays=bays, tower_bay_target_m=L, tower_width_target_m=W, n_lifts=lifts, z_base=0.0,
                z_top=2.0 * lifts + 2.0, anchorage="tied", protection="outer", advance_guardrail=True)


def _part(cat: Catalogue, role: str, length: Optional[float] = None) -> Optional[dict]:
    if not cat.has_part(role, length):
        return None
    c = cat.part(role, length)
    return {"code": c.code, "name": c.name, "weight_kg": c.weight_kg, "status": c.status}


def module_card(bundle: DataBundle, modules: Optional[dict] = None, bays: int = 10, lifts: int = 4,
                crew: int = 5) -> dict:
    modules = modules or DEFAULT_MODULES
    systems = [s for s in modules if s in bundle.catalogues]
    if len(systems) < 2:
        raise ValueError("Module card needs at least two systems present in the catalogues")
    out: dict = {"bays": bays, "lifts": lifts, "crew": crew, "systems": {}, "disclaimer": bundle.settings["disclaimer"]}
    for s in systems:
        cat = bundle.catalogues[s]
        L, W = modules[s]
        res = run_system(_area(bays, lifts, L, W), None, cat, bundle, crew)
        res1 = run_system(_area(bays + 1, lifts, L, W), None, cat, bundle, crew)
        lay = res["layout"]
        Lc, Wc = lay["bays"][0], lay["widths"][0]
        m, m1 = res["metrics"], res1["metrics"]
        nd = int(cat.map_rule("decks_per_width", Wc))
        deck = cat.part("deck", Lc)
        lc = cat.rules["load_class_by_bay"]
        pieces = sum(b["qty"] for b in res["bom"])
        out["systems"][s] = {
            "name": cat.name, "bay_m": Lc, "width_m": Wc, "requested": [L, W],
            "deck_area_m2": round(Lc * Wc, 3), "decks_across": nd, "deck_width_m": deck.width_m,
            "deck_coverage": round(nd * (deck.width_m or 0) / Wc, 3),
            "load_class": int(lc.value[f"{Lc:.2f}"]), "load_class_status": lc.status,
            "node": cat.node, "max_gap_m": cat.rule("max_gap_without_bracket_m"),
            "components": {
                "Standard 2.0 m": _part(cat, "standard", 2.0),
                f"Ledger (bay)": _part(cat, "ledger", Lc),
                f"Ledger / transom (width)": _part(cat, "ledger", Wc),
                "Steel deck (bay)": _part(cat, "deck", Lc),
                "Diagonal (bay)": _part(cat, "diagonal", Lc),
                "Toe board (bay)": _part(cat, "toe_board", Lc),
                "Hatch deck": _part(cat, "hatch") if cat.hatch else None,
            },
            "facade": {k: m[k]["value"] for k in ("area_m2", "weight_kg", "weight_t", "kg_per_m2", "crew_hours",
                                                  "elapsed_min", "m2_per_man_hour", "nodes", "wedges",
                                                  "unsecured_exposure_h", "unprotected_exposure_if_no_agr_h",
                                                  "total_cost_eur", "estimate_weight_share")},
            "pieces": pieces,
            "cost_eur_per_m2": round(m["total_cost_eur"]["value"] / m["area_m2"]["value"], 2),
            "marginal_bay": {"weight_kg": round(m1["weight_kg"]["value"] - m["weight_kg"]["value"], 2),
                             "crew_hours": round(m1["crew_hours"]["value"] - m["crew_hours"]["value"], 4)},
            "versions": res["versions"], "valid": res["valid"],
            "violations": [v["message"] for v in lay["violations"] if v["severity"] == "error"],
        }
    a, b = systems[0], systems[1]
    A, B = out["systems"][a], out["systems"][b]

    def d(x, y):   # relative change of B vs A
        return round((y - x) / x * 100, 1) if x else None

    out["deltas"] = {"base": a, "other": b,
                     "kg_per_m2_pct": d(A["facade"]["kg_per_m2"], B["facade"]["kg_per_m2"]),
                     "m2_per_man_hour_pct": d(A["facade"]["m2_per_man_hour"], B["facade"]["m2_per_man_hour"]),
                     "crew_hours_per_m2_pct": d(A["facade"]["crew_hours"] / A["facade"]["area_m2"],
                                                B["facade"]["crew_hours"] / B["facade"]["area_m2"]),
                     "cost_per_m2_pct": d(A["cost_eur_per_m2"], B["cost_eur_per_m2"]),
                     "marginal_bay_crew_hours_pct": d(A["marginal_bay"]["crew_hours"], B["marginal_bay"]["crew_hours"]),
                     "same_topology": (A["pieces"], A["facade"]["nodes"], A["facade"]["wedges"]) ==
                                      (B["pieces"], B["facade"]["nodes"], B["facade"]["wedges"])}
    out["verdict"] = _verdict(out, a, b)
    return out


def _verdict(card: dict, a: str, b: str) -> dict:
    A, B, D = card["systems"][a], card["systems"][b], card["deltas"]
    faster = b if D["crew_hours_per_m2_pct"] < 0 else a
    lighter = b if D["kg_per_m2_pct"] < 0 else a
    cheaper = b if D["cost_per_m2_pct"] < 0 else a
    est = {s: card["systems"][s]["facade"]["estimate_weight_share"] for s in (a, b)}
    ts = {s: card["systems"][s]["versions"]["time_standard"]["status"] for s in (a, b)}
    lines = []
    if D["same_topology"]:
        lines.append("Same structure: identical piece, node and wedge counts — the difference comes only from unit "
                     "weights and time standards.")
    lines.append(f"{card['systems'][faster]['name']} is faster: {abs(D['crew_hours_per_m2_pct']):.0f}% fewer "
                 f"man-hours per m² (time standard status: {ts[faster]}).")
    lines.append(f"{card['systems'][lighter]['name']} is lighter: {abs(D['kg_per_m2_pct']):.0f}% less kg per m²"
                 + (f" — {est[lighter] * 100:.0f}% of its weight is estimated." if est[lighter] > 0.2 else "."))
    lines.append(f"{card['systems'][cheaper]['name']} is cheaper: {abs(D['cost_per_m2_pct']):.0f}% per m² "
                 f"(1-month rental + labour + transport).")
    checks = []
    for s in (a, b):
        if est[s] > 0.2:
            checks.append(f"Load the current {card['systems'][s]['name']} price list: {est[s] * 100:.0f}% of its "
                          f"weight is estimated.")
    if any(v.startswith("provisional") for v in ts.values()):
        checks.append("Re-run the reference tower to the Annex A protocol (3 runs per system, phase timestamps, "
                      "same crew) to confirm the time difference and where it comes from.")
    for s in (a, b):
        if card["systems"][s]["load_class_status"] == "estimate":
            checks.append(f"Confirm {card['systems'][s]['name']} load class {card['systems'][s]['load_class']} at "
                          f"{card['systems'][s]['bay_m']:.2f} m bays against the approval.")
    headline = (f"On a straight façade, {card['systems'][faster]['name']} leads at this module"
                + (" on speed, weight and cost." if faster == lighter == cheaper else
                   f"; {card['systems'][lighter]['name']} is lighter, {card['systems'][cheaper]['name']} cheaper."))
    return {"headline": headline, "faster": faster, "lighter": lighter, "cheaper": cheaper, "lines": lines,
            "checks": checks,
            "scope_note": "Module level only. Hull fit (infills on curved shell and flare) is assessed per area: "
                          "Layher's finer grid wins on moderate curvature; SM8's longer brackets help on strong flare."}
