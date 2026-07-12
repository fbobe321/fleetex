"""Unit tests: password hashing, cookie signing, session store, authorization."""

from __future__ import annotations

import json

import pytest
from bson import ObjectId

from fleetex_web import authorization as authz
from fleetex_web.passwords import hash_password, verify_password
from fleetex_web.sessions import SessionStore, generate_session_id, get_logged_in_user_id, serialize_user, validation_token


# --- passwords ----------------------------------------------------------- #
def test_hash_is_bcrypt_2a_and_verifies():
    h = hash_password("hunter2", rounds=4)
    assert h.startswith("$2a$04$")  # minor 'a', cost 4
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_password_too_long_rejected():
    with pytest.raises(ValueError):
        hash_password("x" * 73, rounds=4)
    assert verify_password("x" * 73, hash_password("short", rounds=4)) is False


# --- cookie signing (Node interop) --------------------------------------- #
def test_cookie_signature_matches_node_cookie_signature_lib():
    # Reference value independently confirmed against `openssl dgst -sha256 -hmac`.
    # Locks the algorithm to the Node `cookie-signature` scheme -> cookies are
    # cross-verifiable between fleetex-web and the Node services.
    from fleetex_web.sessions import _sign

    assert _sign("test-sid-value", "my-session-secret") == "2b3tm5u9IwGFY/JVIVS8X9z/BTLTwD2edHjTpW5Bcg0"


def test_cookie_sign_unsign_roundtrip(redis):
    store = SessionStore(redis, ["s1", "s2"], 100)
    sid = "abc123"
    signed = store.sign_cookie(sid)
    assert store.unsign_cookie(signed) == sid


def test_cookie_verifies_against_any_secret_and_rejects_tamper(redis):
    signer = SessionStore(redis, ["old-secret"], 100)
    verifier = SessionStore(redis, ["new-secret", "old-secret"], 100)  # rotation: old still accepted
    signed = signer.sign_cookie("sid42")
    assert verifier.unsign_cookie(signed) == "sid42"
    assert verifier.unsign_cookie(signed[:-2] + "xx") is None  # tampered sig


# --- session store (validationToken) ------------------------------------- #
async def test_session_save_load_with_validation_token(redis):
    store = SessionStore(redis, ["s"], 100)
    sid = generate_session_id()
    await store.save(sid, {"passport": {"user": {"_id": "u1", "email": "a@b"}}})
    # stored under sess:<sid> with the v1 validation token
    raw = await redis.get(f"sess:{sid}")
    assert json.loads(raw)["validationToken"] == validation_token(sid)
    loaded = await store.load(sid)
    assert get_logged_in_user_id(loaded) == "u1"


async def test_session_rejected_when_validation_token_wrong(redis):
    store = SessionStore(redis, ["s"], 100)
    sid = generate_session_id()
    await redis.set(f"sess:{sid}", json.dumps({"validationToken": "v1:XXXX", "passport": {"user": {"_id": "u1"}}}))
    assert await store.load(sid) is None  # mismatched token -> treated as missing


def test_serialize_user_shape():
    u = serialize_user({"_id": ObjectId(), "email": "a@b.com", "first_name": "A"})
    assert set(u) >= {"_id", "email", "first_name", "last_name"}
    assert isinstance(u["_id"], str)


# --- authorization ------------------------------------------------------- #
def test_privilege_levels():
    owner = ObjectId()
    collab = ObjectId()
    project = {"owner_ref": owner, "collaberator_refs": [collab], "publicAccesLevel": "private"}
    assert authz.privilege_level_for_user(project, str(owner)) == authz.OWNER
    assert authz.privilege_level_for_user(project, str(collab)) == authz.READ_AND_WRITE
    assert authz.privilege_level_for_user(project, str(ObjectId())) is authz.NONE
    assert authz.privilege_level_for_user(project, str(ObjectId()), is_admin=True) == authz.OWNER


def test_public_and_token_access():
    public = {"owner_ref": ObjectId(), "publicAccesLevel": "readOnly"}
    assert authz.privilege_level_for_user(public, str(ObjectId())) == authz.READ_ONLY
    token_project = {"owner_ref": ObjectId(), "publicAccesLevel": "tokenBased", "tokens": {"readOnly": "tok-ro"}}
    assert authz.anonymous_privilege_level(token_project, "tok-ro") == authz.READ_ONLY
    assert authz.anonymous_privilege_level(token_project, "bad") is authz.NONE


def test_is_restricted_user():
    assert authz.is_restricted_user(authz.NONE, False, False, True) is True
    assert authz.is_restricted_user(authz.READ_ONLY, False, False, True) is True  # anon read-only
    assert authz.is_restricted_user(authz.READ_ONLY, False, True, False) is False  # invited member
    assert authz.is_restricted_user(authz.OWNER, False, False, False) is False


def test_build_project_view_redacts_for_restricted():
    owner = {"_id": ObjectId(), "email": "o@w.com", "first_name": "Own"}
    project = {"_id": ObjectId(), "owner_ref": owner["_id"], "name": "P", "members": [{"x": 1}]}
    full = authz.build_project_view(project, owner, restricted=False)
    assert full["owner"]["email"] == "o@w.com" and full["members"] == [{"x": 1}]
    redacted = authz.build_project_view(project, owner, restricted=True)
    assert redacted["owner"] == {"_id": str(owner["_id"])} and redacted["members"] == []
