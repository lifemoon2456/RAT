from pathlib import Path
import tomllib
from PyInstaller.utils.hooks import collect_submodules, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)

root = Path(SPECPATH).parent
release_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
numeric_version = tuple(int(n) for n in release_version.split("b")[0].split(".")) + (0,)
metadata = []
for package in ("PySide6", "SQLAlchemy", "pydantic", "keyring", "openai", "google-genai"):
    metadata += copy_metadata(package)
analysis = Analysis(
    [str(root / "scripts" / "rat_desktop.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "build" / "licenses" / "THIRD_PARTY_NOTICES.txt"), "rat/resources"),
           (str(root / "src" / "rat" / "resources" / "fonts"), "rat/resources/fonts"),
           (str(root / "src" / "rat" / "resources" / "arabic_demo"), "rat/resources/arabic_demo")] + metadata,
    hiddenimports=["sqlalchemy.dialects.sqlite.pysqlite", "keyring.backends.Windows",
                   "win32ctypes.pywin32.win32cred", "win32ctypes.pywin32.pywintypes"]
                   + collect_submodules("fontTools.ttLib.tables"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytestqt", "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="RAT",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeric_version, prodvers=numeric_version,
                         mask=0x3f, flags=0x2, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "Ren'Py Arabic Translator Beta"),
            StringStruct("FileVersion", release_version),
            StringStruct("ProductName", "Ren'Py Arabic Translator"),
            StringStruct("ProductVersion", release_version),
            StringStruct("OriginalFilename", "RAT.exe"),
        ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
    ),
)
