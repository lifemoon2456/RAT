import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from yaml import YAMLError

from rat import __version__
from rat.arabic.runtime import ArabicRuntimeService
from rat.config.models import ArabicSettings, load_settings, read_yaml, save_settings
from rat.config.paths import log_dir
from rat.diagnostics import write_diagnostics
from rat.discovery.inventory import inventory_game
from rat.domain.packed import PackedOptions
from rat.domain.translation import ProviderConfig
from rat.exporters.backup import BackupManager
from rat.exporters.installation import InstallationService
from rat.exporters.manager import ExportManager
from rat.extraction.packed_manager import PackedGameService
from rat.extraction.scanner import GameImportService
from rat.logging_setup import configure_logging, log_event
from rat.projects import ProjectService, ProjectSession
from rat.protection import MaskingEngine, RestorationEngine
from rat.providers.base import ProviderError
from rat.providers.registry import get_provider
from rat.providers.settings_service import ProviderSettingsService
from rat.review import ReviewService
from rat.translation.orchestrator import TranslationManager


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="RAT: projects, discovery and offline mock demo")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--log-dir", type=Path, default=None)
    commands = root.add_subparsers(dest="command", required=True)
    project = commands.add_parser("project", help="Create or reopen an empty RAT workspace")
    projects = project.add_subparsers(dest="project_command", required=True)
    create = projects.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--workspace", type=Path)
    create.add_argument("--config", type=Path)
    info = projects.add_parser("info")
    info.add_argument("--project", type=Path, required=True)
    config = commands.add_parser("config-init", help="Write non-secret default YAML settings")
    config.add_argument("--output", type=Path, required=True)
    commands.add_parser("mock-demo", help="Echo built-in synthetic samples; no game input")
    scan = commands.add_parser(
        "scan", help="Inventory a game or import its texts into a RAT project"
    )
    scan.add_argument("--game", type=Path, required=True)
    scan.add_argument("--project", type=Path)
    scan.add_argument("--sdk", type=Path)
    scan.add_argument("--generate-templates", action="store_true")
    protection = commands.add_parser(
        "protect", help="Preview protection of saved extracted units; no API or source writes"
    )
    protection.add_argument("--project", type=Path, required=True)
    translate = commands.add_parser(
        "translate", help="Translate missing saved units or resume a checkpoint"
    )
    translate.add_argument("--project", type=Path, required=True)
    translate.add_argument("--profile", help="Saved profile ID; default is offline mock")
    translate.add_argument("--job", help="Resume this saved job with its original profile/options")
    translate.add_argument("--retry-failed", action="store_true")
    profiles = commands.add_parser("providers", help="List public profiles without credentials")
    profiles.add_argument("--project", type=Path, required=True)
    qa = commands.add_parser("qa", help="Audit current editor translations without API calls")
    qa.add_argument("--project", type=Path, required=True)
    export = commands.add_parser("export", help="Export into the independent RAT project")
    export.add_argument("--project", type=Path, required=True)
    export.add_argument("--include-unapproved", action="store_true")
    export.add_argument("--no-zip", action="store_true")
    backup = commands.add_parser("backup", help="Back up the RAT database and project metadata")
    backup.add_argument("--project", type=Path, required=True)
    restore = commands.add_parser("restore", help="Restore a backup into a NEW project directory")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    diagnostics = commands.add_parser("diagnostics", help="Write an allowlisted diagnostic report")
    diagnostics.add_argument("--project", type=Path)
    diagnostics.add_argument("--output", type=Path, required=True)
    install = commands.add_parser(
        "install-copy", help="Install on a NEW copy; originals stay untouched"
    )
    install.add_argument("--project", type=Path, required=True)
    install.add_argument("--export-id", required=True)
    install.add_argument("--destination", type=Path, required=True)
    rollback = commands.add_parser(
        "restore-copy", help="Restore the managed game copy's patch backup"
    )
    rollback.add_argument("--installation", type=Path, required=True)
    arabic = commands.add_parser("arabic", help="Inspect, configure or disable the Arabic runtime")
    arabic.add_argument("--project", type=Path, required=True)
    action = arabic.add_mutually_exclusive_group()
    action.add_argument(
        "--settings", type=Path, help="Arabic settings YAML, without outer arabic key"
    )
    action.add_argument("--disable", action="store_true")
    action.add_argument(
        "--demo-sdk", type=Path, help="Create our authored SDK demo; does not run it"
    )
    packed = commands.add_parser(
        "packed", help="Extract, resolve or clean managed packed workspaces"
    )
    packed.add_argument("--project", type=Path, required=True)
    packed_actions = packed.add_subparsers(dest="packed_action", required=True)
    unpack = packed_actions.add_parser("extract")
    unpack.add_argument("--game", type=Path, required=True)
    unpack.add_argument("--decompile", action="store_true")
    unpack.add_argument("--include-assets", action="store_true")
    unpack.add_argument("--no-import", action="store_true")
    unpack.add_argument("--engine-version", default="")
    unpack.add_argument("--confirm-version", action="store_true")
    packed_actions.add_parser("history")
    for action_name in ("info", "resolve", "clean"):
        command = packed_actions.add_parser(action_name)
        command.add_argument("--run", required=True)
        if action_name == "resolve":
            command.add_argument(
                "--selections",
                type=Path,
                required=True,
                help="JSON: conflict_id -> file_id or null (skip)",
            )
    return root


def summary(session: ProjectSession) -> dict:
    return {
        **session.project.model_dump(mode="json"),
        "path": str(session.path),
        "unit_count": session.units.count(session.project.project_id),
        "phase": 7,
    }


async def mock_demo() -> dict:
    provider = get_provider("mock")
    masked = MaskingEngine().mask("Hello [player_name]! {i}Welcome{/i}.")
    assert masked.valid and masked.protected is not None
    results = await provider.translate_batch(
        [{"unit_id": "demo_1", "text": masked.protected.masked_text}],
        source_language="en",
        target_language="ar",
        context={},
        settings={},
    )
    restored = RestorationEngine().restore(masked.protected, results[0]["translation_text"])
    return {
        "mode": "simulation_only",
        "connection": await provider.test_connection(),
        "results": results,
        "protection": masked.model_dump(mode="json"),
        "restoration": restored.model_dump(mode="json"),
        "protection_valid": restored.valid,
        "notice": "Protected echo simulation only; no real translation or API connection.",
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        configure_logging(args.log_dir if args.log_dir is not None else log_dir())
        service = ProjectService()
        if args.command == "project":
            if args.project_command == "create":
                session = service.create(
                    args.name, workspace=args.workspace, settings=load_settings(args.config)
                )
            else:
                session = service.open(args.project)
            with session:
                result = summary(session)
        elif args.command == "scan":
            if args.project:
                result = (
                    GameImportService()
                    .scan(
                        args.project, args.game, sdk_dir=args.sdk, generate=args.generate_templates
                    )
                    .model_dump(mode="json")
                )
            elif args.generate_templates:
                raise ValueError("--generate-templates requires --project.")
            else:
                result = inventory_game(args.game).model_dump(mode="json")
        elif args.command == "providers":
            result = [
                profile.model_dump(mode="json")
                for profile in ProviderSettingsService(args.project).profiles()
            ]
        elif args.command == "translate":
            manager = TranslationManager(args.project)
            if args.job:
                job_id = args.job
            else:
                configs = ProviderSettingsService(args.project).profiles()
                config = (
                    next((item for item in configs if item.profile_id == args.profile), None)
                    if args.profile
                    else ProviderConfig()
                )
                if config is None:
                    raise ValueError("Unknown profile")
                job_id = manager.create_job(config)
            result = asyncio.run(manager.run(job_id, retry_failed=args.retry_failed)).model_dump(
                mode="json"
            )
        elif args.command == "packed":
            packed = PackedGameService(args.project)
            if args.packed_action == "extract":
                report = packed.extract(
                    args.game,
                    PackedOptions(
                        decompile=args.decompile,
                        include_assets=args.include_assets,
                        import_texts=not args.no_import,
                        engine_version=args.engine_version,
                        engine_version_confirmed=args.confirm_version,
                    ),
                )
                result = report.model_dump(mode="json")
            elif args.packed_action == "history":
                result = [
                    report.model_dump(mode="json", exclude={"files"}) for report in packed.history()
                ]
            elif args.packed_action == "resolve":
                if args.selections.stat().st_size > 65536:
                    raise ValueError("Selections file too large")
                selections = json.loads(args.selections.read_text(encoding="utf-8"))
                if not isinstance(selections, dict):
                    raise ValueError("Invalid selections")
                result = packed.resolve(args.run, selections).model_dump(mode="json")
            else:
                report = (
                    packed.clean(args.run)
                    if args.packed_action == "clean"
                    else packed.load(args.run)
                )
                result = report.model_dump(mode="json")
        elif args.command == "arabic":
            runtime = ArabicRuntimeService(args.project)
            if args.demo_sdk:
                result = {"demo_path": str(runtime.create_demo(args.demo_sdk))}
            else:
                settings = runtime.load()
                if args.settings:
                    settings = runtime.save(ArabicSettings.model_validate(read_yaml(args.settings)))
                elif args.disable:
                    settings = runtime.save(
                        settings.model_copy(
                            update={
                                "runtime": settings.runtime.model_copy(update={"enabled": False})
                            }
                        )
                    )
                result = {
                    "settings": settings.model_dump(mode="json"),
                    "assessment": runtime.assess(settings).model_dump(
                        mode="json", exclude={"fonts": {"__all__": {"codepoints"}}}
                    ),
                }
        elif args.command == "qa":
            result = [
                record.model_dump(mode="json")
                for record in ReviewService(args.project).list_units()
            ]
        elif args.command == "export":
            result = (
                ExportManager(args.project)
                .export(approved_only=not args.include_unapproved, zip_package=not args.no_zip)
                .model_dump(mode="json")
            )
        elif args.command == "backup":
            result = {"backup_path": str(BackupManager(args.project).create())}
        elif args.command == "restore":
            result = {"project_path": str(BackupManager.restore(args.backup, args.destination))}
        elif args.command == "diagnostics":
            result = {"report_path": str(write_diagnostics(args.output, args.project))}
        elif args.command == "install-copy":
            result = {
                "installation": str(
                    InstallationService(args.project).install_copy(args.export_id, args.destination)
                )
            }
        elif args.command == "restore-copy":
            result = {"game_copy": str(InstallationService.restore_copy(args.installation))}
        elif args.command == "protect":
            report = GameImportService().load(args.project)
            if report is None:
                raise ValueError("Import game text first.")
            result = {
                "network_used": False,
                "ready": sum(item.ready for item in report.protection),
                "blocked": sum(not item.ready for item in report.protection),
                "units": [item.model_dump(mode="json") for item in report.protection],
            }
        elif args.command == "config-init":
            if args.output.exists():
                raise ValueError("Configuration already exists.")
            save_settings(load_settings(), args.output)
            result = {"config_path": str(args.output)}
        else:
            result = asyncio.run(mock_demo())
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except KeyboardInterrupt:
        print("RAT: interrupted; saved batches can be resumed using --job.", file=sys.stderr)
        return 130
    except (OSError, ValueError, ValidationError, SQLAlchemyError, YAMLError, ProviderError):
        log_event("operation_failed")
        # Validation/library exceptions can contain input values or SQL parameters.
        print(
            "RAT: operation failed. Check paths, permissions, configuration, and project format. "
            "For a missing Documents directory, choose --workspace explicitly.",
            file=sys.stderr,
        )
        return 2
