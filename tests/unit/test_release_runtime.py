import json
import logging
import tomllib
from pathlib import Path

import pytest

from rat import __version__
from rat.config.paths import config_dir, log_dir
from rat.logging_setup import SafeJsonFormatter, log_event


def test_structured_log_discards_secrets_in_message_args_and_exception():
    secret = "SYNTHETIC_AUTHORIZATION_BEARER_SECRET"
    record = logging.LogRecord(
        "rat", logging.ERROR, secret, 1, "%s", (secret,), (ValueError, ValueError(secret), None)
    )
    text = SafeJsonFormatter().format(record)
    assert secret not in text
    assert json.loads(text)["event"] == "operation_failed"
    with pytest.raises(ValueError):
        log_event(secret)


def test_default_runtime_paths_are_independent_of_current_directory(tmp_path, monkeypatch):
    before = config_dir(), log_dir()
    monkeypatch.chdir(tmp_path)
    assert (config_dir(), log_dir()) == before
    assert not config_dir().is_relative_to(tmp_path)


def test_application_and_distribution_versions_match():
    project = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["version"] == __version__
    assert "b" in __version__
