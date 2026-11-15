"""Original small synthetic archives; no commercial game content."""

import pickle
import zlib


def write_rpa(path, files, *, version=3, protocol=2, prefix=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    header_size = 34 if version == 3 else 25
    data = bytearray(b" " * header_size)
    index, key = {}, 0x1234ABCD if version == 3 else 0
    for name, payload in files.items():
        start = payload[:2] if prefix else b""
        payload = payload[len(start) :]
        offset = len(data)
        data.extend(payload)
        index[name] = (
            [(offset ^ key, len(payload) ^ key, start)]
            if prefix
            else [(offset ^ key, len(payload) ^ key)]
        )
    offset = len(data)
    data.extend(zlib.compress(pickle.dumps(index, protocol=protocol)))
    header = f"RPA-3.0 {offset:016x} {key:08x}\n" if version == 3 else f"RPA-2.0 {offset:016x}\n"
    assert len(header) == header_size
    data[:header_size] = header.encode()
    path.write_bytes(data)
    return path


def fingerprints(root):
    import hashlib

    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
