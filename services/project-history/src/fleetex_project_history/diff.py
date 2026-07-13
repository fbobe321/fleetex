"""Text diffing for the history view.

``segment_diff`` produces Overleaf-style ``{u|i|d}`` segments (unchanged /
inserted / deleted) over the two document versions, computed char-wise but
coalesced on word/newline boundaries so the output is compact and readable.
``unified`` is a plain unified line diff for a textual download.
"""

from __future__ import annotations

import difflib
import re

# split into words, whitespace runs, and newlines — diffing on these tokens
# gives far more legible segments than raw characters while staying exact.
_TOKEN = re.compile(r"\n|[^\S\n]+|\S+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def segment_diff(old: str, new: str) -> list[dict]:
    """Return a list of ``{"u"|"i"|"d": text}`` segments transforming old→new."""
    a, b = _tokens(old), _tokens(new)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    segments: list[dict] = []

    def _emit(kind: str, text: str) -> None:
        if not text:
            return
        if segments and kind in segments[-1]:
            segments[-1][kind] += text
        else:
            segments.append({kind: text})

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            _emit("u", "".join(a[i1:i2]))
        elif tag == "delete":
            _emit("d", "".join(a[i1:i2]))
        elif tag == "insert":
            _emit("i", "".join(b[j1:j2]))
        elif tag == "replace":
            _emit("d", "".join(a[i1:i2]))
            _emit("i", "".join(b[j1:j2]))
    return segments


def unified(old: str, new: str, *, from_label: str = "old", to_label: str = "new") -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=from_label,
        tofile=to_label,
    )
    return "".join(diff)


def diff_stats(segments: list[dict]) -> dict:
    """Char counts added / removed across the segment list."""
    added = sum(len(s["i"]) for s in segments if "i" in s)
    removed = sum(len(s["d"]) for s in segments if "d" in s)
    return {"added": added, "removed": removed}
