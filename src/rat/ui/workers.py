from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from rat.extraction.scanner import GameImportService
from rat.security.safe_paths import ScanError


class ImportWorker(QObject):
    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, project: Path, game: Path, sdk: Path | None, generate: bool):
        super().__init__()
        self.project = project
        self.game = game
        self.sdk = sdk
        self.generate = generate

    @Slot()
    def run(self) -> None:
        try:
            result = GameImportService().scan(
                self.project,
                self.game,
                sdk_dir=self.sdk,
                generate=self.generate,
                progress=self.progress.emit,
            )
            self.succeeded.emit(result)
        except ScanError as error:
            self.failed.emit(error.code)
        except Exception:
            self.failed.emit("import_failed")
        finally:
            self.finished.emit()
