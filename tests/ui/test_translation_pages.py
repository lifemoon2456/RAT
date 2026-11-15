from pathlib import Path

from PySide6.QtCore import Qt

from rat.config.models import Settings
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.ui.main_window import MainWindow


def test_provider_test_connection_mock_is_background_and_explicitly_simulated(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.create_project("provider UI", tmp_path / "work")
    page = window.provider_page
    window.tabs.setCurrentWidget(page)
    qtbot.mouseClick(page.test_button, Qt.MouseButton.LeftButton)
    assert page.busy
    assert not window.close_button.isEnabled()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert "محاكاة" in page.status.text() and "لم يُختبر API" in page.status.text()
    assert page.key.text() == ""
    assert window.translation_page.profile.count() == 1


def test_translation_ui_progress_and_saved_resume_use_the_shared_core(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.create_project("translation UI", tmp_path / "work")
    fixture = Path(__file__).parents[1] / "fixtures/game_with_tl"
    GameImportService().scan(window.session.path, fixture)
    page = window.translation_page
    window.tabs.setCurrentWidget(page)
    page.rpm.setValue(100000)
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    assert page.busy
    qtbot.waitUntil(lambda: not page.busy, timeout=20000)
    assert "Translated: 0" in page.status.text()
    assert "محاكاة فقط: 8" in page.status.text()
    assert "Remaining: 0" in page.status.text()
    assert window.import_page.model.rowCount() == 8
    assert page.jobs.count() == 1
    qtbot.mouseClick(page.resume_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert "محاكاة فقط: 8" in page.status.text()
    project_path = window.session.path
    window.close_project()
    assert window.open_project(project_path)
    assert window.translation_page.jobs.count() == 1
