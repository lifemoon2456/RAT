import platform

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout

from rat import __version__
from rat.config.paths import config_dir, log_dir


def about_text():
    return (
        f"Ren'Py Arabic Translator (RAT)\n{__version__} — Beta\n"
        f"Python {platform.python_version()}\n\n"
        "نسخة تجريبية؛ راجع الترجمة واختبرها على نسخة لعبة مستقلة.\n"
        "Mock محاكاة فقط. لم يُختبر حساب API حقيقي ضمن اختبارات الإصدار.\n"
        "المفاتيح في مخزن أسرار النظام. المشاريع مستقلة عن تثبيت التطبيق.\n"
        f"الإعدادات: {config_dir()}\nالسجلات: {log_dir()}\n\n"
        "تراخيص المكتبات والخطوط متاحة في قائمة مساعدة ← تراخيص المكتبات.\n"
        "لم تُحدد رخصة توزيع شيفرة RAT؛ راجع مالك المشروع قبل النشر العام."
    )


def show_about(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("حول RAT")
    dialog.resize(680, 420)
    layout = QVBoxLayout(dialog)
    text = QPlainTextEdit()
    text.setReadOnly(True)
    text.setPlainText(about_text())
    layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
