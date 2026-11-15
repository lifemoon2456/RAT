import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rat.domain.models import SourceUnit  # noqa: E402
from rat.projects import ProjectService  # noqa: E402


@pytest.fixture
def project(tmp_path):
    with ProjectService().create("مشروع تجريبي", workspace=tmp_path / "workspaces") as session:
        yield session


@pytest.fixture
def source(project):
    path = Path(__file__).parent / "fixtures" / "source_unit.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return SourceUnit(project_id=project.project.project_id, **data)


def pytest_addoption(parser):
    parser.addoption(
        "--renpy-sdk",
        default=os.environ.get("RAT_RENPY_SDK"),
        help="Path to a trusted Windows Ren'Py SDK for the live fixture test",
    )


@pytest.fixture
def renpy_sdk(request):
    value = request.config.getoption("--renpy-sdk")
    if value is None:
        pytest.skip("Live SDK test requires --renpy-sdk or RAT_RENPY_SDK")
    return Path(value)
