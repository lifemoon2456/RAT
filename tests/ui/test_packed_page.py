from packed_support import write_rpa

from rat.config.models import Settings
from rat.projects import ProjectService
from rat.ui.main_window import MainWindow


def open_page(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.create_project("Packed UI", tmp_path / "work")
    page = window.packed_page
    window.tabs.setCurrentWidget(page)
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    return window, page


def test_extract_packed_game_shows_counts_imports_text_and_cleans_only_workspace(qtbot, tmp_path):
    window, page = open_page(qtbot, tmp_path)
    game = tmp_path / "original"
    archive = write_rpa(game / "game/data.rpa", {"script.rpy": b'label start:\n    "Hello"\n'})
    before = archive.read_bytes()
    page.game_path.setText(str(game))
    page.extract()
    assert page.busy and not window.close_button.isEnabled()
    qtbot.waitUntil(lambda: not page.busy, timeout=20000)
    assert page.report.imported_count == 1 and page.model.rowCount() == 1
    assert "RPA: 1" in page.summary.text() and window.import_page.model.rowCount() == 1
    page.clean()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert page.report.status == "cleaned" and archive.read_bytes() == before
    assert window.import_page.model.rowCount() == 1


def test_ui_conflict_choice_is_explicit_and_applies_selected_archive(qtbot, tmp_path):
    _window, page = open_page(qtbot, tmp_path)
    game = tmp_path / "original"
    write_rpa(game / "game/a.rpa", {"script.rpy": b'label a:\n    "First"\n'})
    write_rpa(game / "game/b.rpa", {"script.rpy": b'label b:\n    "Second"\n'})
    page.game_path.setText(str(game))
    page.extract()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert page.report.status == "conflicts" and not page.pending
    chosen = next(item for item in page.report.files if item.archive == "game/b.rpa")
    page.candidates.setCurrentIndex(page.candidates.findData(chosen.file_id))
    page.choose_candidate()
    assert page.pending and page.report.status == "conflicts"
    page.apply_conflicts()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert page.report.status == "ready" and page.report.imported_count == 1
    assert any(item.published_path for item in page.report.files if item.file_id == chosen.file_id)
