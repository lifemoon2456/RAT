import asyncio
import inspect

from PySide6.QtCore import QObject, Signal

from rat.providers.base import ProviderError
from rat.security.secrets import SecretStoreError


class TaskWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()
    progress = Signal(object)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            result = self.operation(self.progress.emit)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            self.succeeded.emit(result)
        except ProviderError as error:
            self.failed.emit(error.code)
        except SecretStoreError:
            self.failed.emit("secure_storage_unavailable")
        except ValueError as error:
            safe_codes = {
                "unit_locked",
                "qa_blocks_approval",
                "reject_approved_before_editing",
                "review_changed_reload_first",
                "source_not_active",
                "select_unique_units",
                "selection_contains_locked_or_skipped_units",
                "alternative_source_changed",
                "alternative_not_found",
                "alternative_count_limit",
            }
            code = str(error)
            self.failed.emit(code if code in safe_codes else "operation_failed")
        except Exception:
            self.failed.emit("operation_failed")
        finally:
            self.finished.emit()
