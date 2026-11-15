from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from rat.config.models import Settings
from rat.projects import ProjectService
from rat.ui.main_window import MainWindow


def test_choose_game_async_import_search_and_filters(qtbot, tmp_path, monkeypatch):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.create_project("UI import", tmp_path / "projects")
    page = window.import_page
    fixture = Path(__file__).resolve().parents[1] / "fixtures/game_with_tl"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(fixture))
    qtbot.mouseClick(page.game_button, Qt.MouseButton.LeftButton)
    assert page.game_path.text() == str(fixture)
    qtbot.mouseClick(page.scan_button, Qt.MouseButton.LeftButton)
    assert page.busy
    assert not window.close_button.isEnabled()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert page.model.rowCount() == 8
    assert len(page.report.protection) == 8
    assert all(item.ready for item in page.report.protection)
    page.search.setText("player_name")
    assert page.proxy.rowCount() == 1
    page.table.setCurrentIndex(page.proxy.index(0, 0))
    assert "⟦PH_" in page.protection_preview.toPlainText()
    assert "[player_name]" not in page.protection_preview.toPlainText()
    page.search.clear()
    page.kind_filter.setCurrentIndex(page.kind_filter.findData("menu_choice"))
    assert page.proxy.rowCount() == 2
    page.kind_filter.setCurrentIndex(0)
    page.confidence_filter.setCurrentIndex(page.confidence_filter.findData("unverified"))
    assert page.proxy.rowCount() == 0
    page.confidence_filter.setCurrentIndex(0)
    path = window.session.path
    window.close_project()
    assert window.open_project(path)
    assert window.import_page.model.rowCount() == 8


def test_failed_scan_is_visible_and_current_data_survives(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.create_project("UI error", tmp_path / "projects")
    page = window.import_page
    page.game_path.setText(str(tmp_path / "missing"))
    page.start_scan()
    qtbot.waitUntil(lambda: not page.busy, timeout=10000)
    assert "غير صالح" in page.summary.text()
    assert window.session is not None
