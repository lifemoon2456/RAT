from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rat.domain.translation import ProviderConfig, TranslationOptions
from rat.jobs.manager import JobControl
from rat.providers.settings_service import ProviderSettingsService
from rat.translation.glossary import GlossarySystem
from rat.translation.orchestrator import TranslationManager
from rat.ui.task_worker import TaskWorker


class TranslationPage(QWidget):
    busy_changed = Signal(bool)
    data_changed = Signal()

    def __init__(self, parent=None, *, manager_factory=TranslationManager):
        super().__init__(parent)
        self.manager_factory = manager_factory
        self.project = None
        self.busy = False
        self.control = None
        self.thread = self.worker = None
        layout = QVBoxLayout(self)
        notice = QLabel(
            "تُرسل النصوص المحمية والسياق المحدود إلى المزود المختار عند البدء. "
            "تُحفظ النتائج بعد كل دفعة. تُترك الترجمات الموجودة والمعتمدة دون استبدال. "
            "المحاكاة تعيد النص نفسه؛ لا يوجد تصدير أو تثبيت على اللعبة في هذه المرحلة."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.profile = QComboBox()
        self.jobs = QComboBox()
        self.glossary = QLineEdit()
        self.glossary.setPlaceholderText("CSV اختياري: source,target,locked,case_sensitive,notes")
        self.glossary_button = QPushButton("اختيار قاموس CSV")
        self.glossary_button.clicked.connect(self.choose_glossary)
        self.max_items, self.tokens, self.concurrency, self.rpm = [QSpinBox() for _ in range(4)]
        for widget, low, high, value in (
            (self.max_items, 1, 100, 12),
            (self.tokens, 1024, 100000, 6000),
            (self.concurrency, 1, 16, 2),
            (self.rpm, 1, 100000, 30),
        ):
            widget.setRange(low, high)
            widget.setValue(value)
        self.style = QLineEdit("modern_standard_arabic")
        for title, widget in (
            ("المزود المحفوظ", self.profile),
            ("مهمة محفوظة للاستئناف", self.jobs),
            ("القاموس", self.glossary),
            ("", self.glossary_button),
            ("أقصى عناصر الدفعة", self.max_items),
            ("ميزانية الإدخال التقريبية للـtokens", self.tokens),
            ("الطلبات المتزامنة", self.concurrency),
            ("طلبات/دقيقة — حسب حدود حسابك", self.rpm),
            ("أسلوب الترجمة", self.style),
        ):
            form.addRow(title, widget)
        layout.addLayout(form)
        self.retry_failed = QCheckBox(
            "أعد محاولة النتائج الفاشلة أو التي تحتاج مراجعة في المهمة المستأنفة"
        )
        layout.addWidget(self.retry_failed)
        controls = QHBoxLayout()
        self.start_button = QPushButton("بدء مهمة جديدة للنصوص المفقودة")
        self.resume_button = QPushButton("Resume — استئناف المحفوظ")
        self.pause_button = QPushButton("Pause — حفظ وتوقف مؤقت")
        self.stop_button = QPushButton("Stop — إيقاف")
        for button in (self.start_button, self.resume_button, self.pause_button, self.stop_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.status = QLabel("افتح مشروعًا ثم افهرس نصوصه.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.start_button.clicked.connect(lambda: self.start(False))
        self.resume_button.clicked.connect(lambda: self.start(True))
        self.pause_button.clicked.connect(lambda: self.control.pause() if self.control else None)
        self.stop_button.clicked.connect(lambda: self.control.stop() if self.control else None)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.setEnabled(False)

    def set_project(self, project):
        self.project = project
        self.setEnabled(project is not None)
        self.profile.clear()
        self.jobs.clear()
        self.glossary.clear()
        self.progress_bar.setValue(0)
        if project:
            self.refresh()

    def refresh(self):
        if self.project is None or self.busy:
            return
        self.profile.clear()
        configs = ProviderSettingsService(self.project).profiles()
        if not any(config.provider_id == "mock" for config in configs):
            configs.insert(0, ProviderConfig())
        for config in configs:
            self.profile.addItem(f"{config.provider_id} / {config.model or '—'}", config)
        self.jobs.clear()
        for job in self.manager_factory(self.project).list_jobs():
            self.jobs.addItem(
                f"{job['status']} / {job['profile']['provider_id']} / {job['job_id'][:10]}",
                job["job_id"],
            )

    def choose_glossary(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر قاموس CSV", filter="CSV (*.csv)")
        if path:
            self.glossary.setText(path)

    def start(self, resume):
        if self.busy or self.project is None:
            return
        manager = self.manager_factory(self.project)
        self.control = JobControl()
        try:
            if resume:
                job_id = self.jobs.currentData()
                if not job_id:
                    self.status.setText("لا توجد مهمة محفوظة للاستئناف.")
                    return
            else:
                from pathlib import Path

                glossary = (
                    GlossarySystem.from_csv(Path(self.glossary.text()))
                    if self.glossary.text().strip()
                    else GlossarySystem()
                )
                options = TranslationOptions(
                    max_items=self.max_items.value(),
                    max_input_tokens=self.tokens.value(),
                    concurrency=self.concurrency.value(),
                    requests_per_minute=self.rpm.value(),
                    style=self.style.text(),
                )
                job_id = manager.create_job(self.profile.currentData(), options, glossary)
        except Exception:
            self.status.setText(
                "تعذر إنشاء المهمة؛ افهرس النصوص وتحقق من إعدادات المزود والقاموس أولًا."
            )
            return
        retry = self.retry_failed.isChecked()
        self.busy = True
        self.busy_changed.emit(True)
        self.start_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.thread = QThread(self)
        self.worker = TaskWorker(
            lambda notify: manager.run(
                job_id, control=self.control, on_progress=notify, retry_failed=retry
            )
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.show_progress)
        self.worker.succeeded.connect(self.show_progress)
        self.worker.failed.connect(
            lambda code: self.status.setText(
                f"توقفت المهمة: {code}؛ التقدم المحفوظ متاح للاستئناف."
            )
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def show_progress(self, progress):
        self.progress_bar.setMaximum(max(1, progress.total))
        self.progress_bar.setValue(progress.total - progress.remaining)
        self.status.setText(
            f"الحالة: {progress.status}\nTotal: {progress.total} | "
            f"Translated: {progress.translated} | "
            f"Remaining: {progress.remaining} | Errors: {progress.errors}\n"
            f"محاكاة فقط: {progress.simulated} | محفوظ سابقًا/مستبعد: {progress.skipped}"
        )

    def finish(self):
        self.busy = False
        self.thread = self.worker = None
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.start_button.setEnabled(True)
        self.resume_button.setEnabled(True)
        self.refresh()
        self.busy_changed.emit(False)
        self.data_changed.emit()
