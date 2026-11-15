"""Collect installed notices verbatim and local Qt license texts for the EXE."""

import sys
from importlib.metadata import distributions
from pathlib import Path


def collect(destination: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    sections = [
        "RAT — Third-party notices\n\n"
        "This inventory describes the build environment; not all listed modules are bundled.\n"
        "Libraries retain their original licenses. No library source was modified.\n\n"
        "Qt/PySide6: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only.\n"
        "Only the Qt Core/Gui/Widgets desktop modules and supporting plugins are used.\n"
        "Matching library source and build instructions:\n"
        "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/\n"
        "https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/\n"
        "https://doc.qt.io/qtforpython-6/building_from_source/index.html\n"
        "https://code.qt.io/cgit/qt/qtbase.git/tree/src/3rdparty?h=v6.12.0\n"
        "The Qt libraries are dynamically loaded DLLs, unpacked to the temporary _MEI directory.\n"
        "You may inspect and replace these libraries for debugging your modifications.\n"
        "The repository includes application sources and the build scripts.\n"
    ]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    sections.append("\n=== Python ===\n" + python_license.read_text(encoding="utf-8"))
    for package in sorted(distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = package.metadata["Name"]
        license_id = package.metadata.get("License-Expression") or package.metadata.get(
            "License", ""
        )
        sections.append(f"\n=== {name} {package.version} ===\nLicense: {license_id}\n")
        for file in sorted(package.files or [], key=str):
            normalized = str(file).replace("\\", "/")
            if ".dist-info/" in normalized and (
                "/licenses/" in normalized
                or file.name.lower().startswith(("license", "notice", "copying"))
            ):
                path = package.locate_file(file)
                if path.is_file():
                    sections.append(f"\n--- {file.name} ---\n" + path.read_text(encoding="utf-8"))
    for path in sorted((root / "assets" / "licenses").glob("*.txt")):
        sections.append(f"\n=== {path.name} ===\n" + path.read_text(encoding="utf-8"))
    for path in sorted((root / "src/rat/resources/fonts").rglob("*.txt")):
        sections.append(
            f"\n=== Bundled font: {path.parent.name} ===\n" + path.read_text(encoding="utf-8")
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(sections), encoding="utf-8")


if __name__ == "__main__":
    collect(Path(sys.argv[1]))
