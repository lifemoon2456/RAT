import stat
from pathlib import Path, PurePosixPath, PureWindowsPath


class ScanError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def is_link(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
    )


def safe_relative(value: str) -> str:
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if not value or path.is_absolute() or windows.drive or ".." in path.parts or ":" in value:
        raise ScanError("unsafe_reference_path")
    if value == ".":
        raise ScanError("unsafe_reference_path")
    return path.as_posix()


def read_source_bytes(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> bytes:
    if is_link(path) or path.stat().st_size > max_bytes:
        raise ScanError("unsafe_or_large_source")
    with path.open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ScanError("unsafe_or_large_source")
    return data


def read_source(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> str:
    data = read_source_bytes(path, max_bytes=max_bytes)
    try:
        return data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ScanError("unsupported_encoding") from error
