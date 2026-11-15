"""Package only an EXE whose isolated smoke result matches its bytes and version."""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import zipfile
from pathlib import Path

from rat import __version__


def prepare(root: Path, compiler: Path | None = None):
    executable = root / "dist/RAT.exe"
    smoke = json.loads((root / ".local/phase7/windows-smoke.json").read_text(encoding="utf-8"))
    checksum = hashlib.sha256(executable.read_bytes()).hexdigest()
    if (
        smoke["sha256"] != checksum
        or smoke["exit_code"] != 0
        or smoke["result"].get("application_version") != __version__
        or smoke["result"].get("status") != "passed"
    ):
        raise ValueError("EXE must pass current-version isolated smoke before release packaging")
    folder = root / "dist" / f"release-{__version__}"
    folder.mkdir(exist_ok=True)
    stem = f"RAT-{__version__}-windows-x64"
    shutil.copy2(executable, folder / (stem + ".exe"))
    with zipfile.ZipFile(folder / (stem + "-portable.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, "RAT.exe")
        archive.write(root / "build/licenses/THIRD_PARTY_NOTICES.txt", "THIRD_PARTY_NOTICES.txt")
        archive.write(root / "docs/installation.md", "INSTALLATION.md")
        archive.write(root / "RELEASE_NOTICE.txt", "RELEASE_NOTICE.txt")
    artifacts = [folder / (stem + ".exe"), folder / (stem + "-portable.zip")]
    if compiler:
        subprocess.run(
            [
                str(compiler.resolve()),
                f"/DAppVersion={__version__}",
                str(root / "scripts/installer.iss"),
            ],
            cwd=root,
            check=True,
        )
        installer = root / "dist" / (stem + "-setup.exe")
        shutil.copy2(installer, folder / installer.name)
        artifacts.append(folder / installer.name)
    manifest = {
        "version": __version__,
        "channel": "beta",
        "python": platform.python_version(),
        "signed": False,
        "installer_built": compiler is not None,
        "clean_windows_vm_tested": False,
        "artifacts": {
            path.name: {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in artifacts
        },
    }
    (folder / "release-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (folder / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {name}" for name, item in manifest["artifacts"].items())
        + "\n",
        encoding="utf-8",
    )
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, help="Path to Inno Setup ISCC.exe")
    args = parser.parse_args()
    print(prepare(Path(__file__).resolve().parents[1], args.compiler))
