"""Kit tests — all run without a live Mongo/Redis (clients are lazy)."""

from __future__ import annotations

import json
import logging

import pytest

from fleetex_service_kit import Settings, create_app
from fleetex_service_kit.contract import Response, assert_match, call_asgi, diff, normalize
from fleetex_service_kit.db import create_mongo_client, database_name_from_url, get_database
from fleetex_service_kit.logging import JsonFormatter


# --- config -------------------------------------------------------------- #
def test_settings_defaults():
    s = Settings.from_env("notifications", default_port=3042, env={})
    assert s.service_name == "notifications"
    assert s.port == 3042
    assert s.mongo_url == "mongodb://mongo/sharelatex"
    assert s.redis_url == "redis://redis:6379"


def test_settings_reads_overleaf_env():
    env = {
        "OVERLEAF_MONGO_URL": "mongodb://db/mydb",
        "REDIS_HOST": "cache",
        "REDIS_PORT": "6380",
        "PORT": "9000",
    }
    s = Settings.from_env("chat", env=env)
    assert s.mongo_url == "mongodb://db/mydb"
    assert s.redis_url == "redis://cache:6380"
    assert s.port == 9000


def test_settings_explicit_urls_win():
    env = {"REDIS_URL": "redis://explicit:1234", "MONGO_URL": "mongodb://x/y"}
    s = Settings.from_env("x", env=env)
    assert s.redis_url == "redis://explicit:1234"
    assert s.mongo_url == "mongodb://x/y"


# --- db factories (lazy, no server needed) ------------------------------- #
def test_database_name_parsing():
    assert database_name_from_url("mongodb://mongo/sharelatex") == "sharelatex"
    assert database_name_from_url("mongodb://mongo") == "sharelatex"  # default
    assert database_name_from_url("mongodb://h:27017/custom") == "custom"


def test_get_database_uses_parsed_name():
    client = create_mongo_client("mongodb://mongo/sharelatex")
    db = get_database(client, "mongodb://mongo/sharelatex")
    assert db.name == "sharelatex"
    client.close()


# --- logging ------------------------------------------------------------- #
def test_json_formatter_emits_valid_json():
    rec = logging.makeLogRecord({"msg": "hello", "levelname": "INFO"})
    line = JsonFormatter("notifications").format(rec)
    parsed = json.loads(line)
    assert parsed["msg"] == "hello"
    assert parsed["level"] == "info"
    assert parsed["name"] == "notifications"
    assert "time" in parsed


def test_json_formatter_includes_extras():
    rec = logging.makeLogRecord({"msg": "m", "levelname": "INFO", "port": 3042})
    parsed = json.loads(JsonFormatter("s").format(rec))
    assert parsed["port"] == 3042


# --- app factory (mongo/redis disabled) ---------------------------------- #
async def test_health_and_status_endpoints():
    app = create_app(Settings.from_env("demo", env={}), connect_mongo=False, connect_redis=False)
    health = await call_asgi(app, "GET", "/health")
    assert health.status == 200
    assert health.json == {"status": "ok", "service": "demo"}
    status = await call_asgi(app, "GET", "/status")
    assert status.status == 200
    assert "demo is alive" in status.text


# --- contract harness ---------------------------------------------------- #
def test_normalize_drops_ignored_paths():
    obj = {"id": 1, "name": "a", "meta": {"createdAt": "t", "keep": 2}}
    out = normalize(obj, ignore={"id", "meta.createdAt"})
    assert out == {"name": "a", "meta": {"keep": 2}}


def test_normalize_ignores_list_element_fields():
    obj = [{"id": "x", "v": 1}, {"id": "y", "v": 2}]
    out = normalize(obj, ignore={"[*].id"})
    assert out == [{"v": 1}, {"v": 2}]


def test_diff_matches_when_only_ignored_fields_differ():
    py = Response(status=200, json=[{"id": "aaa", "text": "hi"}])
    node = Response(status=200, json=[{"id": "bbb", "text": "hi"}])
    assert diff(py, node, ignore={"[*].id"}) == []
    assert_match(py, node, ignore={"[*].id"})


def test_diff_flags_status_and_body_mismatch():
    py = Response(status=500, json={"a": 1})
    node = Response(status=200, json={"a": 2})
    problems = diff(py, node)
    assert any("status" in p for p in problems)
    assert any("body" in p for p in problems)
    with pytest.raises(AssertionError):
        assert_match(py, node)
