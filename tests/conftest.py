import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
_tmp = tempfile.mkdtemp(prefix="vsr-test-")
os.environ.setdefault("VSR_DB", str(Path(_tmp) / "vsr.sqlite"))
os.environ.setdefault("VSR_FILES", str(Path(_tmp) / "files"))

from vsr.catalogue import load_bundle  # noqa: E402
from vsr.geometry import dxf_import  # noqa: E402

SAMPLE = ROOT / "samples" / "block_B12"


@pytest.fixture(scope="session")
def bundle():
    return load_bundle(ROOT / "data")


@pytest.fixture(scope="session")
def project():
    return json.loads((SAMPLE / "project.json").read_text())


@pytest.fixture(scope="session")
def dxf_result(project):
    return dxf_import.import_sections(SAMPLE / "B12_frame_sections.dxf", project["drawings"][0]["layer_mapping"],
                                      project["frame_spacing_m"])


@pytest.fixture(scope="session")
def sections(dxf_result):
    return {s.id: s for s in dxf_result["sections"]}
