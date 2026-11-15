import hashlib
import json
from pathlib import Path

import pytest
from packed_support import fingerprints, write_rpa

from rat.domain.packed import DecompilerCompatibility, PackedLimits, PackedOptions
from rat.exporters.manager import ExportManager
from rat.extraction.packed_manager import PackedGameService
from rat.extraction.scanner import GameImportService
from rat.review import ReviewService


def game(tmp_path):
    root = tmp_path / "original"
    (root / "game").mkdir(parents=True)
    return root


def test_multiple_archives_manifest_discovery_import_and_originals_unchanged(project, tmp_path):
    root = game(tmp_path)
    write_rpa(
        root / "game/one.rpa", {"script.rpy": b'label start:\n    "Hello [name]"\n    return\n'}
    )
    write_rpa(
        root / "game/two.rpa",
        {
            "nested/more.rpy": b'label more:\n    "Other text"\n    return\n',
            "images/test.bin": b"small synthetic media",
        },
    )
    before = fingerprints(root)
    service = PackedGameService(project.path)
    report = service.extract(root)
    assert report.rpa_count == 2 and report.imported_count == 2 and report.status == "ready"
    assert report.view_relpath.startswith("staging/packed/")
    assert service.load(report.run_id) == report
    assert any(item.status == "skipped_asset" for item in report.files)
    entry = next(item for item in report.files if item.original_path == "script.rpy")
    assert entry.archive == "game/one.rpa" and entry.extracted_at
    output = project.path / entry.published_path
    assert hashlib.sha256(output.read_bytes()).hexdigest() == entry.sha256
    imported = GameImportService().load(project.path)
    assert imported.packed_source.original_game_dir == str(root)
    assert len(imported.units) == 2
    assert fingerprints(root) == before
    log = (project.path / "logs/packed-recovery.jsonl").read_text()
    assert "Hello [name]" not in log and "extraction_finished" in log


def test_conflicts_require_explicit_selection_and_do_not_replace_existing_import(project, tmp_path):
    root = game(tmp_path)
    (root / "game/original.rpy").write_text('label start:\n    "Keep existing"\n')
    previous = GameImportService().scan(project.path, root)
    write_rpa(root / "game/one.rpa", {"shared.rpy": b'label a:\n    "First choice"\n'})
    write_rpa(root / "game/two.rpa", {"SHARED.rpy": b'label b:\n    "Second choice"\n'})
    service = PackedGameService(project.path)
    report = service.extract(root)
    assert report.status == "conflicts" and len(report.conflicts) == 1
    assert GameImportService().load(project.path).units == previous.units
    conflict = report.conflicts[0]
    selected = next(item for item in report.files if item.archive == "game/two.rpa")
    old_view = project.path / report.view_relpath
    resolved = service.resolve(report.run_id, {conflict.conflict_id: selected.file_id})
    assert resolved.status == "ready" and resolved.imported_count == 2
    assert resolved.view_relpath != report.view_relpath and old_view.is_dir()
    texts = {unit.source_text for unit in GameImportService().load(project.path).units}
    assert "Second choice" in texts and "First choice" not in texts


def test_identical_duplicates_are_deduplicated_and_path_conflicts_are_explicit(project, tmp_path):
    root = game(tmp_path)
    text = b'label a:\n    "Same"\n'
    write_rpa(root / "game/one.rpa", {"same.rpy": text, "nested.rpy": text})
    write_rpa(root / "game/two.rpa", {"same.rpy": text, "nested.rpy/file.rpy": text})
    report = PackedGameService(project.path).extract(root)
    assert len(report.conflicts) == 1 and report.conflicts[0].kind == "file_directory"
    assert (
        sum(bool(item.published_path) for item in report.files if item.original_path == "same.rpy")
        == 1
    )


def test_traversal_member_fails_without_writing_outside_workspace(project, tmp_path):
    root = game(tmp_path)
    write_rpa(
        root / "game/bad.rpa", {"../../EVIL.rpy": b"bad", "good.rpy": b'label a:\n    "Good"\n'}
    )
    report = PackedGameService(project.path).extract(root)
    assert report.status == "partial" and report.imported_count == 1
    assert any(item.error_code for item in report.files if "EVIL" in item.original_path)
    assert not list(project.path.rglob("EVIL.rpy")) and not (tmp_path / "EVIL.rpy").exists()


def test_repeated_extraction_uses_fresh_runs_without_overwriting_files(project, tmp_path):
    root = game(tmp_path)
    write_rpa(root / "game/data.rpa", {"script.rpy": b'label a:\n    "Stable"\n'})
    service = PackedGameService(project.path)
    first = service.extract(root)
    saved = GameImportService().load(project.path)
    second = service.extract(root)
    assert first.workspace_relpath != second.workspace_relpath
    assert GameImportService().load(project.path).units == saved.units
    assert len(service.history()) == 2


def test_clean_preserves_database_translations_and_exportable_template_snapshot(project, tmp_path):
    root = game(tmp_path)
    fixture = Path(__file__).parents[1] / "fixtures/game_with_tl/game"
    files = {
        path.relative_to(fixture).as_posix(): path.read_bytes() for path in fixture.rglob("*.rpy")
    }
    write_rpa(root / "game/small.rpa", files)
    service = PackedGameService(project.path)
    report = service.extract(root)
    assert report.imported_count == 8
    review = ReviewService(project.path)
    for item in review.list_units():
        review.save(item.unit_id, item.source.source_text)
    review.action([item.unit_id for item in review.list_units()], "approve")
    before = fingerprints(root)
    cleaned = service.clean(report.run_id)
    assert cleaned.status == "cleaned" and not (project.path / report.workspace_relpath).exists()
    assert all(item.state == "approved" for item in review.list_units())
    assert ExportManager(project.path).export().exported_count == 8
    assert fingerprints(root) == before
    assert (project.path / report.manifest_relpath).is_file()


def test_unknown_and_legacy_rpyc_are_reported_without_running_a_decompiler(project, tmp_path):
    root = game(tmp_path)
    write_rpa(root / "game/data.rpa", {"orphan.rpyc": b"RENPY RPC2 untrusted bytes"})
    report = PackedGameService(project.path).extract(root, PackedOptions(decompile=True))
    item = next(item for item in report.files if item.original_path == "orphan.rpyc")
    assert report.rpyc_count == 1 and item.orphan_rpyc
    assert item.decompile_status == "unsupported" and item.error_code == "unknown_engine_version"


def test_view_tampering_and_forged_manifest_cannot_be_imported(project, tmp_path):
    root = game(tmp_path)
    write_rpa(root / "game/data.rpa", {"script.rpy": b'label a:\n    "Original"\n'})
    service = PackedGameService(project.path)
    report = service.extract(root)
    snapshot = GameImportService().load(project.path)
    view = project.path / report.view_relpath
    (view / "game/script.rpy").write_text('label a:\n    "Changed"\n')
    with pytest.raises(ValueError, match="changed"):
        GameImportService().scan(
            project.path, view, packed_manifest=project.path / report.manifest_relpath
        )
    assert GameImportService().load(project.path).units == snapshot.units
    manifest = project.path / report.manifest_relpath
    data = json.loads(manifest.read_text())
    data["workspace_relpath"] = "staging/../exports"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="path"):
        service.clean(report.run_id)


def test_filtered_large_media_does_not_block_scripts_and_selected_size_is_bounded(
    project, tmp_path
):
    root = game(tmp_path)
    write_rpa(
        root / "game/data.rpa",
        {
            "large.bin": b"x" * 2048,
            "script.rpy": b'label a:\n    "Small example"\n',
        },
    )
    limits = PackedLimits(max_file_bytes=1024, max_total_bytes=1024)
    service = PackedGameService(project.path)
    report = service.extract(root, PackedOptions(limits=limits))
    assert report.status == "ready" and report.imported_count == 1
    report = service.extract(root, PackedOptions(limits=limits, include_assets=True))
    assert report.status == "partial" and report.imported_count == 1
    assert any(item.error_code == "packed_file_size_limit" for item in report.files)


def test_games_and_runs_are_isolated_and_cleanup_removes_only_selected_run(project, tmp_path):
    first = game(tmp_path)
    second = tmp_path / "second-game"
    write_rpa(first / "game/data.rpa", {"script.rpy": b'label a:\n    "First"\n'})
    write_rpa(second / "game/data.rpa", {"script.rpy": b'label a:\n    "Second"\n'})
    service = PackedGameService(project.path)
    one, two = service.extract(first), service.extract(second)
    assert one.game_key != two.game_key
    service.clean(one.run_id)
    assert (project.path / two.workspace_relpath).is_dir()
    assert (first / "game/data.rpa").is_file() and (second / "game/data.rpa").is_file()
    assert [unit.source_text for unit in GameImportService().load(project.path).units] == ["Second"]


def test_adapter_compatibility_blocks_decompile_and_paired_rpy_is_not_decompiled(project, tmp_path):
    class UnsupportedAdapter:
        adapter_id = "test-unsupported"
        calls = 0

        def compatibility(self, engine, data):
            self.calls += 1
            return DecompilerCompatibility(supported=False, code="fixture_incompatible")

        def decompile(self, data):
            raise AssertionError("incompatible files must never reach decompile")

    root = game(tmp_path)
    write_rpa(
        root / "game/data.rpa",
        {
            "paired.rpy": b'label a:\n    "Source exists"\n',
            "paired.rpyc": b"synthetic paired bytecode",
            "orphan.rpyc": b"synthetic orphan bytecode",
        },
    )
    adapter = UnsupportedAdapter()
    report = PackedGameService(project.path, decompiler=adapter).extract(
        root, PackedOptions(decompile=True)
    )
    assert adapter.calls == 1 and report.rpyc_count == 2
    paired = next(item for item in report.files if item.original_path == "paired.rpyc")
    assert not paired.orphan_rpyc and paired.decompile_status is None
    assert any(item.error_code == "fixture_incompatible" for item in report.files)


def test_recovery_without_supported_text_preserves_existing_import(project, tmp_path):
    source = game(tmp_path)
    (source / "game/script.rpy").write_text('label a:\n    "Keep my imported text"\n')
    previous = GameImportService().scan(project.path, source)
    empty = tmp_path / "unsupported-game"
    write_rpa(empty / "game/data.rpa", {"only-python.rpy": b"init python:\n    x = 1\n"})
    report = PackedGameService(project.path).extract(empty)
    assert report.import_error == "no_supported_recovered_texts"
    assert GameImportService().load(project.path).units == previous.units
