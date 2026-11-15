from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog

from rat.config.models import Settings
from rat.projects import ProjectService
from rat.ui.main_window import MainWindow


def test_window_creates_closes_and_reopens_project(qtbot, tmp_path, monkeypatch):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert not window.close_button.isEnabled()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("تجربة الواجهة", True))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path))
    qtbot.mouseClick(window.create_button, Qt.MouseButton.LeftButton)
    assert window.session is not None
    path = window.session.path
    identity = window.session.project
    assert "تجربة الواجهة" in window.project_label.text()
    qtbot.mouseClick(window.close_button, Qt.MouseButton.LeftButton)
    assert window.session is None
    assert not window.close_button.isEnabled()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(path))
    qtbot.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    assert window.session.project == identity
    window.close()
    assert window.session is None


def test_failed_open_retains_current_project(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    assert window.create_project("keep", tmp_path)
    current = window.session
    assert not window.open_project(tmp_path / "missing")
    assert window.session is current
    assert "تعذرت" in window.statusBar().currentMessage()


def test_cancelled_create_has_no_side_effect(qtbot, tmp_path, monkeypatch):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("", False))
    qtbot.mouseClick(window.create_button, Qt.MouseButton.LeftButton)
    assert window.session is None
    assert list(tmp_path.iterdir()) == []
