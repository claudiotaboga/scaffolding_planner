"""Transparent per-area scoring and recommendation, with sensitivity. Works for N systems."""
from __future__ import annotations

from ..catalogue import DataBundle

CRITERIA = {
    "productivity": ("crew_hours_per_m2", "man-h/m2", "Erection effort"),
    "material": ("material_cost_eur", "EUR", "Material cost"),
    "safety": ("safety_index_h", "man-h exposure", "Safety exposure"),
    "fit": ("fit_count", "count", "Geometric fit"),
    "fleet_fit": (None, "score", "Fleet fit"),
}


def _raw(res: dict) -> dict:
    m = res["metrics"]
    return {
        "productivity": m["crew_hours_per_m2"]["value"],
        "material": m["material_cost_eur"]["value"],
        "safety": m["safety_index_h"]["value"],
        "fit": m["infill_units"]["value"] + m["gap_violations"]["value"],
    }


def score(raws: dict[str, dict], weights: dict, fleet: dict[str, float]) -> dict:
    systems = list(raws)
    norm: dict[str, dict] = {s: {} for s in systems}
    for c in ("productivity", "material", "safety"):
        vals = [raws[s][c] for s in systems]
        lo = min(vals)
        for s in systems:
            v = raws[s][c]
            norm[s][c] = 1.0 if v <= 0 or lo == v else (lo / v if v > 0 else 1.0)
    lo = min(raws[s]["fit"] for s in systems)
    for s in systems:
        norm[s]["fit"] = (1 + lo) / (1 + raws[s]["fit"])
        norm[s]["fleet_fit"] = fleet[s]
    wsum = sum(weights.values()) or 1.0
    total = {s: sum(weights[c] * norm[s][c] for c in weights) / wsum for s in systems}
    return {"norm": norm, "total": total}


def _winner(total: dict, eligible: list[str]) -> str:
    return max(eligible, key=lambda s: (round(total[s], 9), s))


def compare(run: dict, bundle: DataBundle, weights: dict | None = None) -> dict:
    res = run["results"]
    systems = list(res)
    sc = bundle.settings["scoring"]
    weights = weights or dict(sc["weights"])
    fleet = {s: (sc["fleet_fit_dominant"] if s == sc["dominant_system"] else sc["fleet_fit_other"]) for s in systems}
    raws = {s: _raw(res[s]) for s in systems}
    sco = score(raws, weights, fleet)
    eligible = [s for s in systems if res[s]["valid"]] or systems
    win = _winner(sco["total"], eligible)
    others = sorted([s for s in systems if s != win], key=lambda s: -sco["total"][s])
    runner = others[0] if others else None

    table = []
    for c, (metric, unit, label) in CRITERIA.items():
        row = {"criterion": c, "label": label, "unit": unit, "weight": weights.get(c, 0.0), "systems": {}}
        for s in systems:
            row["systems"][s] = {"raw": raws[s].get(c, fleet[s]), "normalised": round(sco["norm"][s][c], 4),
                                 "weighted": round(weights.get(c, 0) * sco["norm"][s][c] / (sum(weights.values()) or 1), 4)}
        table.append(row)

    out = {"weights": weights, "fleet_fit": fleet, "table": table,
           "totals": {s: round(sco["total"][s], 4) for s in systems},
           "eligible": eligible, "recommended": win, "runner_up": runner,
           "method": "normalised = best/value (lower-is-better); fit = (1+best)/(1+value); "
                     "total = sum(weight x normalised) / sum(weights). Systems with error-level violations are "
                     "ineligible unless all are."}
    if runner is None:
        out.update(margin_pct=None, reasons=[], sensitivity=[])
        return out
    tw, tr = sco["total"][win], sco["total"][runner]
    out["margin_pct"] = round((tw - tr) / tr * 100, 2) if tr else None

    # reasons: largest weighted contributions in favour of the winner
    contrib = []
    for c, (metric, unit, label) in CRITERIA.items():
        d = weights.get(c, 0) * (sco["norm"][win][c] - sco["norm"][runner][c])
        contrib.append((d, c, label, unit))
    contrib.sort(reverse=True)
    reasons = []
    for d, c, label, unit in contrib:
        if d <= 1e-9 or len(reasons) == 3:
            continue
        if c == "fleet_fit":
            reasons.append(f"{label}: {win} is the yard's dominant family (user-set fleet weight {weights[c]:.2f}).")
            continue
        a, b = raws[win][c], raws[runner][c]
        pct = (b - a) / b * 100 if b else 0
        fmt = (lambda x: f"{x:,.0f}") if c == "material" else (lambda x: f"{x:.3g}")
        reasons.append(f"{label}: {fmt(a)} vs {fmt(b)} {unit} for {runner} ({pct:.0f}% better).")
    if not res[runner]["valid"]:
        reasons.insert(0, f"{runner} has error-level rule violations on this area (see validation) and is not eligible.")
    out["reasons"] = reasons[:3]
    out["sensitivity"] = sensitivity(res, raws, weights, fleet, eligible, win)
    return out


def sensitivity(res, raws, weights, fleet, eligible, win) -> list[dict]:
    """Multiplier on one system's erection time (productivity + unsecured exposure) that flips the winner."""
    out = []

    def winner_with(s, f):
        r2 = {k: dict(v) for k, v in raws.items()}
        m = res[s]["metrics"]
        r2[s]["productivity"] = raws[s]["productivity"] * f
        r2[s]["safety"] = raws[s]["safety"] + (f - 1) * m["unsecured_exposure_h"]["value"]
        return _winner(score(r2, weights, fleet)["total"], eligible)

    for s in res:
        if s not in eligible:
            continue
        direction = "rises" if s == win else "drops"
        lo, hi = (1.0, 5.0) if s == win else (0.02, 1.0)
        flip_end = hi if s == win else lo
        if winner_with(s, flip_end) == win:
            out.append({"system": s, "flips": False,
                        "text": f"No flip: even if {s} erection time {direction} by "
                                f"{abs(flip_end - 1) * 100:.0f}%, the recommendation stays {win}."})
            continue
        a, b = lo, hi
        for _ in range(40):
            mid = (a + b) / 2
            flipped = winner_with(s, mid) != win
            if s == win:
                a, b = (a, mid) if flipped else (mid, b)
            else:
                a, b = (mid, b) if flipped else (a, mid)
        f = b if s == win else a
        pct = abs(f - 1) * 100
        out.append({"system": s, "flips": True, "multiplier": round(f, 4), "pct": round(pct, 1),
                    "text": f"The recommendation flips if {s} erection time {direction} by more than {pct:.1f}%."})
    return out
