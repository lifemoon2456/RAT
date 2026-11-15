from PySide6.QtCore import Qt

from rat.arabic.runtime import ArabicRuntimeService
from rat.config.models import Settings
from rat.projects import ProjectService
from rat.ui.main_window import MainWindow


def window_for(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.create_project("Arabic Runtime UI", tmp_path / "work")
    window.tabs.setCurrentWidget(window.arabic_page)
    return window


def test_font_preview_works_with_unknown_version_and_warns_without_claiming_runtime(
    qtbot, tmp_path
):
    window = window_for(qtbot, tmp_path)
    page = window.arabic_page
    qtbot.mouseClick(page.preview_button, Qt.MouseButton.LeftButton)
    assert page.busy and not window.close_button.isEnabled()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert "unknown" in page.status.text()
    assert "Build 42 / 123" in page.preview.toPlainText()
    assert "Alex" in page.preview.toPlainText() and "٣٤٥" in page.preview.toPlainText()
    assert not ArabicRuntimeService(window.session.path).load().runtime.enabled


def test_confirmed_version_font_sizes_save_reopen_and_disable(qtbot, tmp_path):
    window = window_for(qtbot, tmp_path)
    page = window.arabic_page
    page.enabled.setChecked(True)
    page.target.setText("8.5.3")
    page.confirm_version.setChecked(True)
    page.sizes["history"].setValue(36)
    page.run("save")
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    project = window.session.path
    saved = ArabicRuntimeService(project).load()
    assert saved.runtime.enabled and saved.runtime.sizes.history == 36
    assert saved.runtime.primary_font.path.startswith("runtime/fonts/")
    assert window.close_project() and window.open_project(project)
    assert window.arabic_page.enabled.isChecked()
    assert window.arabic_page.sizes["history"].value() == 36
    window.arabic_page.enabled.setChecked(False)
    window.arabic_page.run("save")
    qtbot.waitUntil(lambda: not window.arabic_page.busy, timeout=15000)
    assert not ArabicRuntimeService(project).load().runtime.enabled


def test_missing_font_is_warned_and_cannot_enable_layer(qtbot, tmp_path):
    window = window_for(qtbot, tmp_path)
    page = window.arabic_page
    page.primary.setText(str(tmp_path / "missing.ttf"))
    page.run("preview")
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert "font_file_or_license_invalid" in page.status.text()
    page.enabled.setChecked(True)
    page.target.setText("8.5.3")
    page.confirm_version.setChecked(True)
    page.run("save")
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert not ArabicRuntimeService(window.session.path).load().runtime.enabled
