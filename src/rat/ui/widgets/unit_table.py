from PySide6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt

from rat.domain.models import TranslationUnit
from rat.domain.protection import UnitProtection

COLUMNS = (
    ("النص الأصلي", "source_text"),
    ("معرّف Ren'Py", "renpy_identifier"),
    ("المسار", "source_relpath"),
    ("السطر", "source_line"),
    ("النوع", "kind"),
    ("الشخصية", "speaker"),
    ("Label", "label"),
    ("الثقة", "confidence"),
    ("الحالة", "status"),
    ("حماية النص", "protection"),
)


class UnitTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.units: tuple[TranslationUnit, ...] = ()
        self.protection: dict[str, UnitProtection] = {}

    def set_units(
        self, units: tuple[TranslationUnit, ...], protection: tuple[UnitProtection, ...] = ()
    ) -> None:
        self.beginResetModel()
        self.units = units
        self.protection = {item.unit_id: item for item in protection}
        self.endResetModel()

    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.units)

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.units):
            return None
        unit = self.units[index.row()]
        if COLUMNS[index.column()][1] == "protection":
            result = self.protection.get(unit.unit_id)
            if role == Qt.ItemDataRole.DisplayRole:
                return "لم يُفحص" if result is None else "جاهز" if result.ready else "يحتاج مراجعة"
            if role == Qt.ItemDataRole.ToolTipRole and result:
                return "\n".join(issue.code for issue in result.result.issues) or "اجتاز فحص المصدر"
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return unit.source_literal or unit.source_text
        if role == Qt.ItemDataRole.DisplayRole:
            value = getattr(unit, COLUMNS[index.column()][1])
            return "—" if value is None else str(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return COLUMNS[section][0]
            return str(section + 1)
        return None


class UnitFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = ""
        self.confidence = ""
        self.setFilterKeyColumn(-1)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.invalidate()

    def set_confidence(self, confidence: str) -> None:
        self.confidence = confidence
        self.invalidate()

    def filterAcceptsRow(self, row, parent):
        unit = self.sourceModel().units[row]
        return (
            (not self.kind or unit.kind == self.kind)
            and (not self.confidence or unit.confidence == self.confidence)
            and super().filterAcceptsRow(row, parent)
        )
