"""Hull queries on a 2D section (Y-Z) plus obstructions.

hull_y(z): outermost half-breadth of the shell at height z (NaN if no shell at that height).
envelope(z0, z1): max outboard extent of hull (and, in avoid mode, obstructions) over a band.
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Polygon, box

from ..models import Obstruction, Section


class Hull:
    def __init__(self, section: Section | None, obstructions: list[Obstruction] | None = None,
                 avoid_obstructions: bool = True):
        self.section = section
        pts = np.array(section.points, dtype=float) if section else np.zeros((0, 2))
        self.pts = pts
        self.obstructions = obstructions or []
        self.obs_polys = [Polygon(o.points) for o in self.obstructions]
        self.avoid = avoid_obstructions
        self.zmin = float(pts[:, 1].min()) if len(pts) else math.nan
        self.zmax = float(pts[:, 1].max()) if len(pts) else math.nan

    @property
    def empty(self) -> bool:
        return len(self.pts) < 2

    def hull_y(self, z: float) -> float:
        """Outermost y of the shell polyline at height z (linear interpolation on each segment)."""
        if self.empty:
            return math.nan
        p0, p1 = self.pts[:-1], self.pts[1:]
        z0, z1 = p0[:, 1], p1[:, 1]
        lo, hi = np.minimum(z0, z1), np.maximum(z0, z1)
        m = (z >= lo - 1e-9) & (z <= hi + 1e-9)
        if not m.any():
            return math.nan
        a, b = p0[m], p1[m]
        dz = b[:, 1] - a[:, 1]
        t = np.where(np.abs(dz) < 1e-12, 0.0, (z - a[:, 1]) / np.where(np.abs(dz) < 1e-12, 1, dz))
        y = a[:, 0] + t * (b[:, 0] - a[:, 0])
        # horizontal segments: take the outer end
        y = np.where(np.abs(dz) < 1e-12, np.maximum(a[:, 0], b[:, 0]), y)
        return float(y.max())

    def _obs_max_y(self, z0: float, z1: float) -> float:
        best = -math.inf
        for poly in self.obs_polys:
            inter = poly.intersection(box(-1e4, z0, 1e4, z1))
            if not inter.is_empty:
                best = max(best, inter.bounds[2])
        return best

    def envelope(self, z0: float, z1: float, step: float = 0.05, include_obstructions: bool | None = None) -> float:
        """Max outboard extent over [z0, z1]. -inf if nothing there."""
        if z1 < z0:
            z0, z1 = z1, z0
        zs = np.arange(z0, z1 + 1e-9, step)
        if len(zs) == 0 or zs[-1] < z1 - 1e-9:
            zs = np.append(zs, z1)
        best = -math.inf
        if not self.empty:
            # include polyline vertices inside the band (exact extremes)
            vs = self.pts[(self.pts[:, 1] >= z0) & (self.pts[:, 1] <= z1)]
            if len(vs):
                best = float(vs[:, 0].max())
            for z in zs:
                y = self.hull_y(float(z))
                if not math.isnan(y):
                    best = max(best, y)
        inc = self.avoid if include_obstructions is None else include_obstructions
        if inc and self.obs_polys:
            best = max(best, self._obs_max_y(z0, z1))
        return best

    def clashes(self, geom) -> list[str]:
        """Names of obstructions intersecting a shapely geometry (component envelope)."""
        out = []
        for o, poly in zip(self.obstructions, self.obs_polys):
            if poly.intersects(geom) and poly.intersection(geom).area > 1e-6 or (
                    isinstance(geom, LineString) and poly.intersects(geom)):
                out.append(o.name)
        return out
