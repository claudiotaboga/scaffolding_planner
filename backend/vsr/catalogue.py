"""Versioned, data-driven system catalogues, time standards and settings.

Adding a system = dropping a YAML file in data/catalogues (and optionally a time standard in
data/time_standards). No code changes. Every loaded document carries a sha256 so a run can
state exactly which data it used.
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

DATA_DIR = Path(os.environ.get("VSR_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

Status = Literal["verified", "estimate"]
ROLES = {"standard", "ledger", "diagonal", "deck", "hatch", "toe_board", "bracket", "base_jack", "tie"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _key(x: float) -> str:
    return f"{x:.2f}"


class Rule(BaseModel):
    value: Any
    status: Status
    source: str


class Component(BaseModel):
    code: str
    role: str
    name: str
    length_m: float
    width_m: Optional[float] = None
    weight_kg: float
    status: Status
    source: Optional[str] = None
    article_no: Optional[str] = None

    @model_validator(mode="after")
    def _role(self):
        if self.role not in ROLES:
            raise ValueError(f"{self.code}: unknown role {self.role!r}; allowed {sorted(ROLES)}")
        return self


class Hatch(BaseModel):
    code: str
    bay_length_m: float
    replaces_decks: int


class Catalogue(BaseModel):
    system_id: str
    name: str
    manufacturer: str
    catalogue_version: str
    default_source: str
    mixing_with_other_brands: bool = False
    node: dict
    lift_height_m: float = 2.0
    bay_lengths_m: list[float]
    bay_widths_m: list[float]
    rules: dict[str, Rule]
    hatch: Optional[Hatch] = None
    components: list[Component]
    # filled by loader
    file: str = ""
    sha256: str = ""

    REQUIRED_RULES: ClassVar[tuple] = ("max_gap_without_bracket_m", "tie_area_m2", "load_class_by_bay",
                                           "decks_per_width", "bracket_decks", "diagonal_every_n_bays",
                                           "free_standing_max_height_to_base")

    @model_validator(mode="after")
    def _check(self):
        missing = [r for r in self.REQUIRED_RULES if r not in self.rules]
        if missing:
            raise ValueError(f"{self.system_id}: missing rules {missing}")
        for c in self.components:
            if c.source is None:
                c.source = self.default_source
        # every bay length needs ledger, deck, toe board, diagonal; every width needs a ledger, toe board
        for L in self.bay_lengths_m:
            for role in ("ledger", "deck", "toe_board", "diagonal"):
                self.part(role, L)
        for W in self.bay_widths_m:
            for role in ("ledger", "toe_board"):
                self.part(role, W)
            if _key(W) not in self.rules["decks_per_width"].value:
                raise ValueError(f"{self.system_id}: decks_per_width missing width {W}")
        self.standard_lengths()
        self.part("base_jack")
        return self

    # --- lookups -------------------------------------------------------------------------
    def part(self, role: str, length: Optional[float] = None) -> Component:
        cands = [c for c in self.components if c.role == role and (length is None or abs(c.length_m - length) < 0.006)]
        if not cands:
            raise ValueError(f"{self.system_id}: no component role={role} length={length}")
        return cands[0]

    def has_part(self, role: str, length: Optional[float] = None) -> bool:
        try:
            self.part(role, length)
            return True
        except ValueError:
            return False

    def standard_lengths(self) -> list[float]:
        ls = sorted({c.length_m for c in self.components if c.role == "standard"}, reverse=True)
        if not ls:
            raise ValueError(f"{self.system_id}: no standards")
        return ls

    def brackets(self) -> list[Component]:
        return sorted([c for c in self.components if c.role == "bracket"], key=lambda c: c.length_m)

    def rule(self, name: str) -> Any:
        return self.rules[name].value

    def map_rule(self, name: str, x: float) -> Any:
        return self.rules[name].value[_key(x)]

    def ref(self, code: str) -> dict:
        c = next(c for c in self.components if c.code == code)
        return {"catalogue": self.system_id, "version": self.catalogue_version, "sha256": self.sha256,
                "code": c.code, "status": c.status, "source": c.source}

    def version_stamp(self) -> dict:
        n_est = sum(1 for c in self.components if c.status == "estimate")
        return {"system_id": self.system_id, "catalogue_version": self.catalogue_version, "file": self.file,
                "sha256": self.sha256, "components": len(self.components), "estimates": n_est}


class TimeStandard(BaseModel):
    standard_id: str
    system_id: str
    version: str
    status: str
    derivation: str
    crew_reference: int
    unit: str
    actions: dict[str, float]          # man-seconds per action
    infill_crew_hours_per_unit: float = 4.5
    dismantle_factor: float = 0.6
    crew_efficiency: dict[int, float] = {}
    base_weights: dict[str, float] = {}
    scale_factor: Optional[float] = None
    file: str = ""
    sha256: str = ""

    REQUIRED: ClassVar[tuple] = ("place_base_jack", "place_standard", "place_ledger", "place_transom",
                                     "place_guardrail", "place_diagonal", "place_deck", "place_hatch",
                                     "place_toe_board", "place_bracket", "place_tie", "secure_wedge",
                                     "advance_guardrail")

    @model_validator(mode="after")
    def _check(self):
        missing = [a for a in self.REQUIRED if a not in self.actions]
        if missing:
            raise ValueError(f"{self.standard_id}: missing actions {missing}")
        return self

    def efficiency(self, crew: int) -> float:
        if not self.crew_efficiency:
            return 1.0
        keys = sorted(self.crew_efficiency)
        k = max([k for k in keys if k <= crew], default=keys[0])
        return self.crew_efficiency[k]

    def version_stamp(self) -> dict:
        return {"standard_id": self.standard_id, "system_id": self.system_id, "version": self.version,
                "status": self.status, "file": self.file, "sha256": self.sha256}


# --- loading -------------------------------------------------------------------------------
def _load_yaml(p: Path) -> tuple[dict, str]:
    txt = p.read_text(encoding="utf-8")
    return yaml.safe_load(txt), _sha(txt)


def load_catalogues(data_dir: Path | None = None) -> dict[str, Catalogue]:
    d = Path(data_dir or DATA_DIR) / "catalogues"
    out: dict[str, Catalogue] = {}
    for p in sorted(d.glob("*.y*ml")):
        doc, sha = _load_yaml(p)
        cat = Catalogue(**doc, file=p.name, sha256=sha)
        if cat.system_id in out:
            raise ValueError(f"duplicate system_id {cat.system_id} in {p.name}")
        out[cat.system_id] = cat
    return out


def load_time_standards(data_dir: Path | None = None) -> dict[str, TimeStandard]:
    d = Path(data_dir or DATA_DIR) / "time_standards"
    out: dict[str, TimeStandard] = {}
    for p in sorted(d.glob("*.y*ml")):
        doc, sha = _load_yaml(p)
        ts = TimeStandard(**doc, file=p.name, sha256=sha)
        out[ts.system_id] = ts
    return out


def load_settings(data_dir: Path | None = None) -> dict:
    doc, sha = _load_yaml(Path(data_dir or DATA_DIR) / "settings.yaml")
    doc["sha256"] = sha
    return doc


def load_common(data_dir: Path | None = None) -> dict:
    doc, sha = _load_yaml(Path(data_dir or DATA_DIR) / "common" / "tube_and_coupler.yaml")
    doc["sha256"] = sha
    return doc


class DataBundle(BaseModel):
    """Everything a run depends on, loaded together so the run can stamp all versions."""
    catalogues: dict[str, Catalogue]
    time_standards: dict[str, TimeStandard]
    settings: dict
    common: dict
    data_dir: str

    def time_standard_for(self, system_id: str) -> TimeStandard:
        if system_id in self.time_standards:
            return self.time_standards[system_id]
        if "_GENERIC" in self.time_standards:
            return self.time_standards["_GENERIC"]
        raise ValueError(f"No time standard for {system_id} and no _GENERIC fallback")


def load_bundle(data_dir: Path | str | None = None) -> DataBundle:
    d = Path(data_dir or DATA_DIR)
    return DataBundle(catalogues=load_catalogues(d), time_standards=load_time_standards(d),
                      settings=load_settings(d), common=load_common(d), data_dir=str(d))
