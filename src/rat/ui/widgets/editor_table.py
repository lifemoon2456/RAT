from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt, Signal

from rat.database.review_repository import ReviewRepository
from rat.domain.review import ReviewStatus

STATUS_LABELS = {
    "untranslated": "Untranslated — غير مترجم",
    "translated": "Translated — مترجم",
    "needs_review": "Needs Review — يحتاج مراجعة",
    "approved": "Approved — معتمد",
    "error": "Error — خطأ",
    "locked": "Locked — مقفل",
}
COLUMNS = ("النص الأصلي", "الترجمة", "الشخصية", "الملف", "الحالة", "المزود", "QA", "الطول التقريبي")


class EditorTableModel(QAbstractTableModel):
    saved = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = ()
        self.service = None

    def set_records(self, records):
        self.beginResetModel()
        self.records = tuple(records)
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.records)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.records):
            return None
        record = self.records[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(issue.code for issue in record.qa.issues) if record.qa else ""
        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole}:
            values = (
                record.source.source_text,
                record.translation_text or "",
                record.source.speaker or "—",
                record.source.source_relpath,
                STATUS_LABELS[record.status.value] + (" · Skip" if record.skipped else ""),
                record.provider_id or "—",
                ", ".join(issue.code for issue in record.qa.issues) if record.qa else "",
                record.qa.overflow_risk if record.qa else "—",
            )
            return values[index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                COLUMNS[section] if orientation == Qt.Orientation.Horizontal else str(section + 1)
            )
        return None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 1:
            record = self.records[index.row()]
            if not record.locked and record.state != ReviewStatus.APPROVED:
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (
            role != Qt.ItemDataRole.EditRole
            or not index.isValid()
            or index.column() != 1
            or self.service is None
        ):
            return False
        record = self.records[index.row()]
        if record.locked or record.state == ReviewStatus.APPROVED:
            return False
        try:
            records = self.service.save(
                record.unit_id, str(value), expected_etag=ReviewRepository.etag(record)
            )
        except Exception:
            self.failed.emit(
                "تعذر الحفظ؛ ربما تغير السطر أو أصبح معتمدًا/مقفلًا. حدّث القائمة قبل إعادة المحاولة."
            )
            return False
        self.records = records
        self.dataChanged.emit(
            self.index(0, 0), self.index(max(0, len(records) - 1), len(COLUMNS) - 1)
        )
        self.saved.emit(records)
        return True


class EditorFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = self.speaker = self.file = self.status = self.provider = ""

    def update_filter(self, *, query="", speaker="", file="", status="", provider=""):
        self.query, self.speaker, self.file = query.casefold(), speaker.casefold(), file.casefold()
        self.status, self.provider = status, provider
        self.invalidate()

    def filterAcceptsRow(self, row, parent):
        record = self.sourceModel().records[row]
        text = (record.source.source_text + "\n" + (record.translation_text or "")).casefold()
        return (
            self.query in text
            and self.speaker in (record.source.speaker or "").casefold()
            and self.file in record.source.source_relpath.casefold()
            and (not self.status or record.status.value == self.status)
            and (not self.provider or record.provider_id == self.provider)
        )
