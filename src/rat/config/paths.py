from pathlib import Path

from platformdirs import user_config_path, user_documents_path, user_log_path

APP_NAME = "RenPyArabicTranslator"


def config_dir() -> Path:
    return user_config_path(APP_NAME, appauthor=False, roaming=False)


def log_dir() -> Path:
    return user_log_path(APP_NAME, appauthor=False)


def default_workspace() -> Path:
    # No mkdir here: a missing Documents directory requires an explicit alternative.
    documents = user_documents_path()
    if not documents.is_dir():
        raise ValueError("Documents is unavailable; choose --workspace explicitly.")
    return documents / APP_NAME / "projects"
