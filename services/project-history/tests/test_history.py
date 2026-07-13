"""HistoryManager version storage."""

from __future__ import annotations

import pytest

from fleetex_project_history.history import HistoryManager


@pytest.fixture
def hm(db):
    return HistoryManager(db)


async def test_record_assigns_monotonic_project_versions(hm):
    r1 = await hm.record_version("p1", "docA", "v1", pathname="a.tex")
    r2 = await hm.record_version("p1", "docB", "vB", pathname="b.tex")
    r3 = await hm.record_version("p1", "docA", "v2")
    assert [r1["version"]["version"], r2["version"]["version"], r3["version"]["version"]] == [1, 2, 3]
    assert all(r["created"] for r in (r1, r2, r3))


async def test_identical_snapshot_is_deduped(hm):
    r1 = await hm.record_version("p1", "docA", "same")
    r2 = await hm.record_version("p1", "docA", "same")
    assert r1["created"] and not r2["created"]
    assert r1["version"]["version"] == r2["version"]["version"]
    versions = await hm.list_doc_versions("p1", "docA")
    assert len(versions) == 1


async def test_pathname_carries_forward_when_omitted(hm):
    await hm.record_version("p1", "docA", "v1", pathname="chapters/intro.tex")
    r2 = await hm.record_version("p1", "docA", "v2")  # no pathname given
    assert r2["version"]["pathname"] == "chapters/intro.tex"


async def test_project_timeline_newest_first_and_paginates(hm):
    for i in range(5):
        await hm.record_version("p1", "docA", f"content-{i}")
    latest = await hm.list_project_versions("p1", limit=2)
    assert [v["version"] for v in latest] == [5, 4]
    older = await hm.list_project_versions("p1", limit=10, before=4)
    assert [v["version"] for v in older] == [3, 2, 1]
    # timeline metadata excludes content
    assert "content" not in latest[0]


async def test_get_version_and_version_before(hm):
    await hm.record_version("p1", "docA", "one")
    await hm.record_version("p1", "docA", "two")
    await hm.record_version("p1", "docA", "three")
    v2 = await hm.get_doc_version("p1", "docA", 2)
    assert v2["content"] == "two"
    prev = await hm.version_before("p1", "docA", 3)
    assert prev["content"] == "two"


async def test_delete_project_purges(hm):
    await hm.record_version("p1", "docA", "x")
    await hm.record_version("p2", "docA", "y")
    n = await hm.delete_project("p1")
    assert n == 1
    assert await hm.list_project_versions("p1") == []
    assert len(await hm.list_project_versions("p2")) == 1
