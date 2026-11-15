import json
import os
import subprocess
import sys
from pathlib import Path

from rat.cli.commands import main
from rat.config.models import Settings, save_settings


def run_cli(tmp_path: Path, *args: str):
    executable = Path(sys.executable).parent / ("rat.exe" if os.name == "nt" else "rat")
    return subprocess.run(
        [str(executable), "--log-dir", str(tmp_path / "logs"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_create_and_reopen_in_different_processes(tmp_path):
    created = run_cli(
        tmp_path,
        "project",
        "create",
        "--name",
        "مشروع اختبار",
        "--workspace",
        str(tmp_path / "مشاريع"),
    )
    assert created.returncode == 0, created.stderr
    info = json.loads(created.stdout)
    reopened = run_cli(tmp_path, "project", "info", "--project", info["path"])
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout) == info
    assert (Path(info["path"]) / "project.yaml").is_file()


def test_demo_is_explicitly_simulated(tmp_path):
    result = run_cli(tmp_path, "mock-demo")
    assert result.returncode == 0, result.stderr
    demo = json.loads(result.stdout)
    assert demo["mode"] == "simulation_only"
    assert demo["results"][0]["simulated"]
    assert demo["connection"]["network_used"] is False
    assert demo["protection_valid"]
    assert demo["restoration"]["text"] == "Hello [player_name]! {i}Welcome{/i}."


def test_invalid_config_does_not_leak_input_to_output_or_logs(tmp_path, capsys):
    secret = "SYNTHETIC_TEST_SECRET_NOT_A_REAL_KEY"
    path = tmp_path / "invalid.yaml"
    path.write_text(f"api_key: {secret}\n", encoding="utf-8")
    assert (
        main(
            [
                "--log-dir",
                str(tmp_path / "logs"),
                "project",
                "create",
                "--name",
                "x",
                "--workspace",
                str(tmp_path / "workspace"),
                "--config",
                str(path),
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    logs = (tmp_path / "logs" / "application.log").read_text(encoding="utf-8")
    assert secret not in output.out + output.err + logs
    assert not (tmp_path / "workspace").exists()


def test_config_init_refuses_to_overwrite(tmp_path):
    path = tmp_path / "settings.yaml"
    first = run_cli(tmp_path, "config-init", "--output", str(path))
    assert first.returncode == 0, first.stderr
    before = path.read_bytes()
    second = run_cli(tmp_path, "config-init", "--output", str(path))
    assert second.returncode == 2
    assert path.read_bytes() == before


def test_desktop_bootstrap_runs_a_real_qt_event_loop(tmp_path):
    config = tmp_path / "settings.yaml"
    save_settings(Settings(), config)
    script = """
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rat.app import main
application = QApplication([])
QTimer.singleShot(150, application.quit)
raise SystemExit(main(sys.argv[1:]))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--config",
            str(config),
            "--log-dir",
            str(tmp_path / "logs"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "application_started" in (tmp_path / "logs" / "application.log").read_text()


def test_packaging_diagnostic_opens_window_and_reopens_project(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "rat_desktop.py"
    result = subprocess.run(
        [sys.executable, str(script), "--self-test", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["window_opened"] and report["project_reopened"] and report["mock_verified"]
    assert report["frozen"] is False
    assert report["discovery_verified"]
    assert report["protection_verified"]
    assert report["translation_manager_verified"]
    assert report["packed_extraction_verified"] and report["packed_cleanup_verified"]


def test_cli_scan_uses_shared_import_service_and_real_template_ids(tmp_path, project):
    game = Path(__file__).resolve().parents[1] / "fixtures/game_with_tl"
    result = run_cli(tmp_path, "scan", "--game", str(game), "--project", str(project.path))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["units"]) == 8
    assert any(unit["renpy_identifier"] == "start_1b4a9f2d" for unit in report["units"])
    assert len(report["protection"]) == 8
