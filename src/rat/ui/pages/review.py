import inspect

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rat.database.review_repository import ReviewRepository
from rat.domain.translation import ProviderConfig
from rat.jobs.manager import JobControl
from rat.providers.settings_service import ProviderSettingsService
from rat.review import ReviewService
from rat.ui.task_worker import TaskWorker
from rat.ui.widgets.editor_table import STATUS_LABELS, EditorFilter, EditorTableModel


class ReviewPage(QWidget):
    busy_changed = Signal(bool)
    data_changed = Signal()

    def __init__(self, parent=None, *, service_factory=ReviewService):
        super().__init__(parent)
        self.project = None
        self.service_factory = service_factory
        self.busy, self.dirty, self.loading = False, True, False
        self.current_id = None
        self.last_error = ""
        self.control = None
        self.thread = self.worker = None
        layout = QVBoxLayout(self)
        self.notice = QLabel(
            "تُحفظ الترجمة تلقائيًا كمسودة. المعتمد يحتاج Reject قبل تحريره، "
            "والمقفل يحتاج Unlock. إعادة الترجمة تنتج بدائل فقط."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        filters = QHBoxLayout()
        self.search, self.speaker_filter, self.file_filter = QLineEdit(), QLineEdit(), QLineEdit()
        for widget, placeholder in (
            (self.search, "بحث في الأصل والترجمة"),
            (self.speaker_filter, "الشخصية"),
            (self.file_filter, "الملف"),
        ):
            widget.setPlaceholderText(placeholder)
            filters.addWidget(widget)
            widget.textChanged.connect(self.apply_filters)
        self.status_filter, self.provider_filter = QComboBox(), QComboBox()
        self.status_filter.addItem("كل الحالات", "")
        for value, label in STATUS_LABELS.items():
            self.status_filter.addItem(label, value)
        self.provider_filter.addItem("كل المزودين", "")
        for widget in (self.status_filter, self.provider_filter):
            filters.addWidget(widget)
            widget.currentIndexChanged.connect(self.apply_filters)
        layout.addLayout(filters)
        self.model = EditorTableModel(self)
        self.proxy = EditorFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 280)
        layout.addWidget(self.table, 1)
        self.table.selectionModel().currentRowChanged.connect(self.choose_row)
        panel = QGridLayout()
        self.source_text, self.translation, self.before, self.after = [
            QPlainTextEdit() for _ in range(4)
        ]
        for widget in (self.source_text, self.before, self.after):
            widget.setReadOnly(True)
        self.source_text.setMaximumHeight(75)
        self.translation.setMaximumHeight(85)
        self.before.setMaximumHeight(55)
        self.after.setMaximumHeight(55)
        for row, left, right in (
            (0, self.source_text, self.translation),
            (1, self.before, self.after),
        ):
            panel.addWidget(left, row, 0)
            panel.addWidget(right, row, 1)
        self.source_text.setPlaceholderText("النص الأصلي — لا يُعدل")
        self.translation.setPlaceholderText("حرر الترجمة؛ حفظ تلقائي بعد التوقف عن الكتابة")
        self.before.setPlaceholderText("Previous context")
        self.after.setPlaceholderText("Next context")
        layout.addLayout(panel)
        controls = QHBoxLayout()
        self.actions = {}
        for action, title in (
            ("approve", "Approve — اعتماد"),
            ("reject", "Reject — رفض الاعتماد"),
            ("skip", "Skip — تجاهل"),
            ("lock", "Lock — قفل"),
            ("unlock", "Unlock — فتح القفل"),
        ):
            button = QPushButton(title)
            self.actions[action] = button
            button.clicked.connect(lambda _checked=False, name=action: self.bulk_action(name))
            controls.addWidget(button)
        self.previous_button, self.next_button, self.refresh_button = (
            QPushButton("Previous"),
            QPushButton("Next"),
            QPushButton("تحديث / QA"),
        )
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.refresh_button)
        self.previous_button.clicked.connect(lambda: self.navigate(-1))
        self.next_button.clicked.connect(lambda: self.navigate(1))
        self.refresh_button.clicked.connect(self.refresh)
        layout.addLayout(controls)
        alternative_controls = QHBoxLayout()
        self.profile, self.alternatives = QComboBox(), QComboBox()
        self.alternative_count = QSpinBox()
        self.alternative_count.setRange(1, 5)
        self.retranslate_button = QPushButton("Retranslate — بدائل للمحدد")
        self.retranslate_button.setToolTip(
            "طلبات صريحة إلى المزود المحدد؛ قد تستهلك رصيدًا. لا تستبدل المعتمد."
        )
        self.apply_button = QPushButton("تطبيق البديل كمسودة")
        self.stop_button = QPushButton("إيقاف طلب البدائل")
        self.stop_button.setEnabled(False)
        for widget in (
            self.profile,
            self.alternative_count,
            self.retranslate_button,
            self.alternatives,
            self.apply_button,
            self.stop_button,
        ):
            alternative_controls.addWidget(widget)
        layout.addLayout(alternative_controls)
        self.alternative_preview = QPlainTextEdit()
        self.alternative_preview.setReadOnly(True)
        self.alternative_preview.setMaximumHeight(70)
        self.alternative_preview.setPlaceholderText("النص الكامل للبديل المحدد")
        self.alternatives.currentIndexChanged.connect(self.preview_alternative)
        layout.addWidget(self.alternative_preview)
        self.retranslate_button.clicked.connect(self.retranslate)
        self.apply_button.clicked.connect(self.apply_alternative)
        self.stop_button.clicked.connect(lambda: self.control.stop() if self.control else None)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.save_current)
        self.translation.textChanged.connect(
            lambda: self.timer.start() if not self.loading else None
        )
        self.model.failed.connect(self.status.setText)
        self.model.saved.connect(self.inline_saved)
        self.setEnabled(False)

    def set_project(self, project):
        self.timer.stop()
        self.project = project
        self.current_id = None
        self.dirty = True
        self.model.set_records(())
        self.model.service = self.service_factory(project) if project else None
        self.setEnabled(project is not None)
        self.clear_panes()

    def activate(self):
        if self.dirty and self.project and self.isEnabled() and not self.busy:
            self.refresh()

    def refresh(self):
        if self.project and not self.busy and self.save_current():
            self.start_task(lambda _notify: self.model.service.list_units())

    def start_task(self, operation, *, network=False):
        if self.busy:
            return
        self.last_error = ""
        self.timer.stop()
        self.busy = True
        self.busy_changed.emit(True)
        self.table.setEnabled(False)
        self.translation.setReadOnly(True)
        for button in [
            *self.actions.values(),
            self.retranslate_button,
            self.apply_button,
            self.refresh_button,
        ]:
            button.setEnabled(False)
        self.stop_button.setEnabled(network)
        self.thread = QThread(self)

        async def execute(notify):
            result = operation(notify)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, tuple) else self.model.service.list_units()

        self.worker = TaskWorker(execute)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self.task_result)
        self.worker.failed.connect(self.show_error)
        self.worker.progress.connect(
            lambda progress: self.status.setText(
                f"بدائل: {progress.status} | متبقٍ {progress.remaining} | أخطاء {progress.errors}"
            )
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish_task)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def task_result(self, result):
        records = result
        current = self.current_id
        self.model.set_records(records)
        self.current_id = None
        self.provider_filter.blockSignals(True)
        selected = self.provider_filter.currentData()
        self.provider_filter.clear()
        self.provider_filter.addItem("كل المزودين", "")
        for name in sorted({record.provider_id for record in records if record.provider_id}):
            self.provider_filter.addItem(name, name)
        self.provider_filter.setCurrentIndex(max(0, self.provider_filter.findData(selected)))
        self.provider_filter.blockSignals(False)
        self.profile.clear()
        profiles = ProviderSettingsService(self.project).profiles()
        if not any(profile.provider_id == "mock" for profile in profiles):
            profiles.insert(0, ProviderConfig())
        for profile in profiles:
            self.profile.addItem(f"{profile.provider_id} / {profile.model or '—'}", profile)
        self.dirty = False
        self.apply_filters()
        for row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(row, 0))
            if self.model.records[source_index.row()].unit_id == current:
                self.table.setCurrentIndex(self.proxy.index(row, 0))
                break
        else:
            if self.proxy.rowCount():
                self.table.setCurrentIndex(self.proxy.index(0, 0))
        if not self.proxy.rowCount():
            self.clear_panes()
        self.status.setText(
            f"عدد السطور: {len(records)}. الحفظ مباشر؛ QA يعرض أخطاء حاجزة وتحذيرات إرشادية."
        )
        self.data_changed.emit()

    def finish_task(self):
        self.busy = False
        self.worker = self.thread = None
        self.table.setEnabled(True)
        for button in [
            *self.actions.values(),
            self.retranslate_button,
            self.apply_button,
            self.refresh_button,
        ]:
            button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.show_current()
        if self.last_error:
            self.status.setText(self.last_error)
        self.busy_changed.emit(False)

    def show_error(self, code):
        self.last_error = f"تعذرت العملية: {code}. تحقق من QA والقفل، وحدّث القائمة عند التعارض."
        self.status.setText(self.last_error)

    def current_record(self):
        return next(
            (record for record in self.model.records if record.unit_id == self.current_id), None
        )

    def clear_panes(self):
        self.loading = True
        for pane in (self.source_text, self.translation, self.before, self.after):
            pane.clear()
        self.loading = False
        self.alternatives.clear()

    def choose_row(self, current, _previous=None):
        if not self.loading and not self.save_current():
            return
        self.current_id = (
            self.model.records[self.proxy.mapToSource(current).row()].unit_id
            if current.isValid()
            else None
        )
        self.show_current()

    def show_current(self):
        record = self.current_record()
        if record is None:
            self.clear_panes()
            return
        self.loading = True
        self.source_text.setPlainText(record.source.source_text)
        self.translation.setPlainText(record.translation_text or "")
        self.translation.setReadOnly(self.busy or record.locked or record.state == "approved")
        context = self.model.service.context(record.unit_id, records=self.model.records)
        self.before.setPlainText("Previous: " + "\n".join(context["before"]))
        self.after.setPlainText("Next: " + "\n".join(context["after"]))
        self.alternatives.clear()
        for alternative in self.model.service.alternatives(record.unit_id):
            prefix = "محاكاة" if alternative.simulated else alternative.provider_id
            self.alternatives.addItem(f"{prefix}: {alternative.text[:65]}", alternative)
        self.loading = False
        if record.qa:
            self.status.setText(
                f"QA: {', '.join(issue.code for issue in record.qa.issues) or 'لا أخطاء مسجلة'} | "
                f"احتمال تجاوز الواجهة: {record.qa.overflow_risk} — "
                "تقريبي دون قياس الخط أو نافذة اللعبة"
            )

    def save_current(self):
        self.timer.stop()
        if self.loading or self.busy:
            return True
        record = self.current_record()
        if (
            record is None
            or self.translation.isReadOnly()
            or self.translation.toPlainText() == (record.translation_text or "")
        ):
            return True
        row = next(i for i, item in enumerate(self.model.records) if item.unit_id == record.unit_id)
        return self.model.setData(self.model.index(row, 1), self.translation.toPlainText())

    def preview_alternative(self, _index):
        alternative = self.alternatives.currentData()
        self.alternative_preview.setPlainText(alternative.text if alternative else "")

    def inline_saved(self, _records):
        self.show_current()
        self.data_changed.emit()

    def selected_ids(self):
        return [
            self.model.records[self.proxy.mapToSource(index).row()].unit_id
            for index in self.table.selectionModel().selectedRows()
        ]

    def bulk_action(self, action):
        if self.busy or not self.save_current():
            return
        ids = self.selected_ids()
        expected = {
            record.unit_id: ReviewRepository.etag(record)
            for record in self.model.records
            if record.unit_id in ids
        }
        self.start_task(lambda _notify: self.model.service.action(ids, action, expected=expected))

    def navigate(self, offset):
        row = max(0, min(self.proxy.rowCount() - 1, self.table.currentIndex().row() + offset))
        if self.proxy.rowCount() and self.save_current():
            self.table.setCurrentIndex(self.proxy.index(row, 0))

    def apply_filters(self, *_args):
        self.proxy.update_filter(
            query=self.search.text(),
            speaker=self.speaker_filter.text(),
            file=self.file_filter.text(),
            status=self.status_filter.currentData() or "",
            provider=self.provider_filter.currentData() or "",
        )

    def retranslate(self):
        if self.busy or not self.save_current():
            return
        ids, profile, count = (
            self.selected_ids(),
            self.profile.currentData(),
            self.alternative_count.value(),
        )
        self.control = JobControl()
        self.start_task(
            lambda notify: self.model.service.retranslate(
                ids, profile, count=count, control=self.control, on_progress=notify
            ),
            network=True,
        )

    def apply_alternative(self):
        alternative, record = self.alternatives.currentData(), self.current_record()
        if alternative and record and self.save_current():
            expected = ReviewRepository.etag(self.current_record())
            self.start_task(
                lambda _notify: self.model.service.apply_alternative(
                    alternative.alternative_id, expected_etag=expected
                )
            )
