"""Vessel / fleet summary over the latest run of each area: single-system policies vs mixed optimum."""
from __future__ import annotations

from ..catalogue import DataBundle


def vessel_summary(runs: dict[str, dict], bundle: DataBundle, areas_meta: dict[str, dict] | None = None) -> dict:
    if not runs:
        return {"areas": [], "policies": {}, "note": "No runs yet."}
    systems = sorted({s for r in runs.values() for s in r["results"]})
    fleet = bundle.settings["fleet"]
    complexity = fleet["complexity_cost_eur_per_year"] * fleet["vessel_build_months"] / 12.0
    rows = []
    for aid, r in runs.items():
        cmp_ = r["comparison"]
        row = {"area_id": aid, "name": r["snapshot"]["area"]["name"], "run_id": r["run_id"],
               "confidence": r["geometry_confidence"], "recommended": cmp_["recommended"],
               "margin_pct": cmp_.get("margin_pct"), "systems": {}}
        for s, res in r["results"].items():
            m = res["metrics"]
            row["systems"][s] = {"crew_hours": m["crew_hours"]["value"], "weight_t": m["weight_t"]["value"],
                                 "total_cost_eur": m["total_cost_eur"]["value"], "area_m2": m["area_m2"]["value"],
                                 "infill_units": m["infill_units"]["value"], "valid": res["valid"],
                                 "estimate_weight_share": m["estimate_weight_share"]["value"]}
        rows.append(row)

    def policy(choose) -> dict:
        tot = {"crew_hours": 0.0, "peak_t": 0.0, "cost_eur": 0.0, "infill_units": 0, "invalid_areas": 0,
               "area_m2_by_system": {s: 0.0 for s in systems}}
        for row in rows:
            s = choose(row)
            if s not in row["systems"]:
                continue
            v = row["systems"][s]
            tot["crew_hours"] += v["crew_hours"]
            tot["peak_t"] += v["weight_t"]
            tot["cost_eur"] += v["total_cost_eur"]
            tot["infill_units"] += v["infill_units"]
            tot["invalid_areas"] += 0 if v["valid"] else 1
            tot["area_m2_by_system"][s] += v["area_m2"]
        return tot

    pols = {f"100% {s}": policy(lambda row, s=s: s) for s in systems}
    mixed = policy(lambda row: row["recommended"])
    used = [s for s, a in mixed["area_m2_by_system"].items() if a > 0]
    mixed["complexity_cost_eur"] = complexity if len(used) > 1 else 0.0
    mixed["cost_eur"] += mixed["complexity_cost_eur"]
    pols["Mixed optimum"] = mixed
    for p in pols.values():
        p.setdefault("complexity_cost_eur", 0.0)
        tot_a = sum(p["area_m2_by_system"].values()) or 1
        p["share_by_system"] = {s: round(a / tot_a, 4) for s, a in p["area_m2_by_system"].items()}
    best = min(pols, key=lambda k: pols[k]["cost_eur"])
    return {"systems": systems, "areas": rows, "policies": pols, "cheapest_policy": best,
            "assumptions": {"complexity_cost_eur_per_year": fleet["complexity_cost_eur_per_year"],
                            "vessel_build_months": fleet["vessel_build_months"],
                            "complexity_cost_applied_eur": complexity,
                            "peak_t": "sum of all areas standing simultaneously (upper bound; schedule-based peak in phase 4)"},
            "disclaimer": bundle.settings["disclaimer"]}
