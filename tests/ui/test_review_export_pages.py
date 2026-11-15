from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt

from rat.config.models import Settings
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.review import ReviewService
from rat.ui.main_window import MainWindow


def editor(qtbot, tmp_path):
    window = MainWindow(ProjectService(), Settings())
    qtbot.addWidget(window)
    window.show()
    assert window.create_project("review UI", tmp_path / "work")
    GameImportService().scan(
        window.session.path, Path(__file__).parents[1] / "fixtures/game_with_tl"
    )
    page = window.review_page
    window.tabs.setCurrentWidget(page)
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert page.model.rowCount() == 8
    return window, page


def test_editor_autosaves_filters_context_and_flushes_on_project_close(qtbot, tmp_path):
    window, page = editor(qtbot, tmp_path)
    page.table.setCurrentIndex(page.proxy.index(0, 0))
    record = page.current_record()
    target = record.source.source_text.replace("Hello", "مرحبًا")
    page.translation.setPlainText(target)
    qtbot.waitUntil(lambda: page.current_record().translation_text == target, timeout=8000)
    assert page.source_text.isReadOnly()
    assert page.before.toPlainText().startswith("Previous:")
    page.search.setText("does-not-exist")
    assert page.proxy.rowCount() == 0
    page.search.clear()
    page.table.setCurrentIndex(page.proxy.index(0, 0))
    record = page.current_record()
    page.translation.setPlainText(record.source.source_text)
    project_path = window.session.path
    assert window.close_project()
    saved = next(
        row for row in ReviewService(project_path).list_units() if row.unit_id == record.unit_id
    )
    assert saved.translation_text == record.source.source_text


def test_bulk_approve_lock_and_export_worker(qtbot, tmp_path):
    window, page = editor(qtbot, tmp_path)
    for record in page.model.records:
        page.model.service.save(record.unit_id, record.source.source_text)
    page.refresh()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    page.table.selectAll()
    page.bulk_action("approve")
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert all(row.state == "approved" for row in page.model.records)
    page.table.selectAll()
    page.bulk_action("lock")
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert all(row.locked for row in page.model.records)
    assert not page.model.flags(page.model.index(0, 1)) & Qt.ItemFlag.ItemIsEditable
    window.tabs.setCurrentWidget(window.export_page)
    window.export_page.start("export")
    assert not window.close_button.isEnabled()
    qtbot.waitUntil(lambda: not window.export_page.busy, timeout=15000)
    assert '"status": "completed"' in window.export_page.report.toPlainText()
    assert '"exported"' in window.export_page.report.toPlainText()


def test_retranslate_selected_row_shows_alternatives_without_replacing_draft(qtbot, tmp_path):
    _window, page = editor(qtbot, tmp_path)
    page.table.selectionModel().select(
        page.proxy.index(0, 0),
        QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
    )
    page.table.setCurrentIndex(page.proxy.index(0, 0))
    page.alternative_count.setValue(2)
    page.retranslate()
    qtbot.waitUntil(lambda: not page.busy, timeout=20000)
    assert page.alternatives.count() == 2
    assert page.current_record().translation_text in {None, ""}
    page.apply_alternative()
    qtbot.waitUntil(lambda: not page.busy, timeout=15000)
    assert page.current_record().translation_text
    assert page.current_record().state != "approved"
