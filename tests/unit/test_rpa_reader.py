import time

import pytest
from packed_support import write_rpa

from rat.domain.packed import PackedLimits
from rat.extraction.rpa_adapter import RpaAdapter, member_path


@pytest.mark.parametrize("version,protocol,prefix", [(2, 2, False), (3, 2, True), (3, 5, False)])
def test_rpa_formats_prefixes_unicode_and_nested_paths(tmp_path, version, protocol, prefix):
    files = {
        "script.rpy": b'label start:\n    "Original RAT sample"\n',
        "sub/عربي.rpy": 'label other:\n    "مرحبًا"\n'.encode(),
    }
    path = write_rpa(
        tmp_path / "fixture.rpa", files, version=version, protocol=protocol, prefix=prefix
    )
    adapter = RpaAdapter()
    index = adapter.inspect(path, PackedLimits())
    assert index.format == f"{version}.0"
    for member in index.members:
        assert (
            b"".join(adapter.chunks(path, index, member, deadline=time.monotonic() + 10))
            == files[member.original_path]
        )


@pytest.mark.parametrize(
    "path",
    [
        "../evil.rpy",
        "/absolute.rpy",
        "C:/evil.rpy",
        "..\\evil.rpy",
        "a/../../evil.rpy",
        "CON.rpy",
        "aux .rpy",
        "dir./a.rpy",
        "a.rpy:stream",
        "bad\x00.rpy",
        "a?.rpy",
        "a|b.rpy",
    ],
)
def test_unsafe_member_paths_are_rejected(path):
    with pytest.raises(ValueError):
        member_path(path)


def test_unknown_archive_version_and_out_of_bounds_data_are_rejected(tmp_path):
    path = tmp_path / "bad.rpa"
    path.write_bytes(b"RPA-4.0 0000000000000000 00000000\n")
    with pytest.raises(ValueError, match="unsupported_rpa"):
        RpaAdapter().inspect(path, PackedLimits())
    path.write_bytes(b"RPA-3.0 ffffffffffffffff 00000000\n")
    with pytest.raises(ValueError, match="invalid_rpa_index"):
        RpaAdapter().inspect(path, PackedLimits())
