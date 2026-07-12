from __future__ import annotations

from fleetex_service_kit.contract import call_asgi

TID = "a" * 24  # template_id must be 24-hex for the insert-key validation


async def test_status_and_health(app):
    st = await call_asgi(app, "GET", "/status")
    assert st.status == 200 and st.text == "filestore is up"
    hc = await call_asgi(app, "GET", "/health_check")
    assert hc.status == 200 and hc.text == "OK"


async def test_template_roundtrip(app):
    post = await call_asgi(app, "POST", f"/template/{TID}/v/0/pdf", content=b"0123456789")
    assert post.status == 200 and post.text == "OK"

    get = await call_asgi(app, "GET", f"/template/{TID}/v/0/pdf")
    assert get.status == 200 and get.text == "0123456789"

    head = await call_asgi(app, "HEAD", f"/template/{TID}/v/0/pdf")
    assert head.status == 200
    # HEAD sets Content-Length (from Response headers); body is empty.


async def test_range_returns_200_not_206(app):
    await call_asgi(app, "POST", f"/template/{TID}/v/0/pdf", content=b"0123456789")
    r = await call_asgi(app, "GET", f"/template/{TID}/v/0/pdf", headers={"Range": "bytes=2-5"})
    assert r.status == 200  # NOT 206
    assert r.text == "2345"


async def test_cache_warm_returns_ok_without_body(app):
    await call_asgi(app, "POST", f"/template/{TID}/v/0/pdf", content=b"payload")
    r = await call_asgi(app, "GET", f"/template/{TID}/v/0/pdf", params={"cacheWarm": "true"})
    assert r.status == 200 and r.text == "OK"


async def test_missing_file_404(app):
    r = await call_asgi(app, "GET", f"/template/{TID}/v/9/pdf")
    assert r.status == 404


async def test_invalid_insert_key_500(app):
    r = await call_asgi(app, "POST", "/template/not-hex/v/0/pdf", content=b"x")
    assert r.status == 500  # InvalidParametersError -> 500 plain text


async def test_generic_bucket_route(app):
    # place a file via the persistor into a relative bucket dir, then fetch it
    await app.state.persistor.send_stream("genericbucket", "a/b.txt", _aiter(b"bucketdata"))
    r = await call_asgi(app, "GET", "/bucket/genericbucket/key/a/b.txt")
    assert r.status == 200 and r.text == "bucketdata"


async def test_history_global_blob_route(app):
    stores = app.state.config.stores
    h = "abcdef0123456789abcdef"
    key = f"{h[0:2]}/{h[2:4]}/{h[4:]}"
    await app.state.persistor.send_stream(stores["global_blobs"], key, _aiter(b"blobcontents"), use_subdirectories=True)
    r = await call_asgi(app, "GET", f"/history/global/hash/{h}")
    assert r.status == 200 and r.text == "blobcontents"


async def _aiter(data: bytes, chunk: int = 4):
    for i in range(0, len(data), chunk):
        yield data[i : i + chunk]
