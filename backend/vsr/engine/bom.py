"""Component generation from a layout -> itemised list (per lift, per action) and aggregated BoM.

Rules are deterministic and documented in docs/TECHNICAL_NOTE.md so a hand count can reproduce them.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel

from ..catalogue import Catalogue
from ..models import Area
from .layout import Layout, Violation

WEDGES = {"place_ledger": 2, "place_transom": 2, "place_guardrail": 2, "place_diagonal": 2, "place_bracket": 1}


class Item(BaseModel):
    lift: int                 # 0 = base
    phase: str                # ordering key inside a lift
    action: str               # time-standard action
    code: str
    qty: int
    wedges: int = 0
    note: str = ""


class BomLine(BaseModel):
    code: str
    name: str
    role: str
    qty: int
    unit_weight_kg: float
    total_weight_kg: float
    status: str
    source: str
    catalogue: str
    catalogue_version: str


PHASES = ["base_jack", "standard", "ledger", "transom", "diagonal", "bracket", "advance_guardrail", "deck",
          "guardrail", "toe_board", "tie", "wedge", "infill"]


def compose_standard(h: float, lengths: list[float]) -> list[float]:
    """Greedy: longest piece that fits, repeat. Lengths are multiples of the 0.5 m node pitch."""
    out, rem = [], round(h, 3)
    for L in sorted(lengths, reverse=True):
        while rem >= L - 1e-6:
            out.append(L)
            rem = round(rem - L, 3)
    if rem > 1e-6:
        out.append(min(lengths))
    return out


def generate_items(lay: Layout, cat: Catalogue, area: Area, common: dict) -> tuple[list[Item], list[Violation], dict]:
    items: list[Item] = []
    viol: list[Violation] = []
    nb = lay.n_bays
    P = nb + 1 if nb else 0
    lines = len(lay.line_y)
    W = lay.widths
    lh = cat.lift_height_m
    every = int(cat.rule("diagonal_every_n_bays"))
    nodes: set = set()

    def add(lift, phase, action, code, qty, note=""):
        if qty <= 0:
            return
        items.append(Item(lift=lift, phase=phase, action=action, code=code, qty=qty,
                          wedges=WEDGES.get(action, 0) * qty, note=note))

    if not nb:
        viol.append(Violation(rule="empty_layout", severity="error", message="No modular bays placed"))
        return items, viol, {"nodes": 0}

    # ---- base
    jack = cat.part("base_jack")
    add(0, "base_jack", "place_base_jack", jack.code, P * lines, "one per standard column")
    std_lengths = cat.standard_lengths()
    from .layout import line_extension
    for j in range(lines):
        H = lh * lay.line_top_lift[j] + line_extension(area, inner=(j > 0))
        z = 0.0
        for piece in compose_standard(H, std_lengths):
            lift = int(math.floor(z / lh + 1e-9))
            add(lift, "standard", "place_standard", cat.part("standard", piece).code, P,
                f"line {j}, column {H:.1f} m")
            z += piece
    for j in range(lines):
        for i, L in enumerate(lay.bays):
            add(0, "ledger", "place_ledger", cat.part("ledger", L).code, 1, f"base ledger line {j}")
        for p in range(P):
            nodes.add((j, p, 0, 0.0))
    for jj in range(1, lines):
        add(0, "transom", "place_transom", cat.part("ledger", W[jj - 1]).code, P, f"base transom bay-across {jj}")

    # ---- ties
    n_ties = 0
    if area.anchorage == "tied":
        face = lay.run_covered_m * lh * lay.n_lifts
        n_ties = math.ceil(face / float(cat.rule("tie_area_m2")) - 1e-9)
    tie_per_lift = [0] * (lay.n_lifts + 1)
    for t in range(n_ties):
        tie_per_lift[1 + (t % lay.n_lifts)] += 1

    hatch_missing = False
    free_start = area.run_start == "free" or lay.mode == "tower"
    free_end = area.run_end == "free" or lay.mode == "tower"
    if lay.longitudinal_infill:
        free_start = free_start and area.run_start == "free"
        free_end = free_end and area.run_end == "free"
    inner_diag = area.anchorage == "free_standing" or lay.mode == "tower"

    for lp in lay.lifts:
        k = lp.k
        present = lp.lines_present
        jin = lp.inner_line
        across = [W[j - 1] for j in present if j >= 1]           # width of bay between line j-1 and j
        for j in present:
            for i, L in enumerate(lay.bays):
                add(k, "ledger", "place_ledger", cat.part("ledger", L).code, 1, f"deck ledger line {j}")
            for p in range(P):
                nodes.add((j, p, k, 0.0))
        for w in across:
            add(k, "transom", "place_transom", cat.part("ledger", w).code, P, "transom")
        diag_bays = [i for i in range(nb) if i % every == 0]
        faces = [0] + ([jin] if inner_diag and jin != 0 else [])
        for f in faces:
            for i in diag_bays:
                add(k, "diagonal", "place_diagonal", cat.part("diagonal", lay.bays[i]).code, 1, f"face line {f}")
                nodes.add((f, i, k - 1, 0.0))
                nodes.add((f, i + 1, k, 0.0))
        if lp.bracket_m:
            add(k, "bracket", "place_bracket", lp.bracket_code, P, f"inner brackets {lp.bracket_m:.2f} m")
            for p in range(P):
                nodes.add((jin, p, k, 0.0))
        if lp.decked:
            if area.advance_guardrail:
                add(k, "advance_guardrail", "advance_guardrail", "AGR", nb, "advance guardrail per bay (temporary)")
            hatch_done = False
            for i, L in enumerate(lay.bays):
                for w in across:
                    nd = int(cat.map_rule("decks_per_width", w))
                    if (not hatch_done and cat.hatch and abs(cat.hatch.bay_length_m - L) < 0.006
                            and nd >= cat.hatch.replaces_decks):
                        add(k, "deck", "place_hatch", cat.hatch.code, 1, "access hatch")
                        nd -= cat.hatch.replaces_decks
                        hatch_done = True
                    add(k, "deck", "place_deck", cat.part("deck", L).code, nd)
                if lp.bracket_m:
                    nd = int(cat.map_rule("bracket_decks", lp.bracket_m))
                    add(k, "deck", "place_deck", cat.part("deck", L).code, nd, "decks on brackets")
            if not hatch_done:
                hatch_missing = True
            guard_lines = [0]
            if area.protection == "all_sides" or lp.status == "open":
                guard_lines.append(jin)
            for g in guard_lines:
                for L in lay.bays:
                    add(k, "guardrail", "place_guardrail", cat.part("ledger", L).code, 2, f"guardrail line {g}")
                    add(k, "toe_board", "place_toe_board", cat.part("toe_board", L).code, 1, f"toe board line {g}")
                for p in range(P):
                    nodes.add((g, p, k, 0.5))
                    nodes.add((g, p, k, 1.0))
            ends = ([0] if free_start else []) + ([P - 1] if free_end else [])
            for e in ends:
                for w in across:
                    add(k, "guardrail", "place_guardrail", cat.part("ledger", w).code, 2, "end guardrail")
                    add(k, "toe_board", "place_toe_board", cat.part("toe_board", w).code, 1, "end toe board")
                for j in present:
                    nodes.add((j, e, k, 0.5))
                    nodes.add((j, e, k, 1.0))
        if tie_per_lift[k]:
            add(k, "tie", "place_tie", cat.part("tie").code, tie_per_lift[k], "wall tie")
    for inf in lay.infills:
        add(inf.lift, "infill", "infill", common["tube"]["code"], inf.tubes,
            f"{inf.kind} infill tube {inf.tube_length_m:.2f} m")
        add(inf.lift, "infill", "infill_coupler", common["coupler"]["code"], inf.couplers, f"{inf.kind} infill couplers")

    if hatch_missing:
        viol.append(Violation(rule="access", severity="warning",
                              message="No bay matches the hatch-deck length on at least one lift: plan stair tower / "
                                      "ladder access separately (not in BoM)"))
    return items, viol, {"nodes": len(nodes), "ties": n_ties}


def aggregate_bom(items: list[Item], lay: Layout, cat: Catalogue, common: dict) -> list[BomLine]:
    qty: dict[str, int] = defaultdict(int)
    tube_len = 0.0
    for it in items:
        if it.code == "AGR":
            continue                      # temporary advance guardrail: not part of the standing scaffold
        if it.action == "infill":
            continue
        qty[it.code] += it.qty
    for inf in lay.infills:
        tube_len += inf.tubes * inf.tube_length_m
        qty[common["coupler"]["code"]] += inf.couplers
    out: list[BomLine] = []
    for code, q in qty.items():
        if code == common["coupler"]["code"]:
            c = common["coupler"]
            out.append(BomLine(code=code, name=c["name"], role="infill_coupler", qty=q,
                               unit_weight_kg=c["weight_kg"]["value"], total_weight_kg=round(q * c["weight_kg"]["value"], 3),
                               status=c["weight_kg"]["status"], source=c["weight_kg"]["source"],
                               catalogue="tube_and_coupler", catalogue_version=common["version"]))
            continue
        comp = next(c for c in cat.components if c.code == code)
        out.append(BomLine(code=code, name=comp.name, role=comp.role, qty=q, unit_weight_kg=comp.weight_kg,
                           total_weight_kg=round(q * comp.weight_kg, 3), status=comp.status, source=comp.source or "",
                           catalogue=cat.system_id, catalogue_version=cat.catalogue_version))
    if tube_len > 0:
        t = common["tube"]
        out.append(BomLine(code=t["code"], name=t["name"] + " (metres)", role="infill_tube", qty=int(math.ceil(tube_len)),
                           unit_weight_kg=t["weight_kg_per_m"]["value"],
                           total_weight_kg=round(math.ceil(tube_len) * t["weight_kg_per_m"]["value"], 3),
                           status=t["weight_kg_per_m"]["status"], source=t["weight_kg_per_m"]["source"],
                           catalogue="tube_and_coupler", catalogue_version=common["version"]))
    order = {r: i for i, r in enumerate(["base_jack", "standard", "ledger", "diagonal", "deck", "hatch", "toe_board",
                                         "bracket", "tie", "infill_tube", "infill_coupler"])}
    out.sort(key=lambda b: (order.get(b.role, 99), b.code))
    return out
