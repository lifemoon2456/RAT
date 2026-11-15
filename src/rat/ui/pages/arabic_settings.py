from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from rat.arabic.preview import PREVIEW_SAMPLE, preview_html
from rat.arabic.runtime import ArabicRuntimeService
from rat.config.models import ArabicSettings
from rat.domain.arabic import FontChoice, RuntimeOptions, RuntimeSizes
from rat.ui.task_worker import TaskWorker


class ArabicSettingsPage(QWidget):
    busy_changed = Signal(bool)
    saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.busy = False
        self.thread = self.worker = None
        self.font_ids = []
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        self.notice = QLabel(
            "الإعدادات لا تغيّر اللعبة. احفظ ثم صدّر حزمة جديدة. "
            "معاينة Qt تقريبية؛ الاختبار الحقيقي داخل مشروع Ren’Py التجريبي. "
            "الإصدار المجهول والقديم غير المتحقق يمنعان تضمين Runtime؛ لا نقلب النص يدويًا."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.enabled = QCheckBox("تضمين Arabic Runtime Layer عند التصدير")
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.primary, self.license = QLineEdit("builtin:amiri"), QLineEdit()
        font_row = QHBoxLayout()
        font_row.addWidget(self.primary)
        choose = QPushButton("اختيار خط TTF/OTF")
        builtin = QPushButton("Amiri المرفق")
        choose.clicked.connect(self.choose_primary)
        builtin.clicked.connect(self.use_builtin)
        font_row.addWidget(choose)
        font_row.addWidget(builtin)
        form.addRow("الخط الأساسي:", font_row)
        license_row = QHBoxLayout()
        license_row.addWidget(self.license)
        choose_license = QPushButton("ملف الترخيص")
        choose_license.clicked.connect(self.choose_license)
        license_row.addWidget(choose_license)
        form.addRow("رخصة الخط المخصص:", license_row)
        self.rights = QCheckBox("أملك حق إعادة توزيع الخطوط المخصصة المضافة مع نصوص تراخيصها")
        form.addRow(self.rights)
        self.fallbacks = QListWidget()
        self.fallbacks.setMaximumHeight(75)
        form.addRow("خطوط fallback:", self.fallbacks)
        fallback_controls = QHBoxLayout()
        add, remove = QPushButton("إضافة fallback ورخصته"), QPushButton("إزالة المحدد")
        add.clicked.connect(self.add_fallback)
        remove.clicked.connect(lambda: self.fallbacks.takeItem(self.fallbacks.currentRow()))
        fallback_controls.addWidget(add)
        fallback_controls.addWidget(remove)
        form.addRow(fallback_controls)
        self.sizes = {}
        size_row = QHBoxLayout()
        for name, label in (
            ("dialogue", "الحوار"),
            ("names", "الأسماء"),
            ("choices", "الخيارات"),
            ("history", "History"),
            ("preferences", "Preferences"),
        ):
            size = QSpinBox()
            size.setRange(10, 128)
            self.sizes[name] = size
            size_row.addWidget(QLabel(label))
            size_row.addWidget(size)
        form.addRow("الأحجام:", size_row)
        self.direction = QComboBox()
        for label, value in (
            ("تلقائي مع تفضيل العربية", "auto"),
            ("RTL إلزامي", "rtl"),
            ("LTR", "ltr"),
        ):
            self.direction.addItem(label, value)
        form.addRow("اتجاه القراءة:", self.direction)
        self.align_interfaces = QCheckBox("محاذاة نصوص القوائم والسجل والتفضيلات وفق الاتجاه")
        form.addRow(self.align_interfaces)
        self.target = QLineEdit()
        self.target.setPlaceholderText("مثال 8.5.3 — اتركه فارغًا لاستخدام كشف اللعبة")
        form.addRow("إصدار مستهدف يدوي:", self.target)
        self.confirm_version = QCheckBox("تحققت من إصدار اللعبة؛ مسار SDK وحده ليس دليلًا عليه")
        form.addRow(self.confirm_version)
        layout.addLayout(form)
        self.sample = QPlainTextEdit(PREVIEW_SAMPLE)
        self.sample.setMaximumHeight(90)
        layout.addWidget(self.sample)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.preview.setMinimumHeight(100)
        layout.addWidget(self.preview)
        controls = QHBoxLayout()
        self.preview_button = QPushButton("فحص الخط والتوافق ومعاينة")
        self.save_button = QPushButton("حفظ إعدادات العربية")
        self.demo_button = QPushButton("إنشاء مشروع Ren’Py تجريبي")
        self.preview_button.clicked.connect(lambda: self.run("preview"))
        self.save_button.clicked.connect(lambda: self.run("save"))
        self.demo_button.clicked.connect(self.choose_demo)
        for button in (self.preview_button, self.save_button, self.demo_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        outer.addWidget(scroll)
        self.set_project(None)

    def set_project(self, project):
        self.project = project
        self.setEnabled(project is not None)
        settings = ArabicRuntimeService(project).load() if project else ArabicSettings()
        self.load_fields(settings)
        self.status.clear()
        self.preview.clear()

    def load_fields(self, settings):
        options = settings.runtime
        self.enabled.setChecked(options.enabled)
        self.primary.setText(options.primary_font.path)
        self.license.setText(options.primary_font.license_path)
        self.rights.setChecked(options.primary_font.redistribution_allowed)
        self.fallbacks.clear()
        for choice in options.fallback_fonts:
            self.add_choice(choice)
        for name, size in self.sizes.items():
            size.setValue(getattr(options.sizes, name))
        self.direction.setCurrentIndex(self.direction.findData(settings.layout_direction))
        self.align_interfaces.setChecked(options.align_interfaces)
        self.target.setText(options.target_version)
        self.confirm_version.setChecked(options.target_version_confirmed)

    def choices(self):
        return tuple(
            self.fallbacks.item(index)
            .data(Qt.ItemDataRole.UserRole)
            .model_copy(update={"redistribution_allowed": self.rights.isChecked()})
            for index in range(self.fallbacks.count())
        )

    def settings(self):
        return ArabicSettings(
            layout_direction=self.direction.currentData(),
            runtime=RuntimeOptions(
                enabled=self.enabled.isChecked(),
                primary_font=FontChoice(
                    path=self.primary.text().strip(),
                    license_path=self.license.text().strip(),
                    redistribution_allowed=self.rights.isChecked(),
                ),
                fallback_fonts=self.choices(),
                sizes=RuntimeSizes(**{name: size.value() for name, size in self.sizes.items()}),
                target_version=self.target.text().strip(),
                target_version_confirmed=self.confirm_version.isChecked(),
                align_interfaces=self.align_interfaces.isChecked(),
            ),
        )

    def choose_primary(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر خطًا", "", "Fonts (*.ttf *.otf)")
        if path:
            self.primary.setText(path)
            self.license.clear()
            self.rights.setChecked(False)

    def choose_license(self):
        path, _ = QFileDialog.getOpenFileName(self, "نص رخصة الخط", "", "Text (*.txt);;All (*)")
        if path:
            self.license.setText(path)

    def use_builtin(self):
        self.primary.setText("builtin:amiri")
        self.license.clear()

    def add_choice(self, choice):
        item = QListWidgetItem(choice.path)
        item.setData(Qt.ItemDataRole.UserRole, choice)
        item.setToolTip(choice.license_path)
        self.fallbacks.addItem(item)

    def add_fallback(self):
        if self.fallbacks.count() >= 4:
            return
        path, _ = QFileDialog.getOpenFileName(self, "خط fallback", "", "Fonts (*.ttf *.otf)")
        if path:
            license_path, _ = QFileDialog.getOpenFileName(self, "رخصة fallback", "", "Text (*.txt)")
            self.add_choice(FontChoice(path=path, license_path=license_path))

    def choose_demo(self):
        sdk = QFileDialog.getExistingDirectory(self, "اختر Ren’Py SDK للمشروع التجريبي")
        if sdk:
            self.run("demo", sdk=Path(sdk))

    def run(self, mode, *, sdk=None):
        if self.busy or not self.project:
            return
        try:
            settings = self.settings()
        except ValueError:
            self.status.setText("تحقق من صيغة الإصدار والأحجام ومسارات الخطوط.")
            return
        self.busy = True
        self.busy_changed.emit(True)
        for button in (self.preview_button, self.save_button, self.demo_button):
            button.setEnabled(False)
        service = ArabicRuntimeService(self.project)
        self.thread = QThread(self)

        def operation(_notify):
            if mode == "demo":
                return {"mode": mode, "path": service.create_demo(sdk, settings)}
            saved = service.save(settings) if mode == "save" else settings
            return {"mode": mode, "settings": saved, "assessment": service.assess(saved)}

        self.worker = TaskWorker(operation)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self.show_result)
        self.worker.failed.connect(
            lambda code: self.status.setText(
                "تعذر الفحص أو الحفظ: " + code + ". افحص الإصدار والتغطية والرخصة؛ "
                "يمكن حفظ التعطيل دون خط صالح."
            )
        )
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def show_result(self, result):
        if result["mode"] == "demo":
            self.status.setText(
                "المشروع التجريبي: "
                + str(result["path"])
                + "\nافتحه في SDK المطابق واتبع README_AR.txt؛ لم تُشغّل اللعبة الأصلية."
            )
            return
        assessment = result["assessment"]
        if result["mode"] == "save":
            self.load_fields(result["settings"])
            self.saved.emit()
        for font_id in self.font_ids:
            QFontDatabase.removeApplicationFont(font_id)
        self.font_ids = []
        families = []
        for info in sorted(assessment.fonts, key=lambda info: bool(info.missing_arabic)):
            font_id = QFontDatabase.addApplicationFont(info.path)
            if font_id >= 0:
                self.font_ids.append(font_id)
                families.extend(QFontDatabase.applicationFontFamilies(font_id))
        font = QFont()
        if families:
            font.setFamilies(families)
        font.setPixelSize(result["settings"].runtime.sizes.dialogue)
        self.preview.setFont(font)
        self.preview.setHtml(
            preview_html(self.sample.toPlainText(), direction=result["settings"].layout_direction)
        )
        self.status.setText(
            ("تم الحفظ. " if result["mode"] == "save" else "معاينة Qt. ")
            + f"Ren’Py: {assessment.profile.version or 'غير معروف'} / {assessment.profile.mode}\n"
            + "أخطاء: "
            + (", ".join(assessment.errors) or "لا توجد")
            + "\nتحذيرات: "
            + (", ".join(assessment.warnings) or "لا توجد")
        )

    def finish(self):
        self.busy = False
        self.worker = self.thread = None
        for button in (self.preview_button, self.save_button, self.demo_button):
            button.setEnabled(True)
        self.busy_changed.emit(False)
