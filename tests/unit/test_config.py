import pytest
from pydantic import ValidationError
from yaml import YAMLError

from rat.config.models import Settings, load_settings, save_settings
from rat.config.paths import default_workspace


def test_settings_yaml_roundtrip(tmp_path):
    path = tmp_path / "settings.yaml"
    settings = Settings.model_validate({"app": {"workspace_dir": str(tmp_path / "مساحات")}})
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert not path.with_suffix(".yaml.tmp").exists()
    assert settings.translation.provider == "mock"
    assert settings.quality.require_placeholder_match


@pytest.mark.parametrize(
    "data",
    [
        {"api_key": "synthetic-secret"},
        {"translation": {"api_key": "synthetic-secret"}},
        {"translation": {"provider": "nonexistent"}},
        {"translation": {"request_timeout_seconds": 0}},
        {"translation": {"preserve_approved_translations": False}},
        {"project": {"write_original_game": True}},
        {"project": {"allow_decompile": True}},
        {"quality": {"require_placeholder_match": False}},
        {"quality": {"block_export_on_critical_errors": False}},
    ],
)
def test_unsafe_or_unavailable_settings_are_rejected(data):
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


@pytest.mark.parametrize("content", ["[]", "null", "!!python/object/apply:builtins.print ['bad']"])
def test_yaml_is_a_safe_mapping(tmp_path, content):
    path = tmp_path / "settings.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, YAMLError)):
        load_settings(path)


def test_configuration_size_is_bounded(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("#" * 65537, encoding="utf-8")
    with pytest.raises(ValueError, match="64 KiB"):
        load_settings(path)


def test_missing_documents_requests_explicit_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr("rat.config.paths.user_documents_path", lambda: tmp_path / "missing")
    with pytest.raises(ValueError, match="--workspace"):
        default_workspace()
    assert not (tmp_path / "missing").exists()
