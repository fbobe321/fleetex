"""Output parsers for synctex and texcount — ports of SynctexOutputParser.js and
CompileManager._parseWordcountFromOutput. Pure string parsing (fully testable)."""

from __future__ import annotations

import os


def _records(output: str) -> list[list[str]]:
    """Split synctex output into records, each starting at an 'Output:' line."""
    records: list[list[str]] = []
    for line in output.splitlines():
        if line.startswith("Output:"):
            records.append([])
        elif records:
            records[-1].append(line)
    return records


def _label(line: str) -> tuple[str, str]:
    key, _, value = line.partition(":")
    return key.strip(), value.strip()


def parse_view_output(output: str) -> list[dict]:
    """Forward (code->pdf): -> [{page, h, v, width, height}]."""
    hits: list[dict] = []
    for record in _records(output):
        hit: dict = {}
        for line in record:
            key, value = _label(line)
            if key == "Page":
                hit["page"] = int(value)
            elif key == "h":
                hit["h"] = float(value)
            elif key == "v":
                hit["v"] = float(value)
            elif key == "W":
                hit["width"] = float(value)
            elif key == "H":
                hit["height"] = float(value)
        if hit:
            hits.append(hit)
    return hits


def parse_edit_output(output: str, base_dir: str) -> list[dict]:
    """Inverse (pdf->code): -> [{file, line, column}]."""
    hits: list[dict] = []
    for record in _records(output):
        hit: dict = {}
        for line in record:
            key, value = _label(line)
            if key == "Input":
                if os.path.isabs(value):
                    value = os.path.relpath(value, base_dir)
                hit["file"] = value
            elif key == "Line":
                hit["line"] = int(value)
            elif key == "Column":
                hit["column"] = int(value)
        if hit:
            hits.append(hit)
    return hits


def parse_wordcount(output: str) -> dict:
    result = {
        "encode": "", "textWords": 0, "headWords": 0, "outside": 0, "headers": 0,
        "elements": 0, "mathInline": 0, "mathDisplay": 0, "errors": 0, "messages": "",
    }
    for line in output.splitlines():
        _key, _, value = line.partition(":")
        value = value.strip()
        if "Encoding" in line:
            result["encode"] = value
        elif "in text" in line:
            result["textWords"] = _int(value)
        elif "in head" in line:
            result["headWords"] = _int(value)
        elif "outside" in line:
            result["outside"] = _int(value)
        elif "of head" in line:
            result["headers"] = _int(value)
        elif "Number of floats/tables/figures" in line:
            result["elements"] = _int(value)
        elif "Number of math inlines" in line:
            result["mathInline"] = _int(value)
        elif "Number of math displayed" in line:
            result["mathDisplay"] = _int(value)
        elif "(errors" in line:
            result["errors"] = _int(value.rstrip(")"))
        elif line.startswith("!!! "):
            result["messages"] += line + "\n"
    return result


def _int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return 0
