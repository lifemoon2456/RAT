import json

from packed_support import write_rpa

from rat.cli.commands import main


def test_cli_extract_info_and_cleanup_share_workspace_and_manifest(project, tmp_path, capsys):
    game = tmp_path / "original"
    archive = write_rpa(game / "game/fixture.rpa", {"script.rpy": b'label a:\n    "CLI example"\n'})
    common = ["--log-dir", str(project.path / "logs"), "packed", "--project", str(project.path)]
    assert main(common + ["extract", "--game", str(game)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["rpa_count"] == 1 and report["imported_count"] == 1
    assert main(common + ["info", "--run", report["run_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert main(common + ["clean", "--run", report["run_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cleaned"
    assert archive.is_file() and (project.path / "project.sqlite").is_file()
