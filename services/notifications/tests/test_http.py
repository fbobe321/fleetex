"""HTTP-surface tests: routes, status codes, and JSON shapes via call_asgi.

Also demonstrates the contract harness: when FLEETEX_NODE_BASE is set, the same
requests are diffed against the live Node original.
"""

from __future__ import annotations

import os

import pytest
from bson import ObjectId

from fleetex_service_kit.contract import assert_match, call_asgi, call_http

VALID_UID = "5f9f1b0b0b0b0b0b0b0b0b0b"


async def test_status_matches_node_text(app):
    r = await call_asgi(app, "GET", "/status")
    assert r.status == 200
    assert r.text == "notifications is up"


async def test_add_and_list(app):
    add = await call_asgi(
        app, "POST", f"/user/{VALID_UID}",
        json={"key": "k1", "templateKey": "welcome", "messageOpts": {"n": 1}},
    )
    assert add.status == 200
    assert add.text == ""  # sendStatus(200), empty body

    lst = await call_asgi(app, "GET", f"/user/{VALID_UID}")
    assert lst.status == 200
    assert isinstance(lst.json, list) and len(lst.json) == 1
    item = lst.json[0]
    assert item["key"] == "k1"
    assert item["templateKey"] == "welcome"
    assert item["messageOpts"] == {"n": 1}
    # ObjectId fields are serialized as 24-hex strings (matching Express).
    assert item["user_id"] == VALID_UID
    assert isinstance(item["_id"], str) and len(item["_id"]) == 24


async def test_empty_list_is_empty_array(app):
    r = await call_asgi(app, "GET", f"/user/{VALID_UID}")
    assert r.status == 200
    assert r.json == []


async def test_bad_object_id_is_404(app):
    r = await call_asgi(app, "GET", "/user/not-an-object-id")
    assert r.status == 404


async def test_delete_by_key_requires_key_400(app):
    r = await call_asgi(app, "DELETE", f"/user/{VALID_UID}", json={})
    assert r.status == 400


async def test_mark_read_by_id(app):
    await call_asgi(app, "POST", f"/user/{VALID_UID}", json={"key": "k", "templateKey": "t"})
    listed = await call_asgi(app, "GET", f"/user/{VALID_UID}")
    nid = listed.json[0]["_id"]
    d = await call_asgi(app, "DELETE", f"/user/{VALID_UID}/notification/{nid}")
    assert d.status == 200
    assert (await call_asgi(app, "GET", f"/user/{VALID_UID}")).json == []


async def test_key_count_and_bulk(app):
    u1, u2 = ObjectId(), ObjectId()
    for u in (u1, u2):
        await call_asgi(app, "POST", f"/user/{u}", json={"key": "promo", "templateKey": "t"})
    c = await call_asgi(app, "GET", "/key/promo/count")
    assert c.status == 200 and c.json == {"count": 2}
    b = await call_asgi(app, "DELETE", "/key/promo/bulk")
    assert b.status == 200 and b.json == {"count": 2}
    assert (await call_asgi(app, "GET", "/key/promo/count")).json == {"count": 0}


async def test_unknown_get_is_404(app):
    r = await call_asgi(app, "GET", "/no/such/route")
    assert r.status == 404


async def test_dedup_via_http(app):
    for tk in ("first", "second"):
        await call_asgi(app, "POST", f"/user/{VALID_UID}", json={"key": "dup", "templateKey": tk})
    listed = await call_asgi(app, "GET", f"/user/{VALID_UID}")
    assert len(listed.json) == 1
    assert listed.json[0]["templateKey"] == "first"  # second was a no-op


# --- optional: diff against the live Node service --------------------------- #
NODE_BASE = os.environ.get("FLEETEX_NODE_BASE")


@pytest.mark.skipif(not NODE_BASE, reason="set FLEETEX_NODE_BASE to diff vs Node")
async def test_contract_vs_node(app):
    uid = str(ObjectId())
    payload = {"key": "ct", "templateKey": "ct-template", "messageOpts": {"a": 1}}
    await call_asgi(app, "POST", f"/user/{uid}", json=payload)
    await call_http(NODE_BASE, "POST", f"/user/{uid}", json=payload)

    py = await call_asgi(app, "GET", f"/user/{uid}")
    node = await call_http(NODE_BASE, "GET", f"/user/{uid}")
    # _id is server-generated and volatile; everything else must match.
    assert_match(py, node, ignore={"[*]._id"})
