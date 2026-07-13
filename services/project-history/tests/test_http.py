"""HTTP surface of project-history."""

from __future__ import annotations

from fleetex_service_kit.contract import call_asgi


async def _record(app, pid, doc, content, **extra):
    return await call_asgi(app, "POST", f"/project/{pid}/doc/{doc}/version", json={"content": content, **extra})


async def test_record_and_dedup_status_codes(app):
    r1 = await _record(app, "p1", "d1", "hello", pathname="main.tex", user_id="u1")
    assert r1.status == 201 and r1.json["created"] is True
    r2 = await _record(app, "p1", "d1", "hello")  # identical -> not created
    assert r2.status == 200 and r2.json["created"] is False


async def test_record_requires_content(app):
    r = await call_asgi(app, "POST", "/project/p1/doc/d1/version", json={"pathname": "x"})
    assert r.status == 400


async def test_project_timeline(app):
    await _record(app, "p1", "d1", "a")
    await _record(app, "p1", "d2", "b")
    await _record(app, "p1", "d1", "a2")
    r = await call_asgi(app, "GET", "/project/p1/versions")
    versions = r.json["versions"]
    assert [v["version"] for v in versions] == [3, 2, 1]
    assert versions[0]["doc_id"] == "d1"


async def test_get_full_version(app):
    await _record(app, "p1", "d1", "the content", pathname="main.tex")
    r = await call_asgi(app, "GET", "/project/p1/version/1")
    assert r.status == 200 and r.json["content"] == "the content"
    missing = await call_asgi(app, "GET", "/project/p1/version/99")
    assert missing.status == 404


async def test_diff_between_versions(app):
    await _record(app, "p1", "d1", "The quick brown fox")
    await _record(app, "p1", "d1", "The quick red fox")
    r = await call_asgi(app, "GET", "/project/p1/doc/d1/diff?from=1&to=2")
    body = r.json
    assert body["from"] == 1 and body["to"] == 2
    # reconstruct old/new from the segment diff
    old = "".join(s.get("u", "") + s.get("d", "") for s in body["diff"])
    new = "".join(s.get("u", "") + s.get("i", "") for s in body["diff"])
    assert old == "The quick brown fox" and new == "The quick red fox"
    assert body["stats"]["added"] > 0 and body["stats"]["removed"] > 0


async def test_diff_defaults_to_latest_pair(app):
    await _record(app, "p1", "d1", "one")
    await _record(app, "p1", "d1", "one two")
    r = await call_asgi(app, "GET", "/project/p1/doc/d1/diff")  # no from/to
    assert r.json["to"] == 2 and r.json["from"] == 1


async def test_diff_missing_doc_is_404(app):
    r = await call_asgi(app, "GET", "/project/p1/doc/nope/diff")
    assert r.status == 404


async def test_diff_against_current_buffer(app):
    await _record(app, "p1", "d1", "Hello world")
    # compare stored v1 against an arbitrary "current buffer"
    r = await call_asgi(app, "POST", "/project/p1/doc/d1/diff-against/1", json={"content": "Hello brave world"})
    assert r.status == 200
    body = r.json
    assert body["from"] == 1 and body["to"] == "current"
    old = "".join(s.get("u", "") + s.get("d", "") for s in body["diff"])
    new = "".join(s.get("u", "") + s.get("i", "") for s in body["diff"])
    assert old == "Hello world" and new == "Hello brave world"
    assert body["stats"]["added"] > 0


async def test_diff_against_requires_content_and_existing_version(app):
    await _record(app, "p1", "d1", "x")
    assert (await call_asgi(app, "POST", "/project/p1/doc/d1/diff-against/1", json={})).status == 400
    assert (await call_asgi(app, "POST", "/project/p1/doc/d1/diff-against/99", json={"content": "y"})).status == 404


async def test_restore_pushes_and_records_new_version(app, doc_updater):
    await _record(app, "p1", "d1", "original", pathname="main.tex")
    await _record(app, "p1", "d1", "edited badly")
    r = await call_asgi(app, "POST", "/project/p1/doc/d1/restore/1", json={"user_id": "u9"})
    assert r.status == 200
    assert r.json["restoredFrom"] == 1 and r.json["pushed"] is True and r.json["created"] is True
    # the original content was pushed to document-updater
    assert doc_updater.calls[-1]["content"] == "original"
    assert doc_updater.calls[-1]["doc_id"] == "d1"
    # and a new "restore" version now tops the timeline
    versions = (await call_asgi(app, "GET", "/project/p1/doc/d1/versions")).json["versions"]
    assert versions[0]["source"] == "restore"
    assert (await call_asgi(app, "GET", f"/project/p1/version/{versions[0]['version']}")).json["content"] == "original"


async def test_restore_missing_version_is_404(app):
    r = await call_asgi(app, "POST", "/project/p1/doc/d1/restore/5")
    assert r.status == 404


async def test_delete_project(app):
    await _record(app, "p1", "d1", "x")
    await call_asgi(app, "DELETE", "/project/p1")
    assert (await call_asgi(app, "GET", "/project/p1/versions")).json["versions"] == []
