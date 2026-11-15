import json
import shutil
from pathlib import Path

import pytest

from rat.arabic.fonts import FontManager
from rat.arabic.runtime import ArabicRuntimeService
from rat.arabic.style_generator import RUNTIME_PATH
from rat.config.models import ArabicSettings
from rat.domain.arabic import FontChoice, RuntimeOptions
from rat.exporters.backup import BackupManager
from rat.exporters.manager import ExportManager
from rat.extraction.renpy_sdk import run_sdk, sdk_command
from rat.extraction.scanner import GameImportService
from rat.review import ReviewService


def import_game(project, tmp_path):
    game = tmp_path / "original-game"
    shutil.copytree(Path(__file__).parents[1] / "fixtures/game_with_tl", game)
    # Evidence belongs to this authored copy, never inferred from the SDK path.
    (game / "renpy").mkdir()
    (game / "renpy/vc_version.py").write_text("version = '8.5.3.26051504'\n")
    report = GameImportService().scan(project.path, game)
    return game, report


def configured():
    return ArabicSettings(runtime=RuntimeOptions(enabled=True))


def test_runtime_settings_import_managed_fonts_reopen_export_and_disable(project, tmp_path):
    game, _report = import_game(project, tmp_path)
    before = {
        path.relative_to(game): path.read_bytes() for path in game.rglob("*") if path.is_file()
    }
    service = ArabicRuntimeService(project.path)
    saved = service.save(configured())
    assert saved.runtime.primary_font.path.startswith("runtime/fonts/")
    assert service.load() == saved
    backup = BackupManager(project.path)
    manifest = backup.verify(backup.create())
    assert saved.runtime.primary_font.path in manifest["files"]
    review = ReviewService(project.path)
    for row in review.list_units():
        review.save(row.unit_id, row.source.source_text.replace("Hello", "مرحبًا"))
    review.action([row.unit_id for row in review.list_units()], "approve")
    exported = ExportManager(project.path).export()
    assert exported.status == "completed" and RUNTIME_PATH in exported.created_files
    manifest = json.loads((Path(exported.destination) / "manifest.json").read_text())
    assert manifest["arabic_runtime"]["enabled"]
    assert any(path.endswith(".license.txt") for path in exported.created_files)
    off = saved.model_copy(update={"runtime": saved.runtime.model_copy(update={"enabled": False})})
    service.save(off)
    disabled = ExportManager(project.path).export()
    assert disabled.status == "completed" and RUNTIME_PATH not in disabled.created_files
    assert {
        path.relative_to(game): path.read_bytes() for path in game.rglob("*") if path.is_file()
    } == before


def test_unknown_version_is_not_inferred_from_an_extraction_sdk(project):
    GameImportService().scan(project.path, Path(__file__).parents[1] / "fixtures/game_with_tl")
    service = ArabicRuntimeService(project.path)
    assessment = service.assess(configured())
    assert not assessment.valid and assessment.profile.mode == "unknown"
    with pytest.raises(ValueError, match="settings_invalid"):
        service.save(configured())
    assert not service.load().runtime.enabled


def test_invalid_font_blocks_enabled_runtime_but_can_always_disable(project, tmp_path):
    import_game(project, tmp_path)
    service = ArabicRuntimeService(project.path)
    invalid = configured().model_copy(
        update={
            "runtime": RuntimeOptions(
                enabled=True, primary_font=FontChoice(path=str(tmp_path / "missing.ttf"))
            )
        }
    )
    assert "font_file_or_license_invalid" in service.assess(invalid).errors
    with pytest.raises(ValueError):
        service.save(invalid)
    service.save(
        invalid.model_copy(
            update={"runtime": invalid.runtime.model_copy(update={"enabled": False})}
        )
    )
    assert not service.load().runtime.enabled


def test_custom_font_requires_explicit_redistribution_permission(project, tmp_path):
    import_game(project, tmp_path)
    service = ArabicRuntimeService(project.path)
    primary = FontChoice(
        path=str(FontManager.builtin_path()),
        license_path=str(FontManager.builtin_path().with_name("OFL.txt")),
    )
    options = RuntimeOptions(enabled=True, primary_font=primary)
    assert not service.assess(ArabicSettings(runtime=options)).valid
    allowed = options.model_copy(
        update={"primary_font": primary.model_copy(update={"redistribution_allowed": True})}
    )
    assert service.assess(ArabicSettings(runtime=allowed)).valid


def test_export_fails_before_emitting_translations_when_runtime_font_is_missing(project, tmp_path):
    import_game(project, tmp_path)
    service = ArabicRuntimeService(project.path)
    saved = service.save(configured())
    review = ReviewService(project.path)
    row = review.list_units()[0]
    review.save(row.unit_id, row.source.source_text)
    review.action([row.unit_id], "approve")
    (project.path / saved.runtime.primary_font.path).unlink()
    result = ExportManager(project.path).export()
    assert result.status == "failed" and not result.exported
    assert RUNTIME_PATH not in result.created_files


def test_font_checks_ignore_code_inside_tags_and_placeholders_but_block_missing_visible_glyphs(
    project, tmp_path
):
    _game, report = import_game(project, tmp_path)
    service = ArabicRuntimeService(project.path)
    files, metadata = service.bundle(configured(), imported=report, texts=["مرحبًا [имя] {b}نص{/b}"])
    assert RUNTIME_PATH in files and metadata["logical_unicode_preserved"]
    with pytest.raises(ValueError, match="missing_font_glyphs"):
        service.bundle(configured(), imported=report, texts=["你好"])


def test_real_sdk_demo_lint_native_render_and_disable_restore(project, renpy_sdk, monkeypatch):
    service = ArabicRuntimeService(project.path)
    demo = service.create_demo(renpy_sdk)
    command = sdk_command(renpy_sdk)
    run_sdk(command + [str(demo), "compile"], demo)
    lint = run_sdk(command + [str(demo), "lint"], demo)
    assert "errors" not in lint.lower(), lint
    monkeypatch.setenv("RAT_RUNTIME_AUTOTEST", "1")
    monkeypatch.setenv("RENPY_SKIP_MAIN_MENU", "1")
    run_sdk(command + [str(demo), "run"], demo, timeout=60)
    result = json.loads((demo / "runtime-result.json").read_text())
    assert result["status"] == "passed" and result["styles_restored"]
    assert result["mixed_text_preserved"] and not result["disabled"]
    assert (demo / "arabic-native.png").stat().st_size > 10000
    (demo / "game/tl/arabic/rat_runtime.disabled").write_text("", encoding="utf-8")
    monkeypatch.setenv("RAT_RUNTIME_EXPECT_DISABLED", "1")
    run_sdk(command + [str(demo), "run"], demo, timeout=60)
    assert json.loads((demo / "runtime-result.json").read_text())["disabled"]
