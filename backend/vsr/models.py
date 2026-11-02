"""Domain models. Units: metres. Ship coordinates: X aft->fore (frame), Y port->starboard
(for a side we use |Y| = half-breadth, outboard positive), Z baseline up."""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
AreaType = Literal["flat_shell", "curved_shell", "bow_flare", "stern_bilge_turn", "internal_compartment",
                   "deck_edge", "superstructure", "tower"]


class Section(BaseModel):
    """A transverse frame section: hull shell polyline in the (Y, Z) plane for one side."""
    id: str
    frame: float
    x: float = 0.0                       # ship X of the frame (m)
    points: list[tuple[float, float]]    # (y, z) half-breadth, height above BL
    source: str = "manual"               # dxf | dwg | pdf_vector | pdf_scan | navisworks | manual
    source_file: Optional[str] = None
    confidence: Confidence = "low"
    notes: list[str] = []

    def mirrored(self) -> "Section":
        """Section with y -> -y (scaffold on the inboard side of the shell)."""
        return self.model_copy(update={"points": [(-y, z) for y, z in self.points]})

    def geometry_hash(self) -> str:
        return hashlib.sha256(json.dumps([round(v, 4) for p in self.points for v in p]).encode()).hexdigest()[:16]


class Obstruction(BaseModel):
    name: str
    points: list[tuple[float, float]]    # polygon (y, z)
    kind: str = "outfitting"


class Area(BaseModel):
    id: str
    name: str
    area_type: AreaType = "flat_shell"
    section_id: Optional[str] = None
    side: Literal["SB", "PS"] = "SB"
    face: Literal["outboard", "inboard"] = "outboard"   # scaffold outside the shell, or inside (tanks, ER)
    frame_from: Optional[float] = None
    frame_to: Optional[float] = None
    frame_spacing_m: float = 0.70
    run_length_m: Optional[float] = None           # overrides frame range if set
    run_start: Literal["free", "bounded"] = "free"
    run_end: Literal["free", "bounded"] = "free"
    run_tolerance_m: float = 0.20
    max_overhang_m: float = 1.00
    z_base: float = 0.0                            # standing level (dock floor / tank top / deck)
    z_top: float = 8.0                             # top of the surface to be reached
    n_lifts: Optional[int] = None                  # default: decks every 2 m until top deck >= z_top - 2.0
    working_levels: Optional[list[int]] = None     # lifts that get decks/guardrails; None = all
    clearance_target_m: float = 0.20
    gap_min_m: float = 0.05
    max_gap_m: Optional[float] = None              # None -> catalogue max_gap_without_bracket_m
    load_class: int = 4
    anchorage: Literal["tied", "free_standing", "suspended"] = "tied"
    protection: Literal["outer", "all_sides"] = "outer"
    advance_guardrail: bool = True
    min_platform_width_m: float = 0.90
    max_extra_rows: int = 3
    obstructions: list[Obstruction] = []
    obstruction_mode: Literal["avoid", "flag_only"] = "avoid"
    use_drawing_obstructions: bool = False         # copy obstructions imported with the section
    rental_months: float = 1.0
    # fixed tower mode (no hull): reference tower, stair towers
    tower_bays: Optional[int] = None
    tower_bay_target_m: Optional[float] = None
    tower_width_target_m: Optional[float] = None
    access_points: list[str] = []
    notes: str = ""

    def run_length(self) -> float:
        if self.run_length_m is not None:
            return self.run_length_m
        if self.frame_from is not None and self.frame_to is not None:
            return abs(self.frame_to - self.frame_from) * self.frame_spacing_m
        raise ValueError(f"Area {self.id}: no run length (set run_length_m or frame range)")

    def lifts(self, lift_h: float = 2.0) -> int:
        if self.n_lifts:
            return self.n_lifts
        import math
        reach = 2.0
        return max(1, math.ceil((self.z_top - self.z_base - reach) / lift_h - 1e-9))


class AreaGeometry(BaseModel):
    """Geometry handed to the layout engine (source-independent)."""
    section: Optional[Section] = None
    confidence: Confidence = "low"
    source: str = "manual"


class Project(BaseModel):
    id: str
    name: str
    vessel: str = ""
    sections: list[Section] = []
    areas: list[Area] = []
    created: str = ""
    settings_overrides: dict = Field(default_factory=dict)
