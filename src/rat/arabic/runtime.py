import hashlib
import json
from importlib.resources import files as resource_files
from pathlib import Path
from uuid import uuid4

import yaml

from rat.arabic.fonts import FontManager
from rat.arabic.rtl_profiles import compatibility, resolve_profile
from rat.arabic.style_generator import RUNTIME_PATH, StyleGenerator
from rat.config.models import ArabicSettings, read_yaml
from rat.database.discovery_repository import DiscoveryRepository
from rat.discovery.version_detector import detect_version
from rat.domain.arabic import FontChoice, RuntimeAssessment
from rat.domain.discovery import EngineVersion, GameInventory, ImportReport
from rat.exporters.safe_io import checked_path, project_directory
from rat.jobs.manager import ProjectJobLock
from rat.projects import ProjectManifest, ProjectService
from rat.protection.tokenizer import TextTokenizer
from rat.security.safe_paths import read_source_bytes


class ArabicRuntimeService:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.font_manager = FontManager()

    def load(self) -> ArabicSettings:
        with ProjectService().open(self.project_dir) as session:
            return session.settings.arabic

    def assess(self, settings: ArabicSettings, *, imported=None) -> RuntimeAssessment:
        if imported is None:
            with ProjectService().open(self.project_dir) as session:
                imported = DiscoveryRepository(session.database).load(session.project.project_id)
        detected = EngineVersion()
        if imported:
            root = Path(
                imported.packed_source.original_game_dir
                if imported.packed_source
                else imported.inventory.game_dir
            )
            detected = detect_version(root) if root.is_dir() else imported.inventory.engine
        errors = []
        try:
            profile = resolve_profile(detected, settings.runtime)
        except ValueError as error:
            profile = compatibility(None)
            errors.append(str(error))
        warnings, infos = list(profile.warnings), []
        for choice in (settings.runtime.primary_font, *settings.runtime.fallback_fonts):
            try:
                info = self.font_manager.inspect(self.font_manager.path(choice, self.project_dir))
                infos.append(info)
                self.font_manager.license_bytes(choice, self.project_dir)
                if info.embedding_restricted:
                    errors.append("font_embedding_restricted")
                if info.missing_arabic:
                    warnings.append("font_missing_arabic:" + info.family)
            except (OSError, ValueError):
                errors.append("font_file_or_license_invalid")
        complete = [info for info in infos if not info.missing_arabic]
        if not complete:
            errors.append("no_font_covers_basic_arabic")
        elif not any(font.shaping_tables for font in complete):
            errors.append("arabic_shaping_tables_missing")
        if not profile.supported:
            errors.append("runtime_version_not_supported_or_unknown")
        if settings.runtime.target_version:
            warnings.append("target_version_confirmed_by_user")
        if imported:
            for item in imported.inventory.files:
                if item.relpath.casefold() == RUNTIME_PATH.casefold():
                    errors.append("arabic_runtime_filename_conflict")
                if item.extension not in {".rpy", ".rpym"}:
                    continue
                try:
                    content = read_source_bytes(
                        checked_path(Path(imported.inventory.game_dir), item.relpath)
                    ).decode("utf-8-sig")
                    if "rat_arabic_runtime" in content:
                        errors.append("arabic_runtime_namespace_conflict")
                    if "translate arabic python" in content or "translate arabic style" in content:
                        warnings.append("existing_arabic_style_overrides:" + item.relpath)
                except (OSError, ValueError):
                    warnings.append("style_inspection_unavailable:" + item.relpath)
        return RuntimeAssessment(
            profile=profile,
            fonts=tuple(infos),
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(dict.fromkeys(errors)),
        )

    def save(self, settings: ArabicSettings):
        settings = ArabicSettings.model_validate(settings.model_dump())
        with ProjectService().open(self.project_dir) as session, ProjectJobLock(self.project_dir):
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            if settings.runtime.enabled:
                assessment = self.assess(settings, imported=imported)
                if not assessment.valid:
                    raise ValueError("arabic_runtime_settings_invalid")
                project_directory(
                    session.path,
                    "runtime",
                    game_dir=(
                        imported.packed_source.original_game_dir
                        if imported.packed_source
                        else imported.inventory.game_dir
                    )
                    if imported
                    else None,
                )
                managed = []
                choices = (settings.runtime.primary_font, *settings.runtime.fallback_fonts)
                for choice, info in zip(choices, assessment.fonts, strict=True):
                    data = read_source_bytes(Path(info.path), max_bytes=16 * 1024 * 1024)
                    if hashlib.sha256(data).hexdigest() != info.sha256:
                        raise ValueError("font_changed_during_import")
                    font_path = f"runtime/fonts/{info.sha256}{Path(info.path).suffix.lower()}"
                    license_path = f"runtime/fonts/{info.sha256}.license.txt"
                    for path, payload in (
                        (font_path, data),
                        (license_path, self.font_manager.license_bytes(choice, session.path)),
                    ):
                        target = checked_path(session.path, path)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists() and target.read_bytes() != payload:
                            raise ValueError("managed_font_hash_conflict")
                        if not target.exists():
                            target.write_bytes(payload)
                    managed.append(
                        FontChoice(
                            path=font_path, license_path=license_path, redistribution_allowed=True
                        )
                    )
                options = settings.runtime.model_copy(
                    update={"primary_font": managed[0], "fallback_fonts": tuple(managed[1:])}
                )
                settings = settings.model_copy(update={"runtime": options})
            manifest = ProjectManifest.model_validate(read_yaml(session.path / "project.yaml"))
            all_settings = manifest.settings.model_copy(update={"arabic": settings})
            manifest = manifest.model_copy(update={"settings": all_settings})
            temporary = checked_path(session.path, f"runtime-settings-{uuid4().hex}.tmp")
            temporary.write_text(
                yaml.safe_dump(
                    manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False
                ),
                encoding="utf-8",
            )
            temporary.replace(checked_path(session.path, "project.yaml"))
        return settings

    def bundle(self, settings: ArabicSettings, *, imported, texts=()):
        if not settings.runtime.enabled:
            return {}, {"enabled": False}
        assessment = self.assess(settings, imported=imported)
        if not assessment.valid:
            raise ValueError("arabic_runtime_settings_invalid")
        files, paths = {}, {}
        for choice, info in zip(
            (settings.runtime.primary_font, *settings.runtime.fallback_fonts),
            assessment.fonts,
            strict=True,
        ):
            asset_name = info.sha256[:16]
            path = f"game/tl/arabic/fonts/{asset_name}{Path(info.path).suffix.lower()}"
            data = read_source_bytes(Path(info.path), max_bytes=16 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != info.sha256:
                raise ValueError("font_changed_during_export")
            if path in files and files[path] != data:
                raise ValueError("font_filename_collision")
            files[path] = data
            files[f"game/tl/arabic/fonts/{asset_name}.license.txt"] = (
                self.font_manager.license_bytes(choice, self.project_dir)
            )
            paths[info.sha256] = path.removeprefix("game/")
        code = StyleGenerator().generate(
            settings.runtime,
            assessment.profile,
            assessment.fonts,
            paths,
            direction=settings.layout_direction,
        )
        files[RUNTIME_PATH] = code.encode("utf-8")
        covered = set().union(*(set(font.codepoints) for font in assessment.fonts))
        literal_texts = [
            token.text
            for text in texts
            for token in TextTokenizer().tokenize(text).tokens
            if token.kind in {"text", "escape", "newline"}
        ]
        missing = sorted(
            {
                ord(char)
                for text in literal_texts
                for char in text
                if not char.isspace()
                and ord(char) not in covered
                and ord(char) not in {0x200C, 0x200D, 0x200E, 0x200F}
            }
        )
        if missing:
            raise ValueError("export_text_contains_missing_font_glyphs")
        metadata = {
            "enabled": True,
            "profile": assessment.profile.model_dump(mode="json"),
            "warnings": assessment.warnings,
            "font_hashes": list(paths),
            "disable_file": "game/tl/arabic/rat_runtime.disabled",
            "logical_unicode_preserved": True,
            "sizes": settings.runtime.sizes.model_dump(),
            "layout_direction": settings.layout_direction,
            "align_interfaces": settings.runtime.align_interfaces,
            "fonts": [
                {"file": paths[info.sha256], "sha256": info.sha256, "family": info.family}
                for info in assessment.fonts
            ],
        }
        files["arabic-runtime.json"] = json.dumps(metadata, indent=2).encode("utf-8")
        return files, metadata

    def create_demo(self, sdk_dir: Path, settings: ArabicSettings | None = None):
        from rat.extraction.renpy_sdk import sdk_command

        sdk_command(sdk_dir)  # Layout check only; no process is executed here.
        version = detect_version(sdk_dir)
        settings = settings or self.load()
        options = settings.runtime.model_copy(
            update={
                "enabled": True,
                "target_version": version.version or "",
                "target_version_confirmed": True,
            }
        )
        settings = settings.model_copy(update={"runtime": options})
        with ProjectService().open(self.project_dir) as session, ProjectJobLock(self.project_dir):
            imported = DiscoveryRepository(session.database).load(session.project.project_id)
            directory = project_directory(
                session.path,
                "staging",
                game_dir=(
                    imported.packed_source.original_game_dir
                    if imported and imported.packed_source
                    else imported.inventory.game_dir
                    if imported
                    else None
                ),
            )
            target = checked_path(directory, f"arabic-demo-{uuid4().hex}")
            target.mkdir()
            demo_report = ImportReport(
                inventory=GameInventory(
                    game_dir=str(target), files=(), translation_languages=(), engine=version
                )
            )
            bundle, _metadata = self.bundle(settings, imported=demo_report)
            source = resource_files("rat") / "resources/arabic_demo"
            for name in ("game/script.rpy", "README_AR.txt"):
                bundle[name] = (source / name).read_bytes()
            for relative, data in bundle.items():
                path = checked_path(target, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        return target
