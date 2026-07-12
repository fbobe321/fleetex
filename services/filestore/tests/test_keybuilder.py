from __future__ import annotations

from fleetex_filestore.keybuilder import (
    add_caching_to_key,
    global_blob_key,
    project_blob_key,
    project_key_format,
    template_file_key,
    validate_insert_key,
)

STORES = {"template_files": "/tf", "global_blobs": "/gb", "project_blobs": "/pb"}


def test_project_key_format():
    # zero-pad to 9, reverse, split 3/3/rest
    assert project_key_format("123") == "321/000/000"
    assert project_key_format("000000123") == "321/000/000"


def test_template_file_key():
    spec = template_file_key(STORES, "a" * 24, "0", "pdf")
    assert spec.bucket == "/tf"
    assert spec.key == f"{'a' * 24}/v/0/pdf"
    assert spec.use_subdirectories is False
    sub = template_file_key(STORES, "a" * 24, "0", "pdf", "thumb")
    assert sub.key == f"{'a' * 24}/v/0/pdf/thumb"


def test_global_blob_key_uses_subdirectories():
    spec = global_blob_key(STORES, "abcdef0123456789")
    assert spec.bucket == "/gb"
    assert spec.key == "ab/cd/ef0123456789"
    assert spec.use_subdirectories is True


def test_project_blob_key():
    spec = project_blob_key(STORES, "123", "abcdef0123")
    assert spec.bucket == "/pb"
    assert spec.key == "321/000/000/ab/cdef0123"
    assert spec.use_subdirectories is True


def test_add_caching_to_key():
    k = "abc"
    assert add_caching_to_key(k, "png", None) == "abc-converted-cache/format-png"
    assert add_caching_to_key(k, None, "thumbnail") == "abc-converted-cache/style-thumbnail"
    assert add_caching_to_key(k, "png", "preview") == "abc-converted-cache/format-png-style-preview"


def test_validate_insert_key():
    tid = "a" * 24
    assert validate_insert_key(f"{tid}/v/0/pdf") is True
    assert validate_insert_key(f"{tid}/{'b' * 24}") is True
    assert validate_insert_key("not-hex/v/0/pdf") is False
    assert validate_insert_key("short/v/0/pdf") is False
