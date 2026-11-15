from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QSortFilterProxyModel,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rat.domain.packed import PackedOptions
from rat.extraction.packed_manager import PackedGameService
from rat.ui.task_worker import TaskWorker


class PackedFilesModel(QAbstractTableModel):
    columns = (
        "الأرشيف",
        "المسار الأصلي",
        "الاستخراج",
        "فك RPYC",
        "SHA256",
        "المسار المنشور",
        "المشكلات",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = ()

    def set_files(self, files):
        self.beginResetModel()
        self.files = tuple(files)
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.files)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.files[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join([item.original_path, item.workspace_path or "", *item.warnings])
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                item.archive or "ملف مباشر",
                item.original_path,
                item.status,
                (item.decompile_status or "—") + (" / جزئي" if item.partial else ""),
                item.sha256 or "—",
                item.published_path or "—",
                item.error_code or ", ".join(item.warnings),
            )[index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                self.columns[section]
                if orientation == Qt.Orientation.Horizontal
                else str(section + 1)
            )
        return None


class PackedGamePage(QWidget):
    busy_changed = Signal(bool)
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.busy, self.dirty = False, True
        self.thread = self.worker = None
        self.report = None
        self.pending = {}
        layout = QVBoxLayout(self)
        notice = QLabel(
            "الاستخراج داخل staging/packed في مشروع RAT فقط. ملفات الوسائط اختيارية. "
            "قارئ RPYC غير تنفيذي ومحدود بالعقد المدعومة؛ "
            "الاستعادة الجزئية ليست لعبة قابلة للتشغيل. "
            "التنظيف يحذف مساحة التشغيل المحددة، "
            "ويحفظ قاعدة الترجمات والتقارير وأصول اللعبة."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        self.game_path = QLineEdit()
        self.game_path.setPlaceholderText("مجلد اللعبة الذي يحتوي game")
        browse = QPushButton("اختيار اللعبة")
        browse.clicked.connect(self.choose_game)
        row.addWidget(self.game_path)
        row.addWidget(browse)
        layout.addLayout(row)
        options = QHBoxLayout()
        self.decompile = QCheckBox("محاولة فك RPYC الذي لا يتوفر له RPY")
        self.assets = QCheckBox("استخراج الوسائط من الأرشيفات أيضًا")
        self.import_texts = QCheckBox("فهرسة النصوص بعد حل التعارضات")
        self.import_texts.setChecked(True)
        for widget in (self.decompile, self.assets, self.import_texts):
            options.addWidget(widget)
        layout.addLayout(options)
        version_row = QHBoxLayout()
        self.version = QLineEdit()
        self.version.setPlaceholderText("إصدار يدوي عند غياب دليل اللعبة، مثل 8.5.3")
        self.version_confirmed = QCheckBox("تحققت من الإصدار؛ SDK ليس دليلًا على نسخة اللعبة")
        version_row.addWidget(self.version)
        version_row.addWidget(self.version_confirmed)
        layout.addLayout(version_row)
        controls = QHBoxLayout()
        self.extract_button = QPushButton("Extract Packed Game — استخراج اللعبة المجمعة")
        self.clean_button = QPushButton("Clean Workspace — تنظيف المساحة المحددة")
        self.refresh_button = QPushButton("تحديث السجل")
        self.runs = QComboBox()
        self.runs.currentIndexChanged.connect(self.select_run)
        self.extract_button.clicked.connect(self.extract)
        self.clean_button.clicked.connect(self.clean)
        self.refresh_button.clicked.connect(self.refresh)
        for widget in (self.extract_button, self.clean_button, self.refresh_button, self.runs):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث في مسارات الملفات والحالات والأخطاء")
        layout.addWidget(self.search)
        self.model = PackedFilesModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(1, 250)
        layout.addWidget(self.table, 1)
        conflict_row = QHBoxLayout()
        self.conflicts, self.candidates = QComboBox(), QComboBox()
        self.conflicts.currentIndexChanged.connect(self.select_conflict)
        self.choose_button = QPushButton("تسجيل اختيار التعارض")
        self.apply_button = QPushButton("تطبيق الحلول المحددة وإعادة الفهرسة")
        self.choose_button.clicked.connect(self.choose_candidate)
        self.apply_button.clicked.connect(self.apply_conflicts)
        for widget in (self.conflicts, self.candidates, self.choose_button, self.apply_button):
            conflict_row.addWidget(widget)
        layout.addLayout(conflict_row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_project(None)

    def set_project(self, project):
        self.project, self.report = project, None
        self.dirty, self.pending = True, {}
        self.game_path.clear()
        self.runs.clear()
        self.conflicts.clear()
        self.candidates.clear()
        self.model.set_files(())
        self.summary.clear()
        self.status.clear()
        self.setEnabled(project is not None)

    def activate(self):
        if self.project and self.dirty and not self.busy:
            self.refresh()

    def choose_game(self):
        path = QFileDialog.getExistingDirectory(self, "اختر مجلد اللعبة الأصلي")
        if path:
            self.game_path.setText(path)

    def refresh(self):
        if self.project and not self.busy:
            self.start(lambda _notify: {"reports": PackedGameService(self.project).history()})

    def extract(self):
        if not self.project or self.busy:
            return
        try:
            options = PackedOptions(
                decompile=self.decompile.isChecked(),
                include_assets=self.assets.isChecked(),
                import_texts=self.import_texts.isChecked(),
                engine_version=self.version.text().strip(),
                engine_version_confirmed=self.version_confirmed.isChecked(),
            )
        except ValueError:
            self.status.setText("تحقق من صيغة الإصدار: ثلاثة أرقام مثل 8.5.3.")
            return
        source = Path(self.game_path.text())
        self.start(
            lambda notify: PackedGameService(self.project).extract(source, options, progress=notify)
        )

    def clean(self):
        if self.report and self.report.status != "cleaned" and not self.busy:
            run_id = self.report.run_id
            self.start(lambda _notify: PackedGameService(self.project).clean(run_id))

    def select_run(self, _index):
        report = self.runs.currentData()
        if report and not self.busy:
            self.show_report(report)

    def show_report(self, report):
        self.report, self.pending = report, {}
        self.model.set_files(report.files)
        self.show_counts(report)
        self.conflicts.clear()
        for conflict in report.conflicts:
            self.conflicts.addItem(
                f"{conflict.path} / {'محلول' if conflict.resolved else 'يحتاج اختيارًا'}", conflict
            )
        self.select_conflict(0)
        self.status.setText(
            f"Manifest: {self.project / report.manifest_relpath}\n"
            f"Workspace: {self.project / report.workspace_relpath}\n"
            f"فشل الفهرسة: {report.import_error or '—'} | " + ", ".join(report.warnings)
        )

    def show_counts(self, report):
        extracted = sum(item.status == "extracted" for item in report.files)
        decompiled = sum(item.status == "decompiled" for item in report.files)
        failed = sum(
            item.status == "failed" or item.decompile_status in {"failed", "unsupported"}
            for item in report.files
        )
        orphan = sum(item.orphan_rpyc for item in report.files)
        conflicts = sum(not conflict.resolved for conflict in report.conflicts)
        self.summary.setText(
            f"RPA: {report.rpa_count} | RPYC: {report.rpyc_count} | "
            f"مستخرج: {extracted} | مفكوك: {decompiled} | فشل/غير مدعوم: {failed} | "
            f"RPYC دون مصدر: {orphan} | تعارضات معلقة: {conflicts} | "
            f"نصوص مستوردة: {report.imported_count} | الحالة: {report.status}"
        )

    def select_conflict(self, _index):
        self.candidates.clear()
        self.candidates.addItem("اختر نسخة أو تجاهل التعارض", "__pending__")
        self.candidates.addItem("تجاهل كل ملفات هذا التعارض", "__skip__")
        conflict = self.conflicts.currentData()
        if not conflict or not self.report:
            return
        by_id = {item.file_id: item for item in self.report.files}
        for file_id in conflict.candidates:
            item = by_id[file_id]
            self.candidates.addItem(
                f"{item.archive or 'مباشر'} / {item.original_path} / {item.sha256[:10]}", file_id
            )

    def choose_candidate(self):
        conflict, candidate = self.conflicts.currentData(), self.candidates.currentData()
        if conflict and candidate != "__pending__":
            self.pending[conflict.conflict_id] = None if candidate == "__skip__" else candidate
            self.status.setText(f"اختيارات مسجلة: {len(self.pending)}؛ اضغط تطبيق لحفظها.")

    def apply_conflicts(self):
        if self.report and self.pending and not self.busy:
            run_id, selections = self.report.run_id, dict(self.pending)
            self.start(
                lambda notify: PackedGameService(self.project).resolve(
                    run_id, selections, progress=notify
                )
            )

    def start(self, operation):
        self.busy = True
        self.busy_changed.emit(True)
        for widget in (
            self.extract_button,
            self.clean_button,
            self.refresh_button,
            self.runs,
            self.choose_button,
            self.apply_button,
        ):
            widget.setEnabled(False)
        self.thread = QThread(self)
        self.worker = TaskWorker(operation)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.show_counts)
        self.worker.succeeded.connect(self.result)
        self.worker.failed.connect(
            lambda code: self.status.setText(
                "تعذرت العملية: "
                + code
                + ". تحقق من المسارات والإصدار والتقرير؛ لم تُعدّل أصول اللعبة."
            )
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def result(self, result):
        reports = result["reports"] if isinstance(result, dict) else [result]
        self.runs.blockSignals(True)
        existing = (
            {
                self.runs.itemData(index).run_id: self.runs.itemData(index)
                for index in range(self.runs.count())
            }
            if not isinstance(result, dict)
            else {}
        )
        existing.update({report.run_id: report for report in reports})
        self.runs.clear()
        for report in sorted(existing.values(), key=lambda report: report.created_at, reverse=True):
            self.runs.addItem(
                f"{report.created_at[:19]} / {report.status} / {report.run_id[:8]}", report
            )
        self.runs.blockSignals(False)
        selected = reports[0] if reports else None
        if selected:
            for index in range(self.runs.count()):
                if self.runs.itemData(index).run_id == selected.run_id:
                    self.runs.setCurrentIndex(index)
                    break
            self.show_report(selected)
        self.dirty = False
        if not isinstance(result, dict):
            self.data_changed.emit()

    def finish(self):
        self.busy = False
        self.worker = self.thread = None
        for widget in (
            self.extract_button,
            self.clean_button,
            self.refresh_button,
            self.runs,
            self.choose_button,
            self.apply_button,
        ):
            widget.setEnabled(True)
        self.busy_changed.emit(False)
