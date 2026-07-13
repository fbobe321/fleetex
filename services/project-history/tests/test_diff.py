"""Segment / unified diff engine."""

from __future__ import annotations

from fleetex_project_history.diff import diff_stats, segment_diff, unified


def _apply(segments):
    """Reconstruct (old, new) from segments to prove the diff is exact."""
    old = "".join(s.get("u", "") + s.get("d", "") for s in segments)
    new = "".join(s.get("u", "") + s.get("i", "") for s in segments)
    return old, new


def test_identical_is_all_unchanged():
    segs = segment_diff("hello world", "hello world")
    assert segs == [{"u": "hello world"}]
    assert diff_stats(segs) == {"added": 0, "removed": 0}


def test_pure_insertion():
    segs = segment_diff("a b", "a b c")
    old, new = _apply(segs)
    assert old == "a b" and new == "a b c"
    assert any("i" in s for s in segs)


def test_pure_deletion():
    segs = segment_diff("a b c", "a c")
    old, new = _apply(segs)
    assert old == "a b c" and new == "a c"
    assert any("d" in s for s in segs)


def test_replace_roundtrips_exactly():
    old_t = "The quick brown fox"
    new_t = "The slow brown dog"
    segs = segment_diff(old_t, new_t)
    old, new = _apply(segs)
    assert old == old_t and new == new_t
    stats = diff_stats(segs)
    assert stats["added"] > 0 and stats["removed"] > 0


def test_multiline_and_unified():
    old_t = "line1\nline2\nline3\n"
    new_t = "line1\nline2 changed\nline3\n"
    segs = segment_diff(old_t, new_t)
    old, new = _apply(segs)
    assert old == old_t and new == new_t
    u = unified(old_t, new_t)
    assert "-line2" in u and "+line2 changed" in u
