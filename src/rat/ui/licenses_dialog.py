from importlib.resources import files

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout, QWidget


def read_notices() -> str:
    try:
        return (
            files("rat").joinpath("resources/THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return "تتوفر إشعارات تراخيص المكتبات داخل نسخة EXE المجمعة."


def show_licenses(parent: QWidget) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("تراخيص المكتبات")
    dialog.resize(760, 520)
    layout = QVBoxLayout(dialog)
    text = QPlainTextEdit()
    text.setReadOnly(True)
    text.setPlainText(read_notices())
    layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
