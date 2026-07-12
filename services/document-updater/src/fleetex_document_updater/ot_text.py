"""ShareJS "text" OT type — a verbatim port of Overleaf document-updater's
``app/js/sharejs/types/text.js`` + ``helpers.js`` (the sharejs-text-ot type).

An op is a list of components; a component is exactly one of:
  * insert  ``{"i": "text", "p": pos}``
  * delete  ``{"d": "text", "p": pos}``   (delete carries the exact removed text)
  * comment ``{"c": "text", "p": pos, "t": id}``  (does not mutate the string)

This module is the correctness core of collaborative editing. It is verified by a
TP1 convergence fuzzer (see tests) — DO NOT "optimize" the transform logic; match
the original exactly.
"""

from __future__ import annotations


class OTError(Exception):
    pass


# --- component predicates ------------------------------------------------ #
def _is_insert(c: dict) -> bool:
    return isinstance(c.get("i"), str)


def _is_delete(c: dict) -> bool:
    return isinstance(c.get("d"), str)


def _is_comment(c: dict) -> bool:
    return isinstance(c.get("c"), str)


def _str_inject(s1: str, pos: int, s2: str) -> str:
    return s1[:pos] + s2 + s1[pos:]


# --- validation ---------------------------------------------------------- #
def check_valid_component(c: dict) -> None:
    if not isinstance(c.get("p"), int):
        raise OTError("component missing position field")
    i, d, cc = _is_insert(c), _is_delete(c), _is_comment(c)
    if not (i ^ d ^ cc):
        raise OTError("component needs an i, d or c field")
    if c["p"] < 0:
        raise OTError("position cannot be negative")


def check_valid_op(op: list) -> None:
    for c in op:
        check_valid_component(c)


# --- apply --------------------------------------------------------------- #
def apply(snapshot: str, op: list) -> str:
    check_valid_op(op)
    for c in op:
        if _is_insert(c):
            snapshot = _str_inject(snapshot, c["p"], c["i"])
        elif _is_delete(c):
            deleted = snapshot[c["p"] : c["p"] + len(c["d"])]
            if c["d"] != deleted:
                raise OTError(f"Delete component '{c['d']}' does not match deleted text '{deleted}'")
            snapshot = snapshot[: c["p"]] + snapshot[c["p"] + len(c["d"]) :]
        elif _is_comment(c):
            found = snapshot[c["p"] : c["p"] + len(c["c"])]
            if c["c"] != found:
                raise OTError(f"Comment component '{c['c']}' does not match text '{found}'")
        else:
            raise OTError("Unknown op type")
    return snapshot


# --- append / compose / normalize ---------------------------------------- #
def _append(new_op: list, c: dict) -> None:
    if c.get("i") == "" or c.get("d") == "":
        return  # drop zero-length
    if not new_op:
        new_op.append(c)
        return
    last = new_op[-1]
    if _is_insert(last) and _is_insert(c) and last["p"] <= c["p"] <= last["p"] + len(last["i"]):
        new_op[-1] = {"i": _str_inject(last["i"], c["p"] - last["p"], c["i"]), "p": last["p"]}
    elif _is_delete(last) and _is_delete(c) and c["p"] <= last["p"] <= c["p"] + len(c["d"]):
        new_op[-1] = {"d": _str_inject(c["d"], last["p"] - c["p"], last["d"]), "p": c["p"]}
    else:
        new_op.append(c)


def compose(op1: list, op2: list) -> list:
    check_valid_op(op1)
    check_valid_op(op2)
    new_op = list(op1)
    for c in op2:
        _append(new_op, c)
    return new_op


def normalize(op) -> list:
    new_op: list = []
    if isinstance(op, dict):
        op = [op]
    for c in op:
        c = dict(c)
        c.setdefault("p", 0)
        _append(new_op, c)
    return new_op


# --- transform ----------------------------------------------------------- #
def transform_position(pos: int, c: dict, insert_after: bool = False) -> int:
    if _is_insert(c):
        if c["p"] < pos or (c["p"] == pos and insert_after):
            return pos + len(c["i"])
        return pos
    if _is_delete(c):
        if pos <= c["p"]:
            return pos
        if pos <= c["p"] + len(c["d"]):
            return c["p"]
        return pos - len(c["d"])
    return pos  # comment


def transform_component(dest: list, c: dict, other_c: dict, side: str) -> list:
    check_valid_op([c])
    check_valid_op([other_c])

    if _is_insert(c):
        _append(dest, {"i": c["i"], "p": transform_position(c["p"], other_c, side == "right")})

    elif _is_delete(c):
        if _is_insert(other_c):
            s = c["d"]
            if c["p"] < other_c["p"]:
                _append(dest, {"d": s[: other_c["p"] - c["p"]], "p": c["p"]})
                s = s[other_c["p"] - c["p"] :]
            if s != "":
                _append(dest, {"d": s, "p": c["p"] + len(other_c["i"])})
        elif _is_delete(other_c):
            if c["p"] >= other_c["p"] + len(other_c["d"]):
                _append(dest, {"d": c["d"], "p": c["p"] - len(other_c["d"])})
            elif c["p"] + len(c["d"]) <= other_c["p"]:
                _append(dest, c)
            else:
                new_c = {"d": "", "p": c["p"]}
                if c["p"] < other_c["p"]:
                    new_c["d"] = c["d"][: other_c["p"] - c["p"]]
                if c["p"] + len(c["d"]) > other_c["p"] + len(other_c["d"]):
                    new_c["d"] += c["d"][other_c["p"] + len(other_c["d"]) - c["p"] :]
                intersect_start = max(c["p"], other_c["p"])
                intersect_end = min(c["p"] + len(c["d"]), other_c["p"] + len(other_c["d"]))
                c_intersect = c["d"][intersect_start - c["p"] : intersect_end - c["p"]]
                other_intersect = other_c["d"][intersect_start - other_c["p"] : intersect_end - other_c["p"]]
                if c_intersect != other_intersect:
                    raise OTError("Delete ops delete different text in the same region of the document")
                if new_c["d"] != "":
                    new_c["p"] = transform_position(new_c["p"], other_c)
                    _append(dest, new_c)
        elif _is_comment(other_c):
            _append(dest, c)

    elif _is_comment(c):
        if _is_insert(other_c):
            if c["p"] < other_c["p"] < c["p"] + len(c["c"]):
                offset = other_c["p"] - c["p"]
                new_c_text = c["c"][:offset] + other_c["i"] + c["c"][offset:]
                _append(dest, {**c, "c": new_c_text})
            else:
                _append(dest, {**c, "p": transform_position(c["p"], other_c, True)})
        elif _is_delete(other_c):
            if c["p"] >= other_c["p"] + len(other_c["d"]):
                _append(dest, {**c, "p": c["p"] - len(other_c["d"])})
            elif c["p"] + len(c["c"]) <= other_c["p"]:
                _append(dest, c)
            else:
                new_text = ""
                if c["p"] < other_c["p"]:
                    new_text = c["c"][: other_c["p"] - c["p"]]
                if c["p"] + len(c["c"]) > other_c["p"] + len(other_c["d"]):
                    new_text += c["c"][other_c["p"] + len(other_c["d"]) - c["p"] :]
                new_c = {**c, "c": new_text, "p": transform_position(c["p"], other_c)}
                _append(dest, new_c)
        elif _is_comment(other_c):
            _append(dest, c)

    return dest


def _transform_component_x(left, right, dest_left, dest_right) -> None:
    transform_component(dest_left, left, right, "left")
    transform_component(dest_right, right, left, "right")


def transform_x(left_op: list, right_op: list):
    check_valid_op(left_op)
    check_valid_op(right_op)
    new_right_op: list = []
    for right_component in right_op:
        new_left_op: list = []
        k = 0
        while k < len(left_op):
            left_component = left_op[k]
            k += 1
            next_c: list = []
            _transform_component_x(left_component, right_component, new_left_op, next_c)
            if len(next_c) == 1:
                right_component = next_c[0]
            elif len(next_c) == 0:
                for l in left_op[k:]:
                    _append(new_left_op, l)
                right_component = None
                break
            else:
                l_result, r_result = transform_x(left_op[k:], next_c)
                for l in l_result:
                    _append(new_left_op, l)
                for r in r_result:
                    _append(new_right_op, r)
                right_component = None
                break
        if right_component is not None:
            _append(new_right_op, right_component)
        left_op = new_left_op
    return left_op, new_right_op


def transform(op: list, other_op: list, side: str) -> list:
    if side not in ("left", "right"):
        raise OTError("side (type) must be 'left' or 'right'")
    check_valid_op(op)
    check_valid_op(other_op)
    if not other_op:
        return op
    if len(op) == 1 and len(other_op) == 1:
        return transform_component([], op[0], other_op[0], side)
    if side == "left":
        left, _ = transform_x(op, other_op)
        return left
    _, right = transform_x(other_op, op)
    return right


def invert(op: list) -> list:
    result = []
    for c in reversed(op):
        if _is_insert(c):
            result.append({"d": c["i"], "p": c["p"]})
        elif _is_delete(c):
            result.append({"i": c["d"], "p": c["p"]})
    return result
