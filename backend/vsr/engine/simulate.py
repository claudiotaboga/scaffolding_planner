"""Erection simulation: sequence lift by lift, man-time from the time standard, elapsed for a crew.

Order inside a lift (from the item phases): standards -> ledgers -> transoms -> diagonals ->
brackets -> advance guardrail -> decks -> guardrails -> toe boards -> ties -> wedge securing ->
infills. The advance-guardrail step is placed before the decks of the lift, so fitters stepping
onto a new level are always protected when it is enabled.
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from ..catalogue import TimeStandard
from .bom import PHASES, Item


class Step(BaseModel):
    seq: int
    lift: int
    phase: str
    action: str
    code: str
    qty: int
    man_s_each: float
    man_s: float
    cum_crew_h: float
    cum_elapsed_min: float
    note: str = ""


class SimResult(BaseModel):
    steps: list[Step]
    crew: int
    crew_efficiency: float
    man_s_total: float
    crew_hours: float
    elapsed_min: float
    by_action_man_s: dict[str, float]
    by_lift_man_s: dict[int, float]
    wedges: int
    unprotected_exposure_if_no_agr_h: float
    time_standard: dict


def simulate(items: list[Item], ts: TimeStandard, crew: int) -> SimResult:
    eff = ts.efficiency(crew)
    rate = crew * eff
    order = {p: i for i, p in enumerate(PHASES)}
    lifts = sorted({it.lift for it in items})
    seq_items: list[Item] = []
    wedges_total = 0
    for k in lifts:
        lift_items = sorted([it for it in items if it.lift == k], key=lambda it: order.get(it.phase, 99))
        w = sum(it.wedges for it in lift_items)
        wedges_total += w
        # wedge securing goes after placement, before infills
        pre = [it for it in lift_items if order.get(it.phase, 99) < order["wedge"]]
        post = [it for it in lift_items if order.get(it.phase, 99) > order["wedge"]]
        seq_items += pre
        if w:
            seq_items.append(Item(lift=k, phase="wedge", action="secure_wedge", code="WEDGE", qty=w,
                                  note="secure all wedges of this lift"))
        seq_items += post

    steps: list[Step] = []
    cum = 0.0
    by_action: dict[str, float] = defaultdict(float)
    by_lift: dict[int, float] = defaultdict(float)
    unprot = 0.0
    seq_items = [it for it in seq_items if it.action not in ("infill", "infill_coupler")]  # timed in add_infill_time
    for i, it in enumerate(seq_items):
        each = ts.actions[it.action]
        man = each * it.qty
        cum += man
        by_action[it.action] += man
        by_lift[it.lift] += man
        if it.lift >= 1 and it.action in ("place_deck", "place_hatch", "place_guardrail"):
            unprot += man
        steps.append(Step(seq=i + 1, lift=it.lift, phase=it.phase, action=it.action, code=it.code, qty=it.qty,
                          man_s_each=each, man_s=man, cum_crew_h=round(cum / 3600, 4),
                          cum_elapsed_min=round(cum / rate / 60, 3), note=it.note))
    return SimResult(steps=steps, crew=crew, crew_efficiency=eff, man_s_total=cum, crew_hours=cum / 3600,
                     elapsed_min=cum / rate / 60, by_action_man_s=dict(by_action), by_lift_man_s=dict(by_lift),
                     wedges=wedges_total, unprotected_exposure_if_no_agr_h=unprot / 3600,
                     time_standard=ts.version_stamp())


def add_infill_time(sim: SimResult, infill_units_by_lift: dict[int, int], ts: TimeStandard) -> SimResult:
    """Infill time = units x crew-hours per unit (time standard). Inserted at the end of each lift."""
    if not infill_units_by_lift:
        return sim
    rate = sim.crew * sim.crew_efficiency
    new_steps: list[Step] = []
    cum = 0.0
    by_action = dict(sim.by_action_man_s)
    by_lift = dict(sim.by_lift_man_s)
    lifts_done = set()
    steps = sim.steps

    def flush(k):
        nonlocal cum
        u = infill_units_by_lift.get(k, 0)
        if u and k not in lifts_done:
            man = u * ts.infill_crew_hours_per_unit * 3600
            cum += man
            by_action["infill"] = by_action.get("infill", 0) + man
            by_lift[k] = by_lift.get(k, 0) + man
            new_steps.append(Step(seq=0, lift=k, phase="infill", action="infill", code="TC-INFILL", qty=u,
                                  man_s_each=ts.infill_crew_hours_per_unit * 3600, man_s=man,
                                  cum_crew_h=round(cum / 3600, 4), cum_elapsed_min=round(cum / rate / 60, 3),
                                  note=f"{u} infill unit(s) x {ts.infill_crew_hours_per_unit} crew-h"))
        lifts_done.add(k)

    for idx, s in enumerate(steps):
        if s.action in ("infill", "infill_coupler"):
            continue
        cum += s.man_s
        new_steps.append(s.model_copy(update={"cum_crew_h": round(cum / 3600, 4),
                                              "cum_elapsed_min": round(cum / rate / 60, 3)}))
        nxt = next((t for t in steps[idx + 1:] if t.action not in ("infill", "infill_coupler")), None)
        if nxt is None or nxt.lift != s.lift:
            flush(s.lift)
    for k in sorted(infill_units_by_lift):
        flush(k)
    for i, s in enumerate(new_steps):
        s.seq = i + 1
    return sim.model_copy(update={"steps": new_steps, "man_s_total": cum, "crew_hours": cum / 3600,
                                  "elapsed_min": cum / rate / 60, "by_action_man_s": by_action,
                                  "by_lift_man_s": by_lift})
