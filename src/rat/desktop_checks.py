"""Explicit packaging diagnostic. Never runs during a normal desktop launch."""

import asyncio
import hashlib
import json
import os
import pickle
import sys
import zlib
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from rat import __version__
from rat.arabic.fonts import FontManager
from rat.arabic.runtime import ArabicRuntimeService
from rat.config.models import ArabicSettings, Settings
from rat.diagnostics import diagnostic_report
from rat.domain.arabic import RuntimeOptions
from rat.domain.packed import PackedOptions
from rat.domain.translation import ProviderConfig, TranslationOptions
from rat.exporters.backup import BackupManager
from rat.exporters.installation import InstallationService
from rat.exporters.manager import ExportManager
from rat.extraction.scanner import GameImportService
from rat.projects import ProjectService
from rat.protection import MaskingEngine, RestorationEngine
from rat.providers.registry import get_provider
from rat.review import ReviewService
from rat.translation.orchestrator import TranslationManager
from rat.ui.licenses_dialog import read_notices
from rat.ui.main_window import MainWindow


def check_packed_distribution(directory: Path, sdk: str | None, version: str | None):
    """Only authored synthetic data is compiled; recovered game code is never run."""
    from rat.extraction.packed_manager import PackedGameService
    from rat.extraction.renpy_sdk import run_sdk, sdk_command

    root = directory / f"packed-fixture-{uuid4().hex}"
    (root / "game").mkdir(parents=True)
    files = {"script.rpy": b'label start:\n    "Packed [name]"\n    return\n'}
    if sdk:
        authored = directory / f"authored-compile-{uuid4().hex}"
        (authored / "game").mkdir(parents=True)
        (authored / "game/script.rpy").write_bytes(files["script.rpy"])
        run_sdk([*sdk_command(Path(sdk)), str(authored), "compile"], authored)
        files = {"script.rpyc": (authored / "game/script.rpyc").read_bytes()}
    files["nested/extra.rpy"] = b'label extra:\n    "Another synthetic example"\n    return\n'
    for index, (name, payload) in enumerate(files.items()):
        header_size = 34
        offset = header_size + len(payload)
        key = 0x12345678
        table = {name: [(header_size ^ key, len(payload) ^ key, b"")]}
        archive = root / f"game/fixture-{index}.rpa"
        archive.write_bytes(
            f"RPA-3.0 {offset:016x} {key:08x}\n".encode("ascii")
            + payload
            + zlib.compress(pickle.dumps(table, protocol=2))
        )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "game").iterdir()
    }
    with ProjectService().create("Packed diagnostic", workspace=directory / "projects") as session:
        service = PackedGameService(session.path)
        report = service.extract(
            root,
            PackedOptions(
                decompile=bool(sdk),
                engine_version=version or "",
                engine_version_confirmed=bool(sdk),
            ),
        )
        assert report.rpa_count == 2 and report.imported_count == 2 and report.status == "ready"
        if sdk:
            assert report.rpyc_count == 1 and any(
                item.status == "decompiled" for item in report.files
            )
            assert any(
                unit.renpy_identifier for unit in GameImportService().load(session.path).units
            )
        service.clean(report.run_id)
        assert not (session.path / report.workspace_relpath).exists()
        assert len(GameImportService().load(session.path).units) == 2
    assert hashes == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "game").iterdir()
    }
    return {
        "packed_extraction_verified": True,
        "packed_cleanup_verified": True,
        "rpyc_decompiler_verified": bool(sdk),
    }


def run_desktop_check(directory: Path) -> int:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = MainWindow(ProjectService(), Settings())
    window.show()
    result = {
        "status": "failed",
        "frozen": bool(getattr(sys, "frozen", False)),
        "application_version": __version__,
    }

    def check() -> None:
        try:
            assert window.isVisible()
            assert window.create_project("اختبار النسخة المستقلة", directory / "projects")
            path = window.session.path
            identity = window.session.project
            window.close_project()
            sample_root = directory / f"sample-game-{uuid4().hex}"
            sample_game = sample_root / "game"
            sample_game.mkdir(parents=True, exist_ok=False)
            sample = sample_game / "script.rpy"
            content = (
                'label start:\n    "Portable [name]"\n'
                '    menu:\n        "Continue":\n            return\n'
            )
            sample.write_text(content, encoding="utf-8")
            sdk = os.environ.get("RAT_RENPY_SDK")
            discovery = GameImportService().scan(
                path, sample_root, sdk_dir=Path(sdk) if sdk else None, generate=bool(sdk)
            )
            sample_units = [
                unit for unit in discovery.units if unit.source_relpath == "game/script.rpy"
            ]
            assert len(sample_units) == 2
            assert len(discovery.protection) == len(discovery.units)
            assert sample.read_text(encoding="utf-8") == content
            assert GameImportService().load(path).units == discovery.units
            window.import_page.show_report(discovery)
            assert window.import_page.model.rowCount() == len(discovery.units)
            if sdk:
                assert any(unit.renpy_identifier for unit in sample_units)
            result.update(
                discovery_verified=True,
                sdk_version=discovery.sdk_version,
                sdk_template_verified=bool(sdk),
                extracted_count=len(discovery.units),
            )
            assert window.open_project(path)
            assert window.session.project == identity
            window.close_project()
            protected = MaskingEngine().mask("Hello [name] {b}test{/b}")
            assert protected.valid and protected.protected is not None
            results = asyncio.run(
                get_provider("mock").translate_batch(
                    [{"unit_id": "packaging_sample", "text": protected.protected.masked_text}],
                    source_language="en",
                    target_language="ar",
                    context={},
                    settings={},
                )
            )
            restored = RestorationEngine().restore(
                protected.protected, results[0]["translation_text"]
            )
            assert restored.valid and restored.text == "Hello [name] {b}test{/b}"
            rejected = RestorationEngine().restore(protected.protected, "missing protected fields")
            assert not rejected.valid and rejected.text is None
            assert results[0]["simulated"]
            with ProjectService().create(
                "Translation diagnostic", workspace=directory / "projects"
            ) as translation_project:
                GameImportService().scan(translation_project.path, sample_root)
                manager = TranslationManager(translation_project.path)
                job_id = manager.create_job(
                    ProviderConfig(), TranslationOptions(requests_per_minute=100000)
                )
                progress = asyncio.run(manager.run(job_id))
                assert (
                    progress.simulated == 2 and progress.translated == 0 and progress.remaining == 0
                )
                assert asyncio.run(manager.run(job_id)).simulated == 2
            result["translation_manager_verified"] = True
            review = ReviewService(path)
            for unit in sample_units:
                review.save(unit.unit_id, unit.source_text.replace("Portable", "محمول"))
            review.action([unit.unit_id for unit in sample_units], "approve")
            assert all(row.qa.valid for row in review.list_units() if row.state == "approved")
            result["review_qa_verified"] = True
            backup = BackupManager(path)
            checkpoint = backup.create()
            assert backup.verify(checkpoint)["kind"] == "rat_project_only"
            restored_project = backup.restore(checkpoint, directory / f"restored-{uuid4().hex}")
            assert ReviewService(restored_project).list_units() == review.list_units()
            result["backup_verified"] = True
            result["restore_verified"] = True
            assert diagnostic_report(path)["project"]["units"] == len(discovery.units)
            result["diagnostics_verified"] = True
            font_manager = FontManager()
            font = font_manager.inspect(font_manager.builtin_path())
            assert not font.missing_arabic and font.shaping_tables
            result["arabic_font_verified"] = True
            if sdk:
                ArabicRuntimeService(path).save(
                    ArabicSettings(
                        runtime=RuntimeOptions(
                            enabled=True,
                            target_version=discovery.sdk_version,
                            target_version_confirmed=True,
                        )
                    )
                )
                exported = ExportManager(path).export()
                assert exported.status == "completed" and len(exported.exported) == 2
                assert "game/tl/arabic/arabic_runtime.rpy" in exported.created_files
                demo = ArabicRuntimeService(path).create_demo(Path(sdk))
                assert (demo / "game/script.rpy").is_file()
                result["arabic_runtime_bundle_verified"] = True
                assert sample.read_text(encoding="utf-8") == content
                result["export_verified"] = True
                installation = InstallationService(path).install_copy(
                    exported.export_id, directory / f"installed-{uuid4().hex}"
                )
                restored_copy = InstallationService.restore_copy(installation)
                assert (restored_copy / "game/script.rpy").read_text(encoding="utf-8") == content
                result["install_restore_verified"] = True
            if result["frozen"]:

                async def sdk_checks():
                    from rat.providers.gemini import GeminiProvider
                    from rat.providers.google_translate import GoogleTranslateProvider
                    from rat.providers.openai import OpenAIProvider

                    for adapter in (GeminiProvider, OpenAIProvider):
                        client = adapter(
                            ProviderConfig(
                                provider_id=adapter.provider_id, model="diagnostic-no-request"
                            ),
                            "RAT_SYNTHETIC_DIAGNOSTIC_KEY",
                        )
                        await client.aclose()
                    google = GoogleTranslateProvider(
                        ProviderConfig(provider_id="google_translate", timeout_seconds=60)
                    )
                    assert (
                        await google.translate_batch(
                            [], source_language="en", target_language="ar", context={}, settings={}
                        )
                        == []
                    )

                asyncio.run(sdk_checks())
                from rat.security.secrets import SecretStore

                result["secure_backend"] = type(SecretStore()._backend()).__name__
                result["sdk_clients_initialized_without_api_calls"] = True
                result["google_worker_verified_without_api_calls"] = True
            result.update(check_packed_distribution(directory, sdk, discovery.sdk_version))
            notices = read_notices()
            if result["frozen"]:
                assert "PySide6" in notices and "Python" in notices
                assert "deep-translator" in notices and "Nidhal" in notices
            result.update(
                status="passed",
                window_opened=True,
                project_reopened=True,
                mock_verified=True,
                protection_verified=True,
                bundled_notices=bool(result["frozen"]),
            )
        except Exception as error:
            # Record a category only; exception payloads may contain paths/input.
            result["error_type"] = type(error).__name__
            if hasattr(error, "code"):
                result["error_code"] = error.code
        finally:
            window.close()
            (directory / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            application.exit(0 if result["status"] == "passed" else 1)

    QTimer.singleShot(0, check)
    return application.exec()
