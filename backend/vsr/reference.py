"""VSR reference tower (internal trial, Rev02 slide 7): 4 bays x 2.50 m (SM8) / 2.57 m (Layher),
width 1.14 / 1.09 m, 8 m high (4 lifts of 2 m), 5 fitters. SM8 76 min, Layher 52 min erection."""
from .models import Area

REFERENCE_TRIAL = {"crew": 5, "minutes": {"SM8": 76.0, "LAYHER_LW": 52.0},
                   "source": "VSR internal trial, Rev02 slide 7 (provisional)"}


def reference_tower() -> Area:
    return Area(id="REF-TOWER", name="Reference tower (Rev02 slide 7)", area_type="tower",
                tower_bays=4, tower_bay_target_m=2.5, tower_width_target_m=1.1, n_lifts=4,
                z_base=0.0, z_top=10.0, anchorage="tied", protection="all_sides", advance_guardrail=True,
                notes="Assumptions: decks on every lift, one hatch per lift, guardrails all sides, tied "
                      "(1 tie per 22 m2 face), advance guardrail modelled.")
