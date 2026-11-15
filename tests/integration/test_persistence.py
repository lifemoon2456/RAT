import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from rat.config.models import Settings
from rat.database.tables import translation_revisions, translations, units
from rat.domain.enums import UnitStatus
from rat.domain.models import SourceUnit
from rat.projects import ProjectService


def test_custom_settings_choose_workspace_and_survive_reopen(tmp_path):
    workspace = tmp_path / "مشاريع #1"
    settings = Settings.model_validate(
        {"app": {"workspace_dir": str(workspace)}, "translation": {"batch_max_units": 5}}
    )
    with ProjectService().create("configured", settings=settings) as created:
        path = created.path
        assert path.parent == workspace
    with ProjectService().open(path) as reopened:
        assert reopened.settings == settings
        assert reopened.settings.translation.batch_max_units == 5


def test_close_reopen_preserves_sources_results_and_revisions(project, source):
    project.units.add_source(source)
    project.units.save_translation(source.unit_id, "ترجمة أولى", provider_id="manual")
    project.units.save_translation(
        source.unit_id, source.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    path, metadata, settings = project.path, project.project, project.settings
    project.close()
    with ProjectService().open(path) as reopened:
        assert reopened.project == metadata
        assert reopened.settings == settings
        actual = reopened.units.get(source.unit_id)
        assert actual.source_text == source.source_text
        assert actual.old == source.old
        assert actual.renpy_identifier == source.renpy_identifier
        assert actual.source_sha256 == source.source_sha256
        assert actual.translation_text == source.source_text
        assert actual.status == UnitStatus.APPROVED
        assert reopened.units.revision_count(source.unit_id) == 2
        with pytest.raises(ValueError, match="Approved"):
            reopened.units.save_translation(source.unit_id, "replacement", provider_id="mock")
        assert reopened.units.get(source.unit_id) == actual


def test_source_and_approved_translation_are_protected_in_sql(project, source):
    project.units.add_source(source)
    project.units.save_translation(
        source.unit_id, source.source_text, provider_id="manual", status=UnitStatus.APPROVED
    )
    for statement in (
        units.update().values(source_data={"source_text": "modified"}),
        translations.update().values(translation_text="modified"),
        translations.delete(),
    ):
        with pytest.raises(IntegrityError):
            with project.database.transaction() as connection:
                connection.execute(statement)
    assert project.units.get(source.unit_id).source_text == source.source_text
    assert project.units.revision_count(source.unit_id) == 1


def test_same_text_different_contexts_stay_separate(project, source):
    project.units.add_source(source)
    data = source.model_dump(exclude={"source_sha256"})
    data.update(unit_id="second", renpy_identifier="another_real_fixture_id", speaker="other")
    second = SourceUnit.model_validate(data)
    project.units.add_source(second)
    project.units.save_translation(source.unit_id, "الأولى", provider_id="manual")
    project.units.save_translation(second.unit_id, "الثانية", provider_id="manual")
    assert project.units.count(project.project.project_id) == 2
    assert project.units.get(source.unit_id).translation_text == "الأولى"
    assert project.units.get(second.unit_id).translation_text == "الثانية"


def test_duplicate_source_location_cannot_replace_source(project, source):
    project.units.add_source(source)
    data = source.model_dump(exclude={"source_sha256"})
    data["unit_id"] = "another_internal_id"
    with pytest.raises(IntegrityError):
        project.units.add_source(SourceUnit.model_validate(data))
    assert project.units.count(project.project.project_id) == 1


def test_foreign_keys_and_transaction_rollback(project):
    with pytest.raises(IntegrityError):
        project.units.save_translation("missing", "text", provider_id="mock")
    with project.database.transaction() as connection:
        assert connection.execute(select(translation_revisions)).all() == []
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    with pytest.raises(RuntimeError):
        with project.database.transaction() as connection:
            connection.execute(text("CREATE TABLE must_rollback (value TEXT)"))
            raise RuntimeError("interrupt")
    with project.database.transaction() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE name='must_rollback'"
            ).all()
            == []
        )


def test_failed_revision_insert_rolls_back_translation_change(project, source):
    project.units.add_source(source)
    project.units.save_translation(source.unit_id, "الأولى", provider_id="manual")
    with project.database.transaction() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_revision BEFORE INSERT ON translation_revisions "
            "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
        )
    with pytest.raises(IntegrityError):
        project.units.save_translation(source.unit_id, "لن تحفظ", provider_id="mock")
    assert project.units.get(source.unit_id).translation_text == "الأولى"
    assert project.units.revision_count(source.unit_id) == 1


def test_reject_unvalidated_copy_and_unsupported_validation_status(project, source):
    with pytest.raises(ValidationError):
        project.units.add_source(source.model_copy(update={"source_text": "changed"}))
    project.units.add_source(source)
    with pytest.raises(ValueError, match="unavailable"):
        project.units.save_translation(
            source.unit_id, "translation", provider_id="mock", status=UnitStatus.VALIDATED
        )


@pytest.mark.parametrize("mutation", ["version", "manifest", "missing_database"])
def test_invalid_projects_are_rejected_without_reinitializing(project, mutation):
    path = project.path
    project.close()
    if mutation == "version":
        with project.database.transaction() as connection:
            connection.exec_driver_sql("UPDATE schema_version SET version=999")
    elif mutation == "manifest":
        manifest = path / "project.yaml"
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        data["project"]["name"] = "Wrong name"
        manifest.write_text(yaml.safe_dump(data), encoding="utf-8")
    else:
        (path / "project.sqlite").unlink()
    before = (path / "project.sqlite").read_bytes() if mutation != "missing_database" else None
    with pytest.raises(ValueError):
        ProjectService().open(path)
    if mutation == "missing_database":
        assert not (path / "project.sqlite").exists()
    else:
        assert (path / "project.sqlite").read_bytes() == before


def test_creating_workspace_never_reads_or_changes_a_game(tmp_path):
    import hashlib

    game = tmp_path / "original" / "game"
    game.mkdir(parents=True)
    script = game / "script.rpy"
    content = b'init python:\n    raise RuntimeError("must never execute")\n'
    script.write_bytes(content)
    before = hashlib.sha256(script.read_bytes()).digest()
    with ProjectService().create("isolated", workspace=tmp_path / "workspace") as session:
        assert session.units.count(session.project.project_id) == 0
        assert session.path.is_relative_to(tmp_path / "workspace")
    assert hashlib.sha256(script.read_bytes()).digest() == before
    assert list(game.iterdir()) == [script]


def test_bad_name_creates_no_workspace(tmp_path):
    workspace = tmp_path / "work"
    with pytest.raises(ValueError):
        ProjectService().create("   ", workspace=workspace)
    assert not workspace.exists()
