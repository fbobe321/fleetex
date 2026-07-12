from __future__ import annotations

import hashlib
import os

import pytest

from fleetex_filestore.errors import NotFoundError, NotImplementedFsError, WriteError
from fleetex_filestore.persistor import FSPersistor


async def aiter_bytes(data: bytes, chunk: int = 4):
    for i in range(0, len(data), chunk):
        yield data[i : i + chunk]


@pytest.fixture
def loc(tmp_path):
    return str(tmp_path / "bucket")


async def test_write_then_read_flattened(loc):
    p = FSPersistor()
    await p.send_stream(loc, "a/b/c.txt", aiter_bytes(b"hello"))
    # flattened: slashes -> underscores
    assert os.path.isfile(os.path.join(loc, "a_b_c.txt"))
    assert p.read_object(loc, "a/b/c.txt") == b"hello"
    assert p.get_object_size(loc, "a/b/c.txt") == 5


async def test_subdirectories_preserve_paths(loc):
    p = FSPersistor()
    await p.send_stream(loc, "ab/cd/ef", aiter_bytes(b"blob"), use_subdirectories=True)
    assert os.path.isfile(os.path.join(loc, "ab", "cd", "ef"))
    assert p.read_object(loc, "ab/cd/ef", use_subdirectories=True) == b"blob"


async def test_range_read_inclusive(loc):
    p = FSPersistor()
    await p.send_stream(loc, "f", aiter_bytes(b"0123456789"))
    assert b"".join(p.get_object_stream(loc, "f", 2, 5)) == b"2345"  # inclusive
    assert b"".join(p.get_object_stream(loc, "f", 7, None)) == b"789"  # to EOF
    assert b"".join(p.get_object_stream(loc, "f", None, None)) == b"0123456789"


async def test_missing_raises_not_found(loc):
    p = FSPersistor()
    with pytest.raises(NotFoundError):
        p.get_object_size(loc, "nope")
    with pytest.raises(NotFoundError):
        list(p.get_object_stream(loc, "nope"))


async def test_md5_and_mismatch(loc):
    p = FSPersistor()
    await p.send_stream(loc, "f", aiter_bytes(b"data"), source_md5=hashlib.md5(b"data").hexdigest())
    assert p.get_object_md5(loc, "f") == hashlib.md5(b"data").hexdigest()
    with pytest.raises(WriteError):
        await p.send_stream(loc, "g", aiter_bytes(b"data"), source_md5="deadbeef")
    assert not p.check_if_object_exists(loc, "g")  # temp cleaned up, nothing written


async def test_if_none_match_star_not_implemented(loc):
    p = FSPersistor()
    with pytest.raises(NotImplementedFsError):
        await p.send_stream(loc, "f", aiter_bytes(b"x"), if_none_match="*")


async def test_delete_is_idempotent(loc):
    p = FSPersistor()
    await p.send_stream(loc, "f", aiter_bytes(b"x"))
    p.delete_object(loc, "f")
    p.delete_object(loc, "f")  # no error when missing
    assert not p.check_if_object_exists(loc, "f")


async def test_copy_object(loc):
    p = FSPersistor()
    await p.send_stream(loc, "src", aiter_bytes(b"copyme"))
    p.copy_object(loc, "src", "dst")
    assert p.read_object(loc, "dst") == b"copyme"


async def test_delete_directory_flattened_glob(loc):
    p = FSPersistor()
    await p.send_stream(loc, "pre/a", aiter_bytes(b"1"))
    await p.send_stream(loc, "pre/b", aiter_bytes(b"2"))
    p.delete_directory(loc, "pre")  # removes pre_* flattened files
    assert not p.check_if_object_exists(loc, "pre/a")
    assert not p.check_if_object_exists(loc, "pre/b")
