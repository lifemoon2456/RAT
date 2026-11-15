from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rat import __version__
from rat.config.models import Settings, save_settings
from rat.config.paths import default_workspace
from rat.logging_setup import log_event
from rat.projects import ProjectService, ProjectSession
from rat.ui.about_dialog import show_about
from rat.ui.licenses_dialog import show_licenses
from rat.ui.pages.arabic_settings import ArabicSettingsPage
from rat.ui.pages.export import ExportPage
from rat.ui.pages.game_import import GameImportPage
from rat.ui.pages.packed_game import PackedGamePage
from rat.ui.pages.provider_settings import ProviderSettingsPage
from rat.ui.pages.review import ReviewPage
from rat.ui.pages.translation import TranslationPage


class MainWindow(QMainWindow):
    def __init__(self, service: ProjectService, settings: Settings, *, settings_path=None):
        super().__init__()
        self.service = service
        self.settings = settings
        self.settings_path = settings_path
        self.session: ProjectSession | None = None
        self.setWindowTitle(f"Ren'Py Arabic Translator (RAT) {__version__} Beta")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1240, 780)
        help_menu = self.menuBar().addMenu("مساعدة")
        help_menu.addAction("حول البرنامج / About").triggered.connect(lambda: show_about(self))
        licenses_action = help_menu.addAction("تراخيص المكتبات")
        licenses_action.triggered.connect(lambda: show_licenses(self))

        panel = QWidget()
        layout = QVBoxLayout(panel)
        heading = QLabel("مترجم Ren'Py إلى العربية")
        heading.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(heading)
        notice = QLabel(
            f"RAT {__version__} — نسخة Beta للاختبار والمراجعة.\n"
            "التصدير لا يغيّر اللعبة الأصلية؛ اختبر الحزمة على نسخة منفصلة."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        controls = QHBoxLayout()
        self.create_button = QPushButton("إنشاء مشروع")
        self.open_button = QPushButton("فتح مشروع")
        self.close_button = QPushButton("إغلاق المشروع")
        self.close_button.setEnabled(False)
        for button in (self.create_button, self.open_button, self.close_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.project_label = QLabel("لا يوجد مشروع مفتوح")
        self.project_label.setTextFormat(Qt.TextFormat.PlainText)
        self.project_label.setWordWrap(True)
        self.project_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.project_label)
        self.import_page = GameImportPage(self)
        self.packed_page = PackedGamePage(self)
        self.provider_page = ProviderSettingsPage(self)
        self.translation_page = TranslationPage(self)
        self.review_page = ReviewPage(self)
        self.arabic_page = ArabicSettingsPage(self)
        self.export_page = ExportPage(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.import_page, "اللعبة والنصوص")
        self.tabs.addTab(self.packed_page, "الألعاب المجمعة / Packed")
        self.tabs.addTab(self.provider_page, "إعداد المزودين")
        self.tabs.addTab(self.translation_page, "الترجمة والتقدم")
        self.tabs.addTab(self.review_page, "المحرر والمراجعة / QA")
        self.tabs.addTab(self.arabic_page, "العربية والخطوط / Runtime")
        self.tabs.addTab(self.export_page, "التصدير والنسخ الاحتياطي")
        self.import_page.busy_changed.connect(lambda busy: self.set_busy(busy, "import"))
        self.packed_page.busy_changed.connect(lambda busy: self.set_busy(busy, "packed"))
        self.provider_page.busy_changed.connect(lambda busy: self.set_busy(busy, "provider"))
        self.translation_page.busy_changed.connect(lambda busy: self.set_busy(busy, "translation"))
        self.review_page.busy_changed.connect(lambda busy: self.set_busy(busy, "review"))
        self.arabic_page.busy_changed.connect(lambda busy: self.set_busy(busy, "arabic"))
        self.export_page.busy_changed.connect(lambda busy: self.set_busy(busy, "export"))
        self.provider_page.saved.connect(self.translation_page.refresh)
        self.provider_page.saved.connect(lambda: setattr(self.review_page, "dirty", True))
        self.import_page.data_changed.connect(lambda: setattr(self.review_page, "dirty", True))
        self.translation_page.data_changed.connect(self.reload_import)
        self.packed_page.data_changed.connect(self.reload_import)
        self.review_page.data_changed.connect(self.review_changed)
        self.tabs.currentChanged.connect(self.tab_changed)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(panel)
        self.create_button.clicked.connect(self.choose_new_project)
        self.open_button.clicked.connect(self.choose_existing_project)
        self.close_button.clicked.connect(self.close_project)
        self.statusBar().showMessage("جاهز — لا توجد اتصالات بخدمات ترجمة")

    def choose_new_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "مشروع جديد", "اسم المشروع:")
        if not accepted:
            return
        try:
            initial = self.settings.app.workspace_dir or default_workspace()
        except ValueError:
            initial = Path.home()
        workspace = QFileDialog.getExistingDirectory(
            self,
            "اختر مجلد مساحات العمل",
            str(initial),
        )
        if workspace:
            if self.create_project(name, Path(workspace)) and self.settings_path:
                updated = self.settings.model_copy(
                    update={
                        "app": self.settings.app.model_copy(
                            update={"workspace_dir": Path(workspace)}
                        )
                    }
                )
                try:
                    save_settings(updated, self.settings_path)
                    self.settings = updated
                except OSError:
                    self.statusBar().showMessage("تم إنشاء المشروع؛ تعذر حفظ مسار العمل الافتراضي.")

    def choose_existing_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "اختر مجلد مشروع RAT")
        if path:
            self.open_project(Path(path))

    def create_project(self, name: str, workspace: Path) -> bool:
        try:
            session = self.service.create(name, workspace=workspace, settings=self.settings)
        except Exception:
            self.show_failure()
            return False
        return self.set_session(session)

    def open_project(self, path: Path) -> bool:
        try:
            session = self.service.open(path)
        except Exception:
            self.show_failure()
            return False
        return self.set_session(session)

    def set_session(self, session: ProjectSession) -> bool:
        if not self.close_project():
            session.close()
            return False
        self.session = session
        self.close_button.setEnabled(True)
        self.project_label.setText(f"المشروع: {session.project.name}\nالمجلد: {session.path}")
        self.import_page.set_project(session.path)
        self.packed_page.set_project(session.path)
        self.provider_page.set_project(session.path)
        self.translation_page.set_project(session.path)
        self.review_page.set_project(session.path)
        self.arabic_page.set_project(session.path)
        self.export_page.set_project(session.path)
        self.tab_changed(self.tabs.currentIndex())
        self.statusBar().showMessage("مشروع مفتوح — الحفظ في مساحة العمل المستقلة")
        return True

    def show_failure(self) -> None:
        log_event("operation_failed")
        self.statusBar().showMessage(
            "تعذرت العملية؛ تحقق من المسار والصلاحيات وصحة إعدادات المشروع."
        )

    def close_project(self) -> bool:
        if any(page.busy for page in self.pages()) or not self.review_page.save_current():
            self.statusBar().showMessage("انتظر انتهاء العملية وحفظ المسودة قبل إغلاق المشروع.")
            return False
        if self.session is not None:
            self.session.close()
            self.session = None
        self.project_label.setText("لا يوجد مشروع مفتوح")
        self.close_button.setEnabled(False)
        self.import_page.set_project(None)
        self.packed_page.set_project(None)
        self.provider_page.set_project(None)
        self.translation_page.set_project(None)
        self.review_page.set_project(None)
        self.arabic_page.set_project(None)
        self.export_page.set_project(None)
        self.statusBar().showMessage("جاهز")
        return True

    def pages(self):
        return (
            self.import_page,
            self.packed_page,
            self.provider_page,
            self.translation_page,
            self.review_page,
            self.arabic_page,
            self.export_page,
        )

    def set_busy(self, busy: bool, source="import") -> None:
        self.create_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.close_button.setEnabled(not busy and self.session is not None)
        for name, page in (
            ("import", self.import_page),
            ("packed", self.packed_page),
            ("provider", self.provider_page),
            ("translation", self.translation_page),
            ("review", self.review_page),
            ("arabic", self.arabic_page),
            ("export", self.export_page),
        ):
            if name != source:
                page.setEnabled(not busy and self.session is not None)
        if not busy and source != "review" and self.tabs.currentWidget() is self.review_page:
            self.review_page.activate()

    def reload_import(self):
        if self.session:
            self.import_page.set_project(self.session.path)
            self.review_page.dirty = True

    def review_changed(self):
        if self.session:
            self.import_page.set_project(self.session.path)

    def tab_changed(self, index):
        if not self.review_page.save_current():
            self.tabs.blockSignals(True)
            self.tabs.setCurrentWidget(self.review_page)
            self.tabs.blockSignals(False)
            return
        if self.tabs.widget(index) is self.review_page:
            self.review_page.activate()
        if self.tabs.widget(index) is self.packed_page:
            if not self.packed_page.game_path.text():
                self.packed_page.game_path.setText(self.import_page.game_path.text())
            self.packed_page.activate()

    def closeEvent(self, event: QCloseEvent) -> None:
        if any(page.busy for page in self.pages()):
            if self.translation_page.control and self.translation_page.busy:
                self.translation_page.control.pause()
            if self.review_page.control and self.review_page.busy:
                self.review_page.control.stop()
            self.statusBar().showMessage(
                "جارٍ حفظ العمل الجاري؛ انتظر انتهاء الطلبات ثم أغلق النافذة مجددًا."
            )
            event.ignore()
            return
        if not self.close_project():
            event.ignore()
            return
        super().closeEvent(event)
