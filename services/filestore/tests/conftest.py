from __future__ import annotations

import os

import pytest

from fleetex_filestore.app import build_app
from fleetex_filestore.config import FilestoreConfig


@pytest.fixture
def config(tmp_path, monkeypatch):
    # Run inside tmp so the generic bucket route's relative dirs stay contained.
    monkeypatch.chdir(tmp_path)
    return FilestoreConfig.from_env(env={}, base_path=str(tmp_path / "data"))


@pytest.fixture
def app(config):
    return build_app(config)


async def aiter_bytes(data: bytes, chunk: int = 4):
    for i in range(0, len(data), chunk):
        yield data[i : i + chunk]
