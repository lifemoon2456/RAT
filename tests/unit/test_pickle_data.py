import pickle
import zlib

import pytest

from rat.security.pickle_data import PickleDataReader, inflate


@pytest.mark.parametrize("protocol", [0, 1, 2, 3, 4, 5])
def test_primitive_pickle_is_interpreted_as_data(protocol):
    value = {"script.rpy": [(100, 9, b"xx")], "unicode/عربي.rpy": [(200, 0, b"")]}
    assert PickleDataReader().read(pickle.dumps(value, protocol=protocol)) == value


@pytest.mark.parametrize("records", [False, True])
def test_executable_reducers_are_rejected_without_creating_a_file(tmp_path, records):
    marker = tmp_path / "MUST_NOT_EXIST"

    class Payload:
        def __reduce__(self):
            return eval, (f"__import__('pathlib').Path({str(marker)!r}).write_text('bad')",)

    with pytest.raises(ValueError, match="unsafe_pickle"):
        PickleDataReader(records=records).read(pickle.dumps(Payload()))
    assert not marker.exists()


def test_pickle_memo_resource_and_compression_limits():
    with pytest.raises(ValueError, match="resource_limit"):
        PickleDataReader(max_ops=5).read(pickle.dumps(list(range(100))))
    with pytest.raises(ValueError, match="compressed_data_limit"):
        inflate(zlib.compress(b"x" * 10000), limit=100)
    with pytest.raises(ValueError, match="invalid_pickle_end"):
        PickleDataReader().read(pickle.dumps({}) + b"trailing")
    with pytest.raises(ValueError, match="container_resource_limit"):
        PickleDataReader(max_items=10).read(pickle.dumps(list(range(20))))


@pytest.mark.parametrize("records", [False, True])
def test_aliases_cannot_force_exponential_hash_work_in_one_opcode(records):
    key = ("x",)
    for _ in range(30):
        key = (key, key)
    encoded = pickle.dumps(key, protocol=2)
    # Build a dict only in the data interpreter: Python must not hash this fixture key.
    payload = b"\x80\x02}" + encoded[2:-1] + b"K\x01s."
    with pytest.raises(ValueError, match="pickle_hash_resource_limit"):
        PickleDataReader(records=records).read(payload)
