"""Read standard RPA2/RPA3 data without unpickling Python objects."""

import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rat.domain.packed import PackedLimits
from rat.exporters.safe_io import relative_export_path
from rat.security.pickle_data import PickleDataReader, inflate
from rat.security.safe_paths import is_link


def member_path(name: str) -> str:
    if not isinstance(name, str) or len(name) > 1024 or any(c in name for c in '<>"|?*'):
        raise ValueError("unsafe_archive_path")
    path = relative_export_path(unicodedata.normalize("NFC", name))
    if any(
        part.split(".")[0].rstrip(" .").upper()
        in {
            "CON",
            "NUL",
            "AUX",
            "PRN",
            *{f"COM{i}" for i in range(1, 10)},
            *{f"LPT{i}" for i in range(1, 10)},
        }
        for part in Path(path).parts
    ):
        raise ValueError("unsafe_archive_path")
    return path


@dataclass(frozen=True)
class RpaMember:
    original_path: str
    chunks: tuple[tuple[int, int, bytes], ...]
    size: int


@dataclass(frozen=True)
class RpaIndex:
    format: str
    index_offset: int
    members: tuple[RpaMember, ...]
    signature: tuple[int, int]


class RpaAdapter:
    adapter_id = "rat-rpa-data-v1"

    def inspect(self, path: Path, limits: PackedLimits) -> RpaIndex:
        if is_link(path):
            raise ValueError("archive_link_rejected")
        stat = path.stat()
        with path.open("rb") as source:
            header = source.readline(128)
            match = re.fullmatch(
                rb"RPA-(2\.0|3\.0) ([0-9a-fA-F]{16})(?: ([0-9a-fA-F]{8}))?\n", header
            )
            if not match or (match[1] == b"3.0") != (match[3] is not None):
                raise ValueError("unsupported_rpa_format")
            offset = int(match[2], 16)
            key = int(match[3], 16) if match[3] else 0
            if (
                not len(header) <= offset < stat.st_size
                or stat.st_size - offset > limits.max_index_bytes
            ):
                raise ValueError("invalid_rpa_index_offset_or_size")
            source.seek(offset)
            index = PickleDataReader().read(
                inflate(source.read(limits.max_index_bytes + 1), limit=limits.max_index_bytes)
            )
        if type(index) is not dict or len(index) > limits.max_members:
            raise ValueError("invalid_rpa_index_or_member_limit")
        members = []
        for name, chunks in index.items():
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            if (
                type(name) is not str
                or type(chunks) is not list
                or not chunks
                or len(chunks) > 1024
            ):
                raise ValueError("invalid_rpa_member")
            # Unsafe filenames remain reportable per member; never used to open an output.
            pieces, size = [], 0
            for chunk in chunks:
                if type(chunk) is not tuple or len(chunk) not in {2, 3}:
                    raise ValueError("invalid_rpa_chunk")
                start, length = chunk[:2]
                prefix = chunk[2] if len(chunk) == 3 else b""
                if type(prefix) is str:
                    prefix = prefix.encode("latin1")
                if type(start) is not int or type(length) is not int or type(prefix) is not bytes:
                    raise ValueError("invalid_rpa_chunk_type")
                start, length = start ^ key, length ^ key
                if start < len(header) or length < 0 or start + length > offset:
                    raise ValueError("rpa_chunk_out_of_bounds")
                size += len(prefix) + length
                pieces.append((start, length, prefix))
            members.append(RpaMember(name, tuple(pieces), size))
        return RpaIndex(match[1].decode(), offset, tuple(members), (stat.st_size, stat.st_mtime_ns))

    def chunks(self, path: Path, index: RpaIndex, member: RpaMember, *, deadline: float):
        if is_link(path) or (path.stat().st_size, path.stat().st_mtime_ns) != index.signature:
            raise ValueError("archive_changed_during_extraction")
        with path.open("rb") as source:
            for offset, length, prefix in member.chunks:
                if prefix:
                    yield prefix
                source.seek(offset)
                while length:
                    if time.monotonic() > deadline:
                        raise ValueError("packed_extraction_time_limit")
                    block = source.read(min(length, 1024 * 1024))
                    if not block:
                        raise ValueError("truncated_rpa_member")
                    length -= len(block)
                    yield block
        if (path.stat().st_size, path.stat().st_mtime_ns) != index.signature:
            raise ValueError("archive_changed_during_extraction")
