from __future__ import annotations

import pytest
from bson import ObjectId
from fakeredis import FakeAsyncRedis
from mongomock_motor import AsyncMongoMockClient

from fleetex_web.app import build_app
from fleetex_web.config import WebConfig


@pytest.fixture
def db():
    return AsyncMongoMockClient()["sharelatex"]


@pytest.fixture
def redis():
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def config():
    # low bcrypt rounds keep tests fast
    return WebConfig(session_secrets=["test-secret", "old-secret"], bcrypt_rounds=4)


@pytest.fixture
def app(config, db, redis):
    return build_app(config, db=db, redis=redis)


def cookie_header(config, store, sid: str) -> dict:
    return {"cookie": f"{config.cookie_name}={store.sign_cookie(sid)}"}


def parse_set_cookie(config, set_cookie: str) -> str:
    # extract the value of overleaf.sid=... up to the first ';'
    prefix = f"{config.cookie_name}="
    part = set_cookie.split(";")[0]
    assert part.startswith(prefix)
    return part[len(prefix):]
