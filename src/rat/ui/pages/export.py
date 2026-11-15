from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rat.diagnostics import write_diagnostics
from rat.exporters.backup import BackupManager
from rat.exporters.installation import InstallationService
from rat.exporters.manager import ExportManager
from rat.exporters.safe_io import checked_path
from rat.ui.task_worker import TaskWorker


class ExportPage(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.busy = False
        self.thread = self.worker = None
        layout = QVBoxLayout(self)
        notice = QLabel(
            "التصدير إلى مجلد exports مستقل داخل مشروع RAT. "
            "تُحجب النصوص المعطوبة والمعرفات غير الموثقة. "
            "لن تُعدّل ملفات اللعبة؛ إعداد الخطوط وRTL اختياري في تبويب العربية، "
            "التثبيت الصريح ينشئ نسخة لعبة جديدة مع نسخة احتياطية قبل تطبيق الحزمة."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.approved_only = QCheckBox("Export Approved Only — المعتمد فقط")
        self.approved_only.setChecked(True)
        self.zip_package = QCheckBox("إنشاء ZIP مع التقرير وتعليمات الاختبار")
        self.zip_package.setChecked(True)
        layout.addWidget(self.approved_only)
        layout.addWidget(self.zip_package)
        self.export_button = QPushButton("تصدير حزمة مستقلة")
        self.backup_button = QPushButton("إنشاء نسخة احتياطية لمشروع RAT")
        layout.addWidget(self.export_button)
        layout.addWidget(self.backup_button)
        self.extra_buttons = {}
        for mode, label in (
            ("restore", "استعادة نسخة مشروع إلى مجلد جديد"),
            ("install", "تثبيت آخر حزمة مكتملة على نسخة لعبة جديدة"),
            ("rollback", "استعادة ملفات نسخة اللعبة قبل التعريب"),
            ("diagnostics", "إنشاء تقرير تشخيص بلا أسرار"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, mode=mode: self.choose_operation(mode))
            self.extra_buttons[mode] = button
            layout.addWidget(button)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)
        self.export_button.clicked.connect(lambda: self.start("export"))
        self.backup_button.clicked.connect(lambda: self.start("backup"))
        self.setEnabled(False)

    def set_project(self, project):
        self.project = project
        self.setEnabled(project is not None)
        self.report.clear()
        self.status.clear()

    def choose_operation(self, mode):
        if self.busy or not self.project:
            return
        if mode == "diagnostics":
            path = checked_path(self.project, f"reports/diagnostic-{uuid4().hex}.json")
            self.start(mode, lambda _notify: write_diagnostics(path, self.project))
            return
        if mode in {"restore", "rollback"}:
            selected = QFileDialog.getExistingDirectory(
                self, "اختر مجلد النسخة الاحتياطية / التثبيت"
            )
            if not selected:
                return
            if mode == "rollback":
                self.start(mode, lambda _notify: InstallationService.restore_copy(Path(selected)))
                return
        parent = QFileDialog.getExistingDirectory(self, "اختر مكان إنشاء النسخة الجديدة")
        if not parent:
            return
        target = Path(parent) / f"RAT-{mode}-{uuid4().hex[:8]}"
        if mode == "restore":
            self.start(mode, lambda _notify: BackupManager.restore(Path(selected), target))
        else:

            def install(_notify):
                history = ExportManager(self.project).history()
                completed = next((item for item in history if item.status == "completed"), None)
                if completed is None:
                    raise ValueError("completed_export_required")
                return InstallationService(self.project).install_copy(completed.export_id, target)

            self.start(mode, install)

    def start(self, mode, operation=None):
        if self.busy or self.project is None:
            return
        approved, zip_package = self.approved_only.isChecked(), self.zip_package.isChecked()
        self.busy = True
        self.busy_changed.emit(True)
        self.export_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        for button in self.extra_buttons.values():
            button.setEnabled(False)
        self.thread = QThread(self)
        self.worker = TaskWorker(
            operation
            or (
                lambda _notify: (
                    ExportManager(self.project).export(
                        approved_only=approved, zip_package=zip_package
                    )
                    if mode == "export"
                    else BackupManager(self.project).create()
                )
            )
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self.show_result)
        self.worker.failed.connect(
            lambda code: self.status.setText(
                f"تعذرت العملية: {code}. راجع القوالب والمسار والصلاحيات."
            )
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def show_result(self, result):
        if hasattr(result, "exported"):
            self.status.setText(
                f"الحالة: {result.status} | مصدّر: {len(result.exported)} | "
                f"متجاهل: {len(result.skipped)} | أخطاء: {len(result.errors)}\n"
                f"المجلد: {result.destination}"
            )
            self.report.setPlainText(result.model_dump_json(indent=2))
        else:
            self.status.setText(f"اكتملت العملية في: {result}\nلم تتغير ملفات اللعبة الأصلية.")

    def finish(self):
        self.busy = False
        self.worker = self.thread = None
        self.export_button.setEnabled(True)
        self.backup_button.setEnabled(True)
        for button in self.extra_buttons.values():
            button.setEnabled(True)
        self.busy_changed.emit(False)
