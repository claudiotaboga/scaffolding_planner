from vsr.engine.module import module_card


def test_module_card_sm8_250x114_vs_layher_257x109(bundle):
    c = module_card(bundle)
    A, B = c["systems"]["SM8"], c["systems"]["LAYHER_LW"]
    assert (A["bay_m"], A["width_m"]) == (2.50, 1.14) and (B["bay_m"], B["width_m"]) == (2.57, 1.09)
    assert c["deltas"]["same_topology"]                      # identical structure at this module
    assert A["components"]["Standard 2.0 m"]["weight_kg"] == 9.86 and A["components"]["Standard 2.0 m"]["status"] == "verified"
    assert B["components"]["Steel deck (bay)"]["status"] == "estimate"
    assert c["verdict"]["checks"], "unverified inputs must produce checks"
    # deltas are consistent with the facade figures
    k = (B["facade"]["kg_per_m2"] - A["facade"]["kg_per_m2"]) / A["facade"]["kg_per_m2"] * 100
    assert abs(k - c["deltas"]["kg_per_m2_pct"]) < 0.11
