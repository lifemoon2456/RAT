import pickle
import struct
import zlib

import pytest

from rat.extraction.rpyc_adapter import SafeRpycDecompiler
from rat.security.pickle_data import Record, Symbol


def test_rpyc_executable_pickle_is_rejected_without_running_code(tmp_path):
    marker = tmp_path / "MUST_NOT_EXIST"

    class Payload:
        def __reduce__(self):
            return eval, (f"__import__('pathlib').Path({str(marker)!r}).touch()",)

    compressed = zlib.compress(pickle.dumps(Payload()))
    data = b"RENPY RPC2" + struct.pack("<III", 1, 34, len(compressed)) + bytes(12) + compressed
    with pytest.raises(ValueError, match="unsafe_pickle_global"):
        SafeRpycDecompiler().decompile(data)
    assert not marker.exists()


def test_shared_ast_references_cannot_expand_output_without_bound(monkeypatch):
    say = Record(Symbol("renpy.ast", "Say"), values={"what": "x" * 40000})
    root = ({}, [say] * 200)
    monkeypatch.setattr("rat.extraction.rpyc_adapter.rpyc_slots", lambda _data: {1: root})
    with pytest.raises(ValueError, match="decompiled_source_size_limit"):
        SafeRpycDecompiler().decompile(b"synthetic graph")
