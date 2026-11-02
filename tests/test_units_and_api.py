import pytest

from vsr.engine.bom import compose_standard
from vsr.engine.layout import fill_run
from vsr.geometry.mapping import guess_meaning, parse_frame


def test_fill_run_bounded_exact():
    bays, res, inf, _ = fill_run(7.5, [1.8, 2.5, 3.0], True, True, 0.2, 1.0)
    assert abs(sum(bays) - 7.5) < 1e-9 and not inf


def test_fill_run_bounded_infill():
    bays, res, inf, why = fill_run(1.2, [1.8, 2.5, 3.0], True, True, 0.2, 1.0)
    assert inf and res == pytest.approx(1.2) and bays == []


def test_fill_run_free_end_never_infills():
    bays, res, inf, _ = fill_run(6.37, [1.8, 2.5, 3.0], False, True, 0.2, 1.0)
    assert not inf and sum(bays) >= 6.37 - 0.2


def test_compose_standard():
    assert compose_standard(9.0, [4.0, 3.0, 2.0, 1.0, 0.5]) == [4.0, 4.0, 1.0]
    assert compose_standard(14.5, [4.0, 3.0, 2.0, 1.0, 0.5]) == [4.0, 4.0, 4.0, 2.0, 0.5]


def test_layer_heuristics():
    assert guess_meaning("HULL_SHELL") == "hull_shell"
    assert guess_meaning("CL") == "centreline"
    assert guess_meaning("FRAME_NO") == "frame_text"
    assert parse_frame("FR 146") == 146 and parse_frame("Fr.120.5") == 120.5


def test_api_end_to_end():
    from fastapi.testclient import TestClient
    from vsr.api.app import app
    with TestClient(app) as c:
        p = c.post("/api/projects/sample").json()
        assert len(p["sections"]) == 3
        r = c.post(f"/api/projects/{p['id']}/areas/REF-TOWER/run", json={"crew": 5}).json()
        assert r["comparison"]["recommended"] in r["results"]
        assert c.get(f"/api/runs/{r['run_id']}/excel").status_code == 200
        assert c.get(f"/api/runs/{r['run_id']}/trace/SM8.csv").text.startswith("run_id")
        s = c.get(f"/api/projects/{p['id']}/summary").json()
        assert "Mixed optimum" in s["policies"]
        # viewer cannot write
        assert c.post("/api/projects", json={"name": "x"}, headers={"X-VSR-Role": "viewer"}).status_code == 403
        # upload + inspect the sample DXF
        from conftest import SAMPLE
        with open(SAMPLE / "B12_frame_sections.dxf", "rb") as f:
            d = c.post(f"/api/projects/{p['id']}/drawings", files={"file": ("B12.dxf", f)}).json()
        assert d["inspect"]["frames_found"] == [128.0, 140.0, 152.0]
