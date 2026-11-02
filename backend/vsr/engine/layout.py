"""Layout generation for one area and one system (2D section, prismatic over the run).

Two independent, exact sub-problems:
  * Longitudinal (along X): fill the run with bays from the system grid (DP at 1 cm).
    Posts are continuous standards, so the same bay sequence applies to every lift.
  * Transverse (section Y-Z): choose outer line position, base platform width and optional
    stepped inner lines (for flare), then per lift the bracket that brings the deck edge within
    [gap_min, max_gap] of the hull. Where no combination fits -> tube-and-coupler infill.
Nothing is silently fixed: every infill / violation is recorded with the reason.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
from typing import Literal, Optional

from pydantic import BaseModel

from ..catalogue import Catalogue
from ..geometry.hull import Hull
from ..models import Area, Section

EPS = 1e-6


class LiftPlan(BaseModel):
    k: int
    z_deck: float
    lines_present: list[int]
    inner_line: int
    decked: bool
    hull_y: Optional[float] = None
    edge_y: Optional[float] = None
    bracket_m: Optional[float] = None
    bracket_code: Optional[str] = None
    gap_m: Optional[float] = None          # deck edge to hull at deck level (after bracket, before infill)
    status: Literal["ok", "bracket", "infill", "open"] = "ok"
    infill_width_m: Optional[float] = None
    reason: str = ""


class Infill(BaseModel):
    kind: Literal["longitudinal", "transverse"]
    lift: int
    size_m: float
    units: int                 # infill units (crew-hour basis)
    tubes: int
    tube_length_m: float
    couplers: int
    reason: str


class Violation(BaseModel):
    rule: str
    severity: Literal["error", "warning", "info"]
    message: str
    ref: dict = {}


class Layout(BaseModel):
    system_id: str
    mode: Literal["section", "tower"]
    bays: list[float]
    run_target_m: float
    run_covered_m: float
    run_residual_m: float
    run_start: str
    run_end: str
    longitudinal_infill: bool
    widths: list[float]                    # outer -> inner
    line_y: list[float]                    # y of each standard line (outer first)
    line_top_lift: list[int]
    n_lifts: int
    z_base: float
    lifts: list[LiftPlan]
    infills: list[Infill] = []
    violations: list[Violation] = []
    objective: dict = {}
    search: dict = {}
    explanation: list[str] = []

    @property
    def n_bays(self) -> int:
        return len(self.bays)

    def infill_units(self) -> int:
        return sum(i.units for i in self.infills)


# ---------------------------------------------------------------------------------------------
# Longitudinal fill
# ---------------------------------------------------------------------------------------------
def fill_run(L: float, grid: list[float], start_bounded: bool, end_bounded: bool, tol: float,
             overhang: float) -> tuple[list[float], float, bool, str]:
    """Return (bays, residual, needs_infill, explanation). Exact DP on 1 cm units.

    Objective: fewest bays, then closest to L. Both ends bounded -> sum in [L-tol, L]; else
    sum in [L-tol, L+overhang]. If the window is empty with bounded ends -> longest sum <= L and
    a longitudinal infill closes the residual.
    """
    cm = lambda x: int(round(x * 100))
    Lc, tc, oc = cm(L), cm(tol), cm(overhang)
    g = sorted({cm(x) for x in grid}, reverse=True)
    both = start_bounded and end_bounded
    maxc = Lc if both else Lc + oc
    INF = 10 ** 9
    best = [INF] * (maxc + 1)
    prev = [0] * (maxc + 1)
    best[0] = 0
    for s in range(maxc + 1):
        if best[s] == INF:
            continue
        for b in g:                      # longer bays first -> deterministic tie-break
            t = s + b
            if t <= maxc and best[s] + 1 < best[t]:
                best[t] = best[s] + 1
                prev[t] = b
    lo = max(0, Lc - tc)
    window = [s for s in range(lo, maxc + 1) if best[s] < INF]
    infill = False
    if window:
        s_star = min(window, key=lambda s: (best[s], abs(s - Lc)))
        why = (f"{best[s_star]} bays, sum {s_star/100:.2f} m vs run {L:.2f} m "
               f"({'both ends bounded' if both else 'free end allowed'}; tolerance {tol:.2f} m)")
    else:
        reach = [s for s in range(0, maxc + 1) if best[s] < INF]
        if both or not reach:
            s_star = max(reach) if reach else 0
            infill = (Lc - s_star) > tc
            why = (f"grid cannot close {L:.2f} m within {tol:.2f} m; best sum {s_star/100:.2f} m leaves "
                   f"{(Lc - s_star)/100:.2f} m -> longitudinal infill")
        else:
            s_star = max(reach)
            why = f"free end: longest reachable sum {s_star/100:.2f} m within overhang"
    bays = []
    s = s_star
    while s > 0:
        bays.append(prev[s] / 100)
        s -= prev[s]
    bays.sort(reverse=True)
    residual = max(0.0, (Lc - s_star) / 100)
    return bays, residual, infill, why


# ---------------------------------------------------------------------------------------------
# Transverse configuration search
# ---------------------------------------------------------------------------------------------
def line_extension(area: Area, inner: bool) -> float:
    """Standard extension above the top deck of a line: 1.0 m for guardrail lines (outer line, or all lines
    when protection is all_sides), 0.5 m for inner lines (one node above the deck ledger)."""
    if not inner or area.protection == "all_sides" or area.area_type == "tower":
        return 1.0
    return 0.5


class _Ctx:
    def __init__(self, area: Area, cat: Catalogue, hull: Hull, n: int):
        self.area, self.cat, self.hull, self.n = area, cat, hull, n
        self.lh = cat.lift_height_m
        self.zk = [area.z_base + self.lh * k for k in range(0, n + 1)]
        self.gmin = area.gap_min_m
        self.target = area.clearance_target_m
        self.gmax = area.max_gap_m if area.max_gap_m is not None else float(cat.rule("max_gap_without_bracket_m"))
        self.brackets = cat.brackets()
        # envelopes: an inner line used up to lift k stands to z_k + ext (0.5 m above the deck node,
        # 1.0 m if it carries guardrails); it must clear the hull over [z_base, z_k + ext]
        self.ext_inner = line_extension(area, inner=True)
        self.env_top = [-math.inf] + [hull.envelope(area.z_base, self.zk[k] + self.ext_inner) for k in range(1, n + 1)]
        self.env_edge = [-math.inf] + [hull.envelope(self.zk[k] - 0.5, self.zk[k]) for k in range(1, n + 1)]
        self.hy = [math.nan] + [hull.hull_y(self.zk[k]) for k in range(1, n + 1)]
        self.decked = [True] + [area.working_levels is None or k in area.working_levels for k in range(1, n + 1)]


def _eval(ctx: _Ctx, y0: float, widths: list[float], n_bays: int):
    n = ctx.n
    R = [0.0]
    for w in widths:
        R.append(R[-1] + w)
    line_y = [y0 - r for r in R]
    tops = []
    for j, y in enumerate(line_y):
        T = 0
        for k in range(1, n + 1):
            if ctx.env_top[k] + ctx.gmin <= y + EPS:
                T = k
            else:
                break
        if j <= 1 and T < n:
            return None                       # base platform must be clear at full height
        if j >= 2 and T == 0:
            return None                       # redundant inner line
        tops.append(T)
    lifts: list[LiftPlan] = []
    infill_lifts = 0
    dev = 0.0
    n_br = 0
    for k in range(1, n + 1):
        present = [j for j, T in enumerate(tops) if T >= k]
        jin = max(present)
        y_in = line_y[jin]
        hy = ctx.hy[k]
        lp = LiftPlan(k=k, z_deck=round(ctx.zk[k], 4), lines_present=present, inner_line=jin,
                      decked=ctx.decked[k], edge_y=round(y_in, 4))
        if math.isnan(hy):
            lp.status, lp.reason = "open", "no hull at deck level (above sheer / outside section) — inner side guarded"
            lifts.append(lp)
            continue
        lp.hull_y = round(hy, 4)
        opts = []
        for b in [None] + ctx.brackets:
            bl = 0.0 if b is None else b.length_m
            edge = y_in - bl
            if b is not None and ctx.env_edge[k] + ctx.gmin > edge + EPS:
                continue                       # bracket would clash with hull below deck
            g = edge - hy
            if g < ctx.gmin - EPS:
                continue
            opts.append((g, b, edge))
        feas = [o for o in opts if o[0] <= ctx.gmax + EPS]
        if feas:
            g, b, edge = min(feas, key=lambda o: (abs(o[0] - ctx.target), 0 if o[1] is None else o[1].length_m))
            lp.gap_m, lp.edge_y = round(g, 4), round(edge, 4)
            if b is not None:
                lp.bracket_m, lp.bracket_code, lp.status = b.length_m, b.code, "bracket"
                lp.reason = f"bracket {b.length_m:.2f} m brings gap to {g:.3f} m"
                n_br += 1
            else:
                lp.reason = f"gap {g:.3f} m within [{ctx.gmin:.2f}, {ctx.gmax:.2f}] m"
            dev += abs(g - ctx.target)
        else:
            # best achievable = smallest gap still clash-free
            g, b, edge = min(opts, key=lambda o: o[0])
            lp.gap_m, lp.edge_y = round(g, 4), round(edge, 4)
            if b is not None:
                lp.bracket_m, lp.bracket_code = b.length_m, b.code
                n_br += 1
            lp.status = "infill"
            lp.infill_width_m = round(g - ctx.target, 4)
            sizes = ", ".join(f"{x.length_m:.2f}" for x in ctx.brackets) or "none"
            lp.reason = (f"gap {g:.3f} m > max {ctx.gmax:.2f} m; no width/bracket combination fits "
                         f"(brackets {sizes} m) -> transverse infill {g - ctx.target:.3f} m")
            infill_lifts += 1
        lifts.append(lp)
    material = sum(2 * T + 1 for T in tops) * (n_bays + 1) + 3 * n_br * (n_bays + 1) + 4 * sum(widths) * n * n_bays
    cost = 1000.0 * infill_lifts * max(1, n_bays) + 10.0 * dev + 0.05 * material
    return cost, line_y, tops, lifts, {"infill_lifts": infill_lifts, "gap_deviation_m": round(dev, 4),
                                       "material_proxy": round(material, 2), "brackets_lifts": n_br,
                                       "cost": round(cost, 4)}


def _scores(ctx: _Ctx, y0s: np.ndarray, widths: list[float], n_bays: int) -> np.ndarray:
    """Vectorised objective over many outer-line positions (same rules as _eval). inf = infeasible."""
    n = ctx.n
    R = np.concatenate([[0.0], np.cumsum(widths)])
    env = np.array(ctx.env_top[1:])                          # non-decreasing in k
    C = len(y0s)
    T = np.zeros((len(R), C), dtype=int)
    for j, r in enumerate(R):
        T[j] = np.searchsorted(env + ctx.gmin, y0s - r + EPS, side="right")
    ok = (T[0] >= n) & (T[1] >= n)
    if len(R) > 2:
        ok &= (T[2:] >= 1).all(axis=0)
    infill = np.zeros(C)
    dev = np.zeros(C)
    n_br = np.zeros(C)
    br = [0.0] + [b.length_m for b in ctx.brackets]
    for k in range(1, n + 1):
        hy = ctx.hy[k]
        if math.isnan(hy):
            continue
        jin = (T >= k).sum(axis=0) - 1                        # lines are contiguous from the outer line
        y_in = y0s - R[np.clip(jin, 0, len(R) - 1)]
        best = np.full(C, np.inf)
        best_b = np.zeros(C)
        ming = np.full(C, np.inf)                              # smallest clash-free gap (used when infilling)
        ming_b = np.zeros(C)
        for bl in br:
            edge = y_in - bl
            g = edge - hy
            valid = g >= ctx.gmin - EPS
            if bl > 0:
                valid &= ctx.env_edge[k] + ctx.gmin <= edge + EPS
            feas = valid & (g <= ctx.gmax + EPS)
            d = np.where(feas, np.abs(g - ctx.target), np.inf)
            better = d < best - 1e-12
            best = np.where(better, d, best)
            best_b = np.where(better, bl, best_b)
            gm = np.where(valid, g, np.inf)
            bm = gm < ming - 1e-12
            ming = np.where(bm, gm, ming)
            ming_b = np.where(bm, bl, ming_b)
        miss = ~np.isfinite(best)
        infill += miss
        dev += np.where(miss, 0.0, best)
        n_br += np.where(miss, ming_b > 0, best_b > 0)
    material = (2 * T + 1).sum(axis=0) * (n_bays + 1) + 3 * n_br * (n_bays + 1) + 4 * sum(widths) * n * n_bays
    cost = 1000.0 * infill * max(1, n_bays) + 10.0 * dev + 0.05 * material
    return np.where(ok, cost, np.inf)


def _transverse(ctx: _Ctx, n_bays: int):
    """Exact search over the outer-line position y0 for every width configuration.

    Every lift's outcome is piecewise constant in y0; it can only change where (a) a gap hits gap_min or
    max_gap for some line/bracket, (b) a stepped line's top lift changes (hull clash), or (c) a bracket
    starts/stops clashing. All those breakpoints, the target-gap points and the midpoints between
    consecutive breakpoints are evaluated, so the minimum number of infills is found exactly.
    """
    cat, area = ctx.cat, ctx.area
    widths = sorted(cat.bay_widths_m)
    base_opts = [w for w in widths if w >= area.min_platform_width_m - EPS] or [max(widths)]
    best = None
    evaluated = 0
    finite_k = [k for k in range(1, ctx.n + 1) if not math.isnan(ctx.hy[k])]
    brs = [0.0] + [b.length_m for b in ctx.brackets]
    for w1 in base_opts:
        for r in range(0, max(0, area.max_extra_rows) + 1):
            for extra in itertools.product(widths, repeat=r):
                ws = [w1, *extra]
                R = np.concatenate([[0.0], np.cumsum(ws)])
                y0_min = ctx.env_top[ctx.n] + ctx.gmin + w1
                pts = [y0_min]
                for rj in R:
                    for k in range(1, ctx.n + 1):
                        pts.append(ctx.env_top[k] + ctx.gmin + rj)                 # (b) line top changes
                        if k in finite_k:
                            for b in brs:
                                for g in (ctx.gmin, ctx.target, ctx.gmax):
                                    pts.append(ctx.hy[k] + g + b + rj)          # (a) gap window
                                if b > 0:
                                    pts.append(ctx.env_edge[k] + ctx.gmin + b + rj)  # (c) bracket clash
                bp = np.unique(np.round(np.array(pts), 6))
                bp = bp[bp >= y0_min - EPS]
                if len(bp) == 0:
                    continue
                mids = (bp[:-1] + bp[1:]) / 2
                cands = np.unique(np.concatenate([bp, mids, bp + 2e-4, bp - 2e-4]))
                cands = cands[cands >= y0_min - EPS]
                sc = _scores(ctx, cands, ws, n_bays)
                evaluated += len(cands)
                i = int(np.argmin(sc))
                if not np.isfinite(sc[i]):
                    continue
                res = _eval(ctx, float(cands[i]), ws, n_bays)
                if res is None:
                    continue
                key = (round(res[0], 6), len(ws), round(float(cands[i]), 4))
                if best is None or key < best[0]:
                    best = (key, float(cands[i]), ws, res)
    return best, evaluated


# ---------------------------------------------------------------------------------------------
def generate_layout(area: Area, cat: Catalogue, section: Section | None, common: dict | None = None) -> Layout:
    hull = Hull(section, area.obstructions, avoid_obstructions=(area.obstruction_mode == "avoid"))
    n = area.lifts(cat.lift_height_m)
    tower = area.area_type == "tower" or section is None or hull.empty
    expl: list[str] = []
    viol: list[Violation] = []

    # ---- longitudinal
    if area.tower_bays:
        tgt = area.tower_bay_target_m or 2.5
        L1 = min(cat.bay_lengths_m, key=lambda x: (abs(x - tgt), -x))
        bays = [L1] * area.tower_bays
        run_target = sum(bays)
        residual, linf = 0.0, False
        expl.append(f"Fixed tower: {area.tower_bays} bays x {L1:.2f} m (catalogue length nearest to {tgt:.2f} m)")
    else:
        run_target = area.run_length()
        bays, residual, linf, why = fill_run(run_target, cat.bay_lengths_m, area.run_start == "bounded",
                                             area.run_end == "bounded", area.run_tolerance_m, area.max_overhang_m)
        expl.append("Run: " + why)
    if not bays:
        viol.append(Violation(rule="run_fill", severity="error",
                              message=f"Run {run_target:.2f} m shorter than the smallest bay; whole run is infill"))
    n_bays = len(bays)

    # ---- transverse
    if tower:
        wt = area.tower_width_target_m or area.min_platform_width_m
        if area.tower_width_target_m:
            w1 = min(cat.bay_widths_m, key=lambda x: (abs(x - wt), -x))
        else:
            w1 = min([w for w in cat.bay_widths_m if w >= wt - EPS] or [max(cat.bay_widths_m)])
        widths, line_y, tops = [w1], [w1, 0.0], [n, n]
        lifts = [LiftPlan(k=k, z_deck=round(area.z_base + cat.lift_height_m * k, 4), lines_present=[0, 1],
                          inner_line=1, decked=(area.working_levels is None or k in area.working_levels),
                          status="open", reason="free tower — no hull reference")
                 for k in range(1, n + 1)]
        obj, evaluated = {"infill_lifts": 0}, 1
        expl.append(f"Tower width {w1:.2f} m (nearest catalogue width to {wt:.2f} m)")
    else:
        ctx = _Ctx(area, cat, hull, n)
        best, evaluated = _transverse(ctx, n_bays)
        if best is None:
            raise ValueError(f"{cat.system_id}: no feasible transverse configuration (hull clash at every position)")
        _, y0, widths, (cost, line_y, tops, lifts, obj) = best
        expl.append(f"Transverse: outer line at y={y0:.3f} m, widths {', '.join(f'{w:.2f}' for w in widths)} m "
                    f"(searched {evaluated} positions/configurations; max gap {ctx.gmax:.2f} m, target "
                    f"{ctx.target:.2f} m, min {ctx.gmin:.2f} m)")
        if len(widths) > 1:
            expl.append("Stepped inner lines: " + "; ".join(
                f"line {j} up to lift {tops[j]}" for j in range(2, len(widths) + 1)))

    lay = Layout(system_id=cat.system_id, mode="tower" if tower else "section", bays=bays,
                 run_target_m=round(run_target, 4), run_covered_m=round(sum(bays), 4),
                 run_residual_m=round(residual, 4), run_start=area.run_start, run_end=area.run_end,
                 longitudinal_infill=linf, widths=widths, line_y=[round(y, 4) for y in line_y],
                 line_top_lift=tops, n_lifts=n, z_base=area.z_base, lifts=lifts, objective=obj,
                 search={"evaluated": evaluated}, explanation=expl, violations=viol)
    _add_infills(lay, cat, area, common)
    return lay


def _add_infills(lay: Layout, cat: Catalogue, area: Area, common: dict | None = None):
    from ..catalogue import load_common
    common = common or load_common()
    li, ti = common["longitudinal_infill"], common["transverse_infill"]
    for lp in lay.lifts:
        if lay.longitudinal_infill:
            tubes = len(lp.lines_present) + li["tubes_extra_over_lines"]
            lay.infills.append(Infill(kind="longitudinal", lift=lp.k, size_m=lay.run_residual_m, units=1, tubes=tubes,
                                      tube_length_m=round(lay.run_residual_m + li["overlap_m"], 3),
                                      couplers=tubes * li["couplers_per_tube"],
                                      reason=f"run residual {lay.run_residual_m:.2f} m > tolerance {area.run_tolerance_m:.2f} m at bounded end"))
        if lp.status == "infill" and lay.n_bays:
            units = lay.n_bays
            tubes = ti["tubes_per_bay"] * units
            lay.infills.append(Infill(kind="transverse", lift=lp.k, size_m=lp.infill_width_m or 0.0, units=units,
                                      tubes=tubes, tube_length_m=round((lp.infill_width_m or 0) + ti["overlap_m"], 3),
                                      couplers=tubes * ti["couplers_per_tube"], reason=lp.reason))
