import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

from rat import __version__

Event = Literal[
    "project_created",
    "project_opened",
    "operation_failed",
    "application_started",
    "unhandled_error",
]
EVENTS = {
    "project_created",
    "project_opened",
    "operation_failed",
    "application_started",
    "unhandled_error",
}
LOGGER = logging.getLogger("rat.lifecycle")
LOGGER.propagate = False


class SafeJsonFormatter(logging.Formatter):
    """Never format arbitrary messages, exception values, arguments or traceback locals."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "at": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "event": record.msg
                if isinstance(record.msg, str) and record.msg in EVENTS
                else "operation_failed",
                "version": __version__,
            }
        )


def log_unhandled_exception(_kind, _value, _traceback) -> None:
    log_event("unhandled_error")


def configure_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for handler in list(LOGGER.handlers):
        handler.close()
        LOGGER.removeHandler(handler)
    handler = RotatingFileHandler(
        directory / "application.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(SafeJsonFormatter())
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


def log_event(event: Event) -> None:
    # Allowlist only: no paths, game text, exception payloads, settings, or secrets.
    if event not in EVENTS:
        raise ValueError("Unknown lifecycle event.")
    LOGGER.info(event)
