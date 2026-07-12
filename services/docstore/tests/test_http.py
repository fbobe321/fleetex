from __future__ import annotations

from bson import ObjectId

from fleetex_service_kit.contract import call_asgi

PID = "5f9f1b0b0b0b0b0b0b0b0b0b"
DID = "600000000000000000000001"


async def _create(app, lines=("a", "b"), version=1, ranges=None):
    return await call_asgi(
        app, "POST", f"/project/{PID}/doc/{DID}",
        json={"lines": list(lines), "version": version, "ranges": ranges or {}},
    )


async def test_status(app):
    r = await call_asgi(app, "GET", "/status")
    assert r.status == 200 and r.text == "docstore is alive"


async def test_update_then_get(app):
    up = await _create(app, ["hello", "world"], 3)
    assert up.status == 200 and up.json == {"modified": True, "rev": 1}
    g = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}")
    assert g.status == 200
    assert g.json["_id"] == DID
    assert g.json["lines"] == ["hello", "world"]
    assert g.json["rev"] == 1 and g.json["version"] == 3
    assert "deleted" not in g.json  # null fields omitted


async def test_get_missing_404(app):
    r = await call_asgi(app, "GET", f"/project/{PID}/doc/{ObjectId()}")
    assert r.status == 404


async def test_raw_doc_plain_text(app):
    await _create(app, ["l1", "l2"])
    r = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}/raw")
    assert r.status == 200 and r.text == "l1\nl2"


async def test_update_validation(app):
    bad_lines = await call_asgi(app, "POST", f"/project/{PID}/doc/{DID}", json={"lines": "notarray", "version": 1, "ranges": {}})
    assert bad_lines.status == 400
    no_ranges = await call_asgi(app, "POST", f"/project/{PID}/doc/{DID}", json={"lines": ["a"], "version": 1})
    assert no_ranges.status == 400
    too_big = await call_asgi(app, "POST", f"/project/{PID}/doc/{DID}", json={"lines": ["a" * (2 * 1024 * 1024 + 1)], "version": 1, "ranges": {}})
    assert too_big.status == 413 and too_big.text == "document body too large"


async def test_invalid_id_is_500(app):
    r = await call_asgi(app, "GET", "/project/not-hex/doc/also-bad")
    assert r.status == 500


async def test_patch_soft_delete_flow(app):
    await _create(app)
    d0 = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}/deleted")
    assert d0.json == {"deleted": False}
    patch = await call_asgi(app, "PATCH", f"/project/{PID}/doc/{DID}", json={"deleted": True, "name": "main.tex"})
    assert patch.status == 204
    d1 = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}/deleted")
    assert d1.json == {"deleted": True}
    # get without include_deleted -> 404; with -> 200
    assert (await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}")).status == 404
    inc = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}?include_deleted=true")
    assert inc.status == 200 and inc.json["deleted"] is True


async def test_patch_rejects_extra_keys(app):
    await _create(app)
    r = await call_asgi(app, "PATCH", f"/project/{PID}/doc/{DID}", json={"deleted": True, "bogus": 1})
    assert r.status == 400


async def test_get_all_docs_and_deleted(app):
    await _create(app)
    alld = await call_asgi(app, "GET", f"/project/{PID}/doc")
    assert alld.status == 200 and len(alld.json) == 1 and alld.json[0]["lines"] == ["a", "b"]
    await call_asgi(app, "PATCH", f"/project/{PID}/doc/{DID}", json={"deleted": True, "name": "gone.tex"})
    deleted = await call_asgi(app, "GET", f"/project/{PID}/doc-deleted")
    assert deleted.status == 200 and deleted.json[0]["name"] == "gone.tex"


async def test_delete_is_deprecated_500(app):
    r = await call_asgi(app, "DELETE", f"/project/{PID}/doc/{DID}")
    assert r.status == 500 and "DEPRECATED" in r.text


async def test_archive_peek_and_destroy(app):
    await _create(app, ["archived"])
    arch = await call_asgi(app, "POST", f"/project/{PID}/doc/{DID}/archive")
    assert arch.status == 204
    peek = await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}/peek")
    assert peek.status == 200 and peek.headers.get("x-doc-status") == "archived"
    assert peek.json["lines"] == ["archived"]
    unarch = await call_asgi(app, "POST", f"/project/{PID}/unarchive")
    assert unarch.status == 200  # 200, not 204
    d = await call_asgi(app, "POST", f"/project/{PID}/destroy")
    assert d.status == 204
    assert (await call_asgi(app, "GET", f"/project/{PID}/doc/{DID}")).status == 404


async def test_has_ranges_and_thread_ids(app):
    thread = str(ObjectId())
    ranges = {"comments": [{"op": {"t": thread, "c": "x", "p": 0}}]}
    await _create(app, ["c"], 1, ranges)
    hr = await call_asgi(app, "GET", f"/project/{PID}/has-ranges")
    assert hr.json == {"projectHasRanges": True}
    tids = await call_asgi(app, "GET", f"/project/{PID}/comment-thread-ids")
    assert tids.json == {DID: [thread]}
