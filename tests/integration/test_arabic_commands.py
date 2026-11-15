import json

from rat.cli.commands import main


def test_cli_inspects_and_disables_runtime_without_guessing_version(project, capsys):
    assert (
        main(["--log-dir", str(project.path / "logs"), "arabic", "--project", str(project.path)])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["assessment"]["profile"]["mode"] == "unknown"
    assert "codepoints" not in report["assessment"]["fonts"][0]
    assert not report["settings"]["runtime"]["enabled"]
    assert (
        main(
            [
                "--log-dir",
                str(project.path / "logs"),
                "arabic",
                "--project",
                str(project.path),
                "--disable",
            ]
        )
        == 0
    )
    assert not json.loads(capsys.readouterr().out)["settings"]["runtime"]["enabled"]
