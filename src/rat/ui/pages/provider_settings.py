from uuid import uuid4

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rat.domain.translation import ProviderConfig
from rat.providers.settings_service import ProviderSettingsService
from rat.ui.task_worker import TaskWorker

PROVIDERS = [
    ("Mock — محاكاة دون شبكة", "mock"),
    ("Gemini", "gemini"),
    ("OpenAI", "openai"),
    ("DeepSeek", "deepseek"),
    ("OpenRouter", "openrouter"),
    ("Google Translate — غير رسمي", "google_translate"),
    ("Custom OpenAI-compatible", "custom"),
]


class ProviderSettingsPage(QWidget):
    busy_changed = Signal(bool)
    saved = Signal()

    def __init__(self, parent=None, *, service_factory=ProviderSettingsService):
        super().__init__(parent)
        self.service_factory = service_factory
        self.project = None
        self.busy = False
        self.profile = ProviderConfig()
        self.thread = self.worker = None
        layout = QVBoxLayout(self)
        notice = QLabel(
            "اختبار الاتصال يرسل عينة قصيرة وقد يستهلك رصيدًا. الترجمة ترسل النص والسياق المحدود "
            "إلى المزود المختار. Google Translate هنا غير رسمي وقد ينقطع. "
            "المفاتيح تُحفظ في مخزن النظام الآمن؛ لا تحفظها ملفات المشروع."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.provider = QComboBox()
        for name, value in PROVIDERS:
            self.provider.addItem(name, value)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://your-endpoint.example/v1")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("مفتاح جديد؛ تركه فارغًا يحافظ على المفتاح المحفوظ لنفس الملف")
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 600)
        self.timeout.setValue(90)
        self.output_mode = QComboBox()
        self.output_mode.addItems(["json_schema", "json_object"])
        for label, widget in (
            ("المزود", self.provider),
            ("الموديل — يدوي أو من الخدمة", self.model),
            ("Base URL — للخدمة المخصصة فقط", self.base_url),
            ("API Key", self.key),
            ("المهلة بالثواني", self.timeout),
            ("صيغة الرد حسب دعم الموديل", self.output_mode),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        controls = QHBoxLayout()
        self.save_button = QPushButton("حفظ الإعدادات والمفتاح")
        self.test_button = QPushButton("Test Connection — اختبار الاتصال")
        self.models_button = QPushButton("جلب الموديلات")
        for button in (self.save_button, self.test_button, self.models_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status = QLabel("افتح مشروعًا أولًا.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.provider.currentIndexChanged.connect(self.choose_provider)
        self.save_button.clicked.connect(lambda: self.start("save"))
        self.test_button.clicked.connect(lambda: self.start("test"))
        self.models_button.clicked.connect(lambda: self.start("models"))
        self.setEnabled(False)

    def set_project(self, project):
        self.project = project
        self.key.clear()
        self.setEnabled(project is not None)
        self.choose_provider()

    def choose_provider(self):
        if self.busy:
            return
        provider_id = self.provider.currentData()
        configs = self.service_factory(self.project).profiles() if self.project else []
        self.profile = next(
            (item for item in reversed(configs) if item.provider_id == provider_id),
            ProviderConfig(provider_id=provider_id),
        )
        self.model.clear()
        self.model.setEditText(self.profile.model)
        self.base_url.setText(self.profile.base_url)
        self.base_url.setEnabled(provider_id == "custom")
        self.key.clear()
        self.key.setEnabled(provider_id not in {"mock", "google_translate"})
        self.timeout.setValue(int(self.profile.timeout_seconds))
        self.output_mode.setCurrentText(
            "json_object" if provider_id == "deepseek" else self.profile.output_mode
        )
        self.status.setText(
            "المفتاح لا يُعاد عرضه. اختر موديلًا متاحًا لحسابك؛ لا توجد قائمة أسماء ثابتة."
        )

    def config(self):
        base = self.base_url.text().strip() if self.provider.currentData() == "custom" else ""
        profile_id = self.profile.profile_id if base == self.profile.base_url else uuid4().hex
        return ProviderConfig(
            profile_id=profile_id,
            provider_id=self.provider.currentData(),
            model=self.model.currentText().strip(),
            base_url=base,
            timeout_seconds=self.timeout.value(),
            output_mode=self.output_mode.currentText(),
        )

    def start(self, action):
        if self.busy or self.project is None:
            return
        try:
            config = self.config()
        except ValueError:
            self.status.setText(
                "إعداد غير صالح؛ تحقق من رابط الخدمة دون أسرار أو query، واسم الموديل."
            )
            return
        secret = self.key.text()
        self.key.clear()
        service = self.service_factory(self.project)

        async def operation(_notify):
            service.save(config, secret)
            if action == "test":
                return await service.test_connection(config)
            if action == "models":
                return await service.list_models(config)
            return {"saved": True}

        self.busy = True
        self.busy_changed.emit(True)
        for widget in (self.provider, self.save_button, self.test_button, self.models_button):
            widget.setEnabled(False)
        self.status.setText("جارٍ تنفيذ الطلب…")
        self.thread = QThread(self)
        self.worker = TaskWorker(operation)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(lambda result: self.show_result(config, action, result))
        self.worker.failed.connect(
            lambda code: self.status.setText(
                "تعذر مخزن المفاتيح الآمن؛ لم تُحفظ كنص صريح."
                if code == "secure_storage_unavailable"
                else f"لم ينجح الطلب: {code}"
            )
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def show_result(self, config, action, result):
        self.profile = config
        if action == "models":
            previous = self.model.currentText()
            self.model.clear()
            self.model.addItems(result or [])
            if previous:
                self.model.setEditText(previous)
            self.status.setText(
                "جُلبت قائمة الخدمة."
                if result
                else "لا يدعم المزود قائمة موديلات؛ أدخل الاسم يدويًا."
            )
        elif action == "test":
            self.status.setText(
                "محاكاة محلية فقط — لم يُختبر API."
                if result.get("status") == "simulated"
                else "نجح طلب الاختبار الفعلي وفحص الرد وحماية رموزه."
            )
        else:
            self.status.setText("حُفظت الإعدادات؛ المفاتيح في مخزن النظام الآمن عند إدخالها.")
        self.saved.emit()

    def finish(self):
        self.busy = False
        self.thread = self.worker = None
        for widget in (self.provider, self.save_button, self.test_button, self.models_button):
            widget.setEnabled(True)
        self.busy_changed.emit(False)
