import json
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog

from rat import __version__
from rat.config.models import Settings, load_settings
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.ui.about_dialog import about_text
from rat.ui.main_window import MainWindow


def test_about_and_workspace_choice_persist_to_explicit_config(qtbot, tmp_path, monkeypatch):
    config = tmp_path / "settings.yaml"
    window = MainWindow(ProjectService(), Settings(), settings_path=config)
    qtbot.addWidget(window)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("release", True))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path / "projects"))
    window.choose_new_project()
    assert window.session is not None
    assert load_settings(config).app.workspace_dir == tmp_path / "projects"
    assert __version__ in about_text() and "Beta" in window.windowTitle()
    window.close()


def test_diagnostics_button_uses_core_worker_and_produces_safe_report(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    assert window.create_project("diagnostics", tmp_path / "workspace")
    GameImportService().scan(
        window.session.path, Path(__file__).parents[1] / "fixtures/game_with_tl"
    )
    window.export_page.choose_operation("diagnostics")
    qtbot.waitUntil(lambda: not window.export_page.busy, timeout=15000)
    reports = list((window.session.path / "reports").glob("diagnostic-*.json"))
    assert len(reports) == 1
    result = json.loads(reports[0].read_text())
    assert result["project"]["units"] == 8 and "paths" in result["omitted"]
    window.close()
