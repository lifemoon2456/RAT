import hashlib
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import yaml

from rat.database.discovery_repository import DiscoveryRepository
from rat.discovery.capabilities import capabilities
from rat.discovery.inventory import inventory_game
from rat.domain.discovery import (
    DiscoveryIssue,
    ImportReport,
    PackedProvenance,
    ParsedText,
    TemplateText,
    UnitOrigin,
)
from rat.domain.models import SourceUnit
from rat.extraction.renpy_sdk import generate_templates
from rat.extraction.rpy_parser import parse_rpy
from rat.extraction.translation_parser import parse_template
from rat.projects import ProjectManifest, ProjectService
from rat.protection.service import ProtectionService
from rat.security.safe_paths import ScanError, read_source


class GameImportService:
    def load(self, project_dir: Path) -> ImportReport | None:
        with ProjectService().open(project_dir) as session:
            report = DiscoveryRepository(session.database).load(session.project.project_id)
            return self.with_protection(report) if report is not None else None

    @staticmethod
    def with_protection(report: ImportReport) -> ImportReport:
        return report.model_copy(
            update={"protection": ProtectionService().prepare_units(report.units)}
        )

    def scan(
        self,
        project_dir: Path,
        game_dir: Path,
        *,
        sdk_dir: Path | None = None,
        generate: bool = False,
        progress: Callable[[str], None] | None = None,
        packed_manifest: Path | None = None,
    ) -> ImportReport:
        notify = progress or (lambda _message: None)
        notify("inventory")
        inventory = inventory_game(game_dir)
        root = Path(inventory.game_dir)
        project_dir = project_dir.resolve()
        packed = None
        if packed_manifest is not None:
            from rat.extraction.packed_workspace import validate_packed_import

            packed = validate_packed_import(project_dir, root, packed_manifest)
            inventory = inventory.model_copy(update={"engine": packed.engine})
            if generate and (
                packed.status != "ready" or any(item.partial for item in packed.files)
            ):
                raise ScanError("sdk_generation_on_partial_recovery_not_supported")
        if project_dir.is_relative_to(root) or (
            root.is_relative_to(project_dir) and packed is None
        ):
            raise ScanError("workspace_overlaps_game")
        with ProjectService().open(project_dir) as session:
            issues = list(inventory.issues)
            raw: dict[str, list[ParsedText]] = {}
            for item in inventory.files:
                if item.language is None and item.extension in {".rpy", ".rpym"} and item.sha256:
                    try:
                        extracted, unsupported = parse_rpy(read_source(root / item.relpath))
                        raw[item.relpath] = extracted
                        issues.extend(
                            issue.model_copy(update={"path": item.relpath}) for issue in unsupported
                        )
                    except ScanError as error:
                        issues.append(DiscoveryIssue(code=error.code, path=item.relpath))
            template_root = root
            sdk_version = None
            if generate:
                if sdk_dir is None:
                    raise ScanError("sdk_required")
                notify("sdk_generation")
                if packed_manifest is None:
                    template_root, sdk_version = generate_templates(inventory, sdk_dir, project_dir)
                else:
                    template_root, sdk_version = generate_templates(
                        inventory, sdk_dir, project_dir, packed_manifest=packed_manifest
                    )
            template_paths = []
            if generate:
                template_paths = sorted((template_root / "game" / "tl" / "arabic").rglob("*.rpy"))
            else:
                template_paths = [
                    root / item.relpath
                    for item in inventory.files
                    if item.language == "arabic"
                    and item.extension in {".rpy", ".rpym"}
                    and item.sha256
                ]
            notify("parse_templates")
            templates: list[TemplateText] = []
            for path in template_paths:
                relative = path.relative_to(template_root).as_posix()
                try:
                    entries, unsupported = parse_template(read_source(path), relative)
                    templates.extend(entries)
                    issues.extend(unsupported)
                except ScanError as error:
                    issues.append(DiscoveryIssue(code=error.code, path=relative))
            candidates: dict[str, tuple[SourceUnit, UnitOrigin, str | None]] = {}
            conflicts: set[str] = set()
            ordinals: dict[tuple[str, str, int], int] = {}
            matched_source: set[tuple[str, int]] = set()
            for entry in templates:
                original = entry.original
                relative, line = entry.template_path, entry.template_line
                verified = False
                if entry.reference_path in raw:
                    matches = [
                        item
                        for item in raw[entry.reference_path]
                        if item.text == original.text
                        and (entry.is_string or item.speaker == original.speaker)
                        and item.line == entry.reference_line
                    ]
                    if matches:
                        original = matches[0]
                        relative, line = entry.reference_path, original.line
                        verified = True
                        matched_source.add((relative, line))
                        if entry.is_string:
                            for path, values in raw.items():
                                matched_source.update(
                                    (path, value.line)
                                    for value in values
                                    if value.text == original.text
                                    and value.kind.value in {"menu_choice", "screen_text", "string"}
                                )
                    elif any(
                        item.line == entry.reference_line for item in raw[entry.reference_path]
                    ):
                        issues.append(
                            DiscoveryIssue(
                                code="template_source_mismatch",
                                path=entry.template_path,
                                line=entry.template_line,
                            )
                        )
                        continue
                    else:
                        issues.append(
                            DiscoveryIssue(
                                code="unverified_template_source",
                                path=entry.template_path,
                                line=entry.template_line,
                            )
                        )
                if entry.is_string:
                    position = (
                        "strings:" + hashlib.sha256(entry.original.text.encode("utf-8")).hexdigest()
                    )
                else:
                    counter_key = (entry.template_path, entry.identifier, entry.block_line)
                    ordinal = ordinals.get(counter_key, 0)
                    ordinals[counter_key] = ordinal + 1
                    position = f"translate:{entry.identifier}:{ordinal}"
                source = SourceUnit(
                    unit_id=uuid4().hex,
                    project_id=session.project.project_id,
                    source_relpath=relative,
                    source_line=line,
                    renpy_identifier=entry.identifier,
                    source_text=original.text,
                    source_literal=entry.original.literal,
                    old=entry.original.text if entry.is_string else None,
                    source_location=position,
                    kind=original.kind,
                    speaker=original.speaker,
                    label=original.label,
                    confidence="official_template"
                    if generate and verified
                    else "existing_template",
                )
                origin = UnitOrigin(
                    unit_id=source.unit_id,
                    template_path=entry.template_path,
                    template_line=entry.template_line,
                    source_verified=verified,
                    confidence=source.confidence,
                )
                previous = candidates.get(position)
                if previous:
                    if (
                        previous[0].source_text != source.source_text
                        or previous[2] != entry.translation
                    ):
                        conflicts.add(position)
                        issues.append(
                            DiscoveryIssue(
                                code="conflicting_template_entry", path=relative, line=line
                            )
                        )
                    else:
                        issues.append(
                            DiscoveryIssue(
                                code="duplicate_template_entry", path=relative, line=line
                            )
                        )
                    continue
                candidates[position] = (source, origin, entry.translation)
            # Unmatched source statements remain visible, with no guessed engine identifier.
            for relative, entries in raw.items():
                for entry in entries:
                    if (relative, entry.line) in matched_source:
                        continue
                    position = f"source:{relative}:{entry.line}"
                    source = SourceUnit(
                        unit_id=uuid4().hex,
                        project_id=session.project.project_id,
                        source_relpath=relative,
                        source_line=entry.line,
                        source_text=entry.text,
                        source_literal=entry.literal,
                        renpy_identifier=entry.renpy_identifier,
                        source_location=position,
                        kind=entry.kind,
                        speaker=entry.speaker,
                        label=entry.label,
                    )
                    candidates[position] = (
                        source,
                        UnitOrigin(unit_id=source.unit_id, source_verified=True),
                        None,
                    )
            for position in conflicts:
                candidates.pop(position, None)
            if "no_supported_text_source" in capabilities(inventory) and not generate:
                issues.append(DiscoveryIssue(code="no_supported_text_source"))
            if not templates:
                issues.append(DiscoveryIssue(code="no_official_templates"))
            notify("save")
            if packed and not candidates:
                raise ScanError("no_supported_recovered_texts")
            current_inventory = inventory_game(root)
            if current_inventory.files != inventory.files:
                raise ScanError("game_changed_during_scan")
            report = ImportReport(
                inventory=inventory,
                issues=tuple(issues),
                sdk_dir=str(sdk_dir.resolve()) if sdk_dir else None,
                sdk_version=sdk_version,
                template_dir=str(template_root) if generate else None,
                packed_source=PackedProvenance(
                    run_id=packed.run_id,
                    original_game_dir=packed.original_game_dir,
                    manifest_relpath=packed.manifest_relpath,
                    partial=packed.status != "ready",
                )
                if packed
                else None,
            )
            report = DiscoveryRepository(session.database).save(
                session.project.project_id, report, list(candidates.values())
            )
            temporary = project_dir / "inventory.json.tmp"
            temporary.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(project_dir / "inventory.json")
            manifest = ProjectManifest(
                project=session.project,
                settings=session.settings,
                game_dir=packed.original_game_dir if packed else str(root),
                sdk_dir=report.sdk_dir,
            )
            temporary = project_dir / "project.yaml.tmp"
            temporary.write_text(
                yaml.safe_dump(
                    manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False
                ),
                encoding="utf-8",
            )
            temporary.replace(project_dir / "project.yaml")
            return self.with_protection(report)
