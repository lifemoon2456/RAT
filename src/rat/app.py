import argparse
import sys
from pathlib import Path

from rat.config.models import load_settings, save_settings
from rat.config.paths import config_dir, log_dir
from rat.logging_setup import configure_logging, log_event, log_unhandled_exception
from rat.projects import ProjectService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RAT desktop application — discovery and templates"
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--log-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        configure_logging(args.log_dir if args.log_dir is not None else log_dir())
        path = args.config or config_dir() / "settings.yaml"
        settings = load_settings(path if args.config or path.is_file() else None)
        if not path.exists():
            save_settings(settings, path)
    except Exception:
        if sys.stderr is not None:
            print("RAT: could not load settings or initialize logging.", file=sys.stderr)
        return 2

    from PySide6.QtWidgets import QApplication

    from rat.ui.main_window import MainWindow

    application = QApplication.instance() or QApplication([sys.argv[0]])
    application.setApplicationName("RenPyArabicTranslator")
    application.setOrganizationName("RAT")
    sys.excepthook = log_unhandled_exception
    window = MainWindow(ProjectService(), settings, settings_path=path)
    window.show()
    log_event("application_started")
    return application.exec()
