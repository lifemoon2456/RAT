from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rat.domain.discovery import ImportReport
from rat.extraction.scanner import GameImportService
from rat.ui.widgets.unit_table import UnitFilter, UnitTableModel
from rat.ui.workers import ImportWorker

ERRORS = {
    "sdk_unsafe_or_unsupported_source": (
        "المصدر يحتوي Python أو تعليمات غير مدعومة للتوليد الآمن. "
        "يمكن فهرسته وقراءة قوالبه الموجودة دون تشغيله."
    ),
    "invalid_game_directory": "مجلد اللعبة غير صالح أو رابط غير مسموح.",
    "missing_game_directory": "اختر مجلد اللعبة الذي يحتوي مجلد game.",
    "workspace_overlaps_game": "يجب أن تكون مساحة مشروع RAT منفصلة عن مجلد اللعبة.",
    "sdk_required": "حدد مسار SDK أولًا.",
    "sdk_requires_complete_declarative_source": (
        "يتطلب التوليد الآمن مصدرًا كاملًا دون أرشيفات أو وحدات Python أو ملفات مجمعة بلا مصدر. "
        "يمكنك قراءة القوالب الموجودة والفهرسة الأولية."
    ),
    "invalid_sdk_layout": "لا يحتوي المجلد Ren'Py SDK بالتخطيط المدعوم.",
    "sdk_engine_version_mismatch": "إصدار SDK لا يطابق عائلة إصدار اللعبة المكتشفة.",
    "sdk_timeout": "انتهت مهلة SDK. بقيت ملفات اللعبة الأصلية دون تعديل.",
}
STAGES = {
    "inventory": "جرد الملفات…",
    "sdk_generation": "توليد القوالب على نسخة عمل…",
    "parse_templates": "قراءة القوالب…",
    "save": "حفظ نتائج الفهرسة…",
}


class GameImportPage(QWidget):
    busy_changed = Signal(bool)
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Path | None = None
        self.report: ImportReport | None = None
        self.busy = False
        self.thread = None
        self.worker = None
        layout = QVBoxLayout(self)
        form = QGridLayout()
        self.game_path = QLineEdit()
        self.game_path.setPlaceholderText("مجلد اللعبة الذي يحتوي game")
        self.game_button = QPushButton("اختيار مجلد اللعبة")
        self.sdk_path = QLineEdit()
        self.sdk_path.setPlaceholderText("Ren'Py SDK — اختياري عند قراءة قوالب موجودة")
        self.sdk_button = QPushButton("اختيار SDK")
        self.generate = QCheckBox("توليد قوالب arabic الرسمية على نسخة عمل مستقلة")
        self.scan_button = QPushButton("فهرسة النصوص")
        for row, (field, button) in enumerate(
            ((self.game_path, self.game_button), (self.sdk_path, self.sdk_button))
        ):
            form.addWidget(field, row, 0)
            form.addWidget(button, row, 1)
        form.addWidget(self.generate, 2, 0)
        form.addWidget(self.scan_button, 2, 1)
        layout.addLayout(form)
        self.summary = QLabel("افتح مشروع RAT أو أنشئه أولًا، ثم اختر اللعبة.")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        filters = QGridLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث في النص أو المعرّف أو المسار أو الشخصية")
        self.kind_filter = QComboBox()
        for title, value in (
            ("كل الأنواع", ""),
            ("حوار", "dialogue"),
            ("سرد", "narration"),
            ("خيارات", "menu_choice"),
            ("سلاسل", "string"),
            ("شاشات", "screen_text"),
        ):
            self.kind_filter.addItem(title, value)
        self.confidence_filter = QComboBox()
        for title, value in (
            ("كل مستويات الثقة", ""),
            ("SDK ومصدر متطابق", "official_template"),
            ("قالب موجود", "existing_template"),
            ("دون معرّف رسمي", "unverified"),
        ):
            self.confidence_filter.addItem(title, value)
        filters.addWidget(self.search, 0, 0)
        filters.addWidget(self.kind_filter, 0, 1)
        filters.addWidget(self.confidence_filter, 0, 2)
        layout.addLayout(filters)
        self.model = UnitTableModel(self)
        self.proxy = UnitFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 370)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 220)
        layout.addWidget(self.table, 1)
        self.protection_preview = QPlainTextEdit()
        self.protection_preview.setReadOnly(True)
        self.protection_preview.setMaximumHeight(75)
        self.protection_preview.setPlaceholderText(
            "اختر صفًا لمعاينة النص المحمي؛ المعاينة لا ترسل النص إلى أي خدمة."
        )
        layout.addWidget(self.protection_preview)
        self.issues = QPlainTextEdit()
        self.issues.setReadOnly(True)
        self.issues.setMaximumHeight(100)
        self.issues.setPlaceholderText("تحذيرات التغطية ومشكلات القراءة تظهر هنا.")
        layout.addWidget(self.issues)
        self.game_button.clicked.connect(self.choose_game)
        self.sdk_button.clicked.connect(self.choose_sdk)
        self.scan_button.clicked.connect(self.start_scan)
        self.table.selectionModel().currentRowChanged.connect(self.show_protection)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.kind_filter.currentIndexChanged.connect(
            lambda: self.proxy.set_kind(self.kind_filter.currentData())
        )
        self.confidence_filter.currentIndexChanged.connect(
            lambda: self.proxy.set_confidence(self.confidence_filter.currentData())
        )
        self.setEnabled(False)

    def set_project(self, project: Path | None) -> None:
        self.project = project
        self.report = None
        self.model.set_units(())
        self.game_path.clear()
        self.sdk_path.clear()
        self.issues.clear()
        self.protection_preview.clear()
        self.setEnabled(project is not None)
        self.summary.setText("اختر مجلد اللعبة لقراءة نصوصه دون تعديل أصوله.")
        if project is not None:
            try:
                report = GameImportService().load(project)
                if report:
                    self.show_report(report)
            except Exception:
                self.show_error("saved_inventory_unavailable")

    def choose_game(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "اختر مجلد اللعبة الذي يحتوي game")
        if directory:
            self.game_path.setText(directory)

    def choose_sdk(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "اختر مجلد Ren'Py SDK")
        if directory:
            self.sdk_path.setText(directory)

    def start_scan(self) -> None:
        if self.busy or self.project is None:
            return
        if not self.game_path.text().strip():
            self.show_error("missing_game_directory")
            return
        self.busy = True
        self.busy_changed.emit(True)
        self.scan_button.setEnabled(False)
        self.thread = QThread(self)
        sdk = Path(self.sdk_path.text()) if self.sdk_path.text().strip() else None
        self.worker = ImportWorker(
            self.project, Path(self.game_path.text()), sdk, self.generate.isChecked()
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda stage: self.summary.setText(STAGES.get(stage, stage)))
        self.worker.succeeded.connect(self.show_report)
        self.worker.succeeded.connect(lambda _report: self.data_changed.emit())
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish_scan)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def finish_scan(self) -> None:
        self.busy = False
        self.scan_button.setEnabled(True)
        self.worker = None
        self.thread = None
        self.busy_changed.emit(False)

    def show_report(self, report: ImportReport) -> None:
        self.report = report
        self.game_path.setText(
            report.packed_source.original_game_dir
            if report.packed_source
            else report.inventory.game_dir
        )
        self.sdk_path.setText(report.sdk_dir or "")
        self.model.set_units(report.units, report.protection)
        self.protection_preview.clear()
        counts = {
            suffix: sum(item.extension == suffix for item in report.inventory.files)
            for suffix in (".rpy", ".rpym", ".rpyc", ".rpymc", ".rpa")
        }
        files = " | ".join(f"{suffix}: {count}" for suffix, count in counts.items())
        engine = report.inventory.engine
        version = engine.version or "غير معروف"
        languages = ", ".join(report.inventory.translation_languages) or "لا توجد"
        self.summary.setText(
            f"إصدار اللعبة: {version} ({engine.confidence}) | SDK: {report.sdk_version or '—'}\n"
            f"{files}\nلغات tl: {languages} | النصوص الحالية: {len(report.units)} | "
            f"جديد: {report.added} | أعيد استخدامه: {report.reused} | تغير مصدره: {report.changed}"
            f"\nحماية المصدر: {sum(item.ready for item in report.protection)} جاهز | "
            f"{sum(not item.ready for item in report.protection)} يحتاج مراجعة"
            " — لا توجد ترجمة فعلية"
        )
        lines = [
            f"{issue.code}: {issue.path or ''}{':' + str(issue.line) if issue.line else ''}"
            for issue in report.issues
        ]
        by_id = {unit.unit_id: unit for unit in report.units}
        lines.extend(
            f"protection/{issue.code}: {by_id[item.unit_id].source_relpath}:"
            f"{by_id[item.unit_id].source_line or '—'}"
            for item in report.protection
            for issue in item.result.issues
        )
        self.issues.setPlainText("\n".join(lines) or "لا توجد مشكلات مسجلة للملفات المقروءة.")

    def show_protection(self, current, _previous=None) -> None:
        if not current.isValid():
            self.protection_preview.clear()
            return
        index = self.proxy.mapToSource(current)
        source = self.model.units[index.row()]
        prepared = self.model.protection.get(source.unit_id)
        if prepared and prepared.ready and prepared.result.protected:
            self.protection_preview.setPlainText(prepared.result.protected.masked_text)
        else:
            self.protection_preview.setPlainText("تعذرت الحماية؛ راجع رموز المشكلات أسفل الجدول.")

    def show_error(self, code: str) -> None:
        self.summary.setText(ERRORS.get(code, f"تعذرت الفهرسة: {code}"))
