"""Tests for the export endpoint + round-trip preservation (Phase E E5).

The promise: an artifact uploaded to openbraid round-trips through
Postgres JSONB and the export endpoint to canonical-bytes-equivalent
output. Two artifacts that share the same canonical form share the
same SHA-256.

Covers:
- canonical_json: key order, separators, ensure_ascii=False
- canonical_json: same content under different key orderings → same bytes
- canonical_json: SHA-256 hex is deterministic
- export endpoint: 200, application/json, X-Content-SHA256 matches body
- export endpoint: 404 on unknown account, 404 on unknown slug
- end-to-end: upload content X, export comes back with canonical(X) hash
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server import rest_api
from server.canonical_json import canonicalize, sha256_hex


SAMPLE_OPENCATALOG = {
    "catdef": "1.4",
    "orgdef": "1.0.0",
    "type": "orgdef:Organization",
    "id": "thingalog",
    "name": "Thingalog",
    "version": "2.0.0",
    "mission": "test mission — with em-dash and Unicode β γ δ",
    "items": [
        {"type": "orgdef:Position", "id": "director", "name": "Director"},
        {"type": "orgdef:Position", "id": "engineer", "name": "Engineer"},
    ],
}


def test_canonicalize_emits_sorted_keys_compact_utf8():
    out = canonicalize({"b": 2, "a": 1})
    assert out == b'{"a":1,"b":2}'


def test_canonicalize_is_stable_under_key_reordering():
    a = {"x": 1, "y": [{"a": 1, "b": 2}, {"a": 3, "b": 4}], "z": 3}
    b = {"z": 3, "x": 1, "y": [{"b": 2, "a": 1}, {"b": 4, "a": 3}]}
    assert canonicalize(a) == canonicalize(b)
    assert sha256_hex(a) == sha256_hex(b)


def test_canonicalize_keeps_unicode_as_bytes_not_escapes():
    out = canonicalize({"x": "—"})
    # em-dash is U+2014 → UTF-8 bytes 0xE2 0x80 0x94
    assert out == b'{"x":"\xe2\x80\x94"}'


def test_sha256_hex_is_deterministic():
    h1 = sha256_hex(SAMPLE_OPENCATALOG)
    h2 = sha256_hex(SAMPLE_OPENCATALOG)
    assert h1 == h2
    assert len(h1) == 64  # 256 bits hex


def test_sha256_survives_json_serialize_roundtrip():
    """JSON serialize → deserialize must preserve canonical hash.
    This is the round-trip guarantee for Postgres JSONB: as long as
    JSONB preserves Unicode and value types, the hash matches."""
    h1 = sha256_hex(SAMPLE_OPENCATALOG)
    serialized = json.dumps(SAMPLE_OPENCATALOG)  # any JSON form
    deserialized = json.loads(serialized)
    h2 = sha256_hex(deserialized)
    assert h1 == h2


# --- Endpoint tests --------------------------------------------------------


client = TestClient(rest_api.api)


def test_export_endpoint_returns_canonical_bytes_and_hash_header():
    fake_account = {"id": "acct-uuid", "email": "scott@example.com"}
    fake_artifact = {
        "id": "art-uuid",
        "account_id": "acct-uuid",
        "org_slug": "thingalog",
        "content": SAMPLE_OPENCATALOG,
        "version": "2.0.0",
    }
    # Patch through the shared impl (tool_read_org_impl in tool_impls)
    # since the REST handler now routes through there per the Phase D
    # no-drift discipline.
    from server import tool_impls
    with patch.object(tool_impls, "account_by_handle", return_value=fake_account), \
         patch.object(tool_impls, "artifact_by_account_and_slug", return_value=fake_artifact):
        r = client.get("/export/scott/thingalog")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    expected_hash = sha256_hex(SAMPLE_OPENCATALOG)
    assert r.headers["x-content-sha256"] == expected_hash
    # Body bytes are the canonical form
    assert r.content == canonicalize(SAMPLE_OPENCATALOG)
    # And the body itself parses back to the original content
    assert json.loads(r.content) == SAMPLE_OPENCATALOG


def test_export_endpoint_returns_404_on_unknown_account():
    from server import tool_impls
    with patch.object(tool_impls, "account_by_handle", return_value=None):
        r = client.get("/export/ghost/thingalog")

    assert r.status_code == 404
    assert "No openbraid account" in r.json()["detail"]


def test_export_endpoint_returns_404_on_unknown_slug():
    from server import tool_impls
    fake_account = {"id": "acct-uuid", "email": "scott@example.com"}
    with patch.object(tool_impls, "account_by_handle", return_value=fake_account), \
         patch.object(tool_impls, "artifact_by_account_and_slug", return_value=None):
        r = client.get("/export/scott/ghost-org")

    assert r.status_code == 404
    assert "No org artifact" in r.json()["detail"]


async def test_read_org_returns_full_content_and_hash():
    """The MCP-side read_org tool returns the structured shape AI
    clients need: artifact_id + org_slug + version + content +
    content_sha256. Public read — no session_token needed."""
    from server import tool_impls

    fake_account = {"id": "acct-uuid", "email": "scott@example.com"}
    fake_artifact = {
        "id": "art-uuid",
        "account_id": "acct-uuid",
        "org_slug": "thingalog",
        "content": SAMPLE_OPENCATALOG,
        "version": "2.0.0",
    }
    with patch.object(tool_impls, "account_by_handle", return_value=fake_account), \
         patch.object(tool_impls, "artifact_by_account_and_slug", return_value=fake_artifact):
        result = await tool_impls.tool_read_org_impl("scott", "thingalog")

    assert result["artifact_id"] == "art-uuid"
    assert result["org_slug"] == "thingalog"
    assert result["version"] == "2.0.0"
    assert result["content"] == SAMPLE_OPENCATALOG
    assert result["content_sha256"] == sha256_hex(SAMPLE_OPENCATALOG)


async def test_read_org_raises_on_unknown_handle():
    from server import tool_impls

    with patch.object(tool_impls, "account_by_handle", return_value=None):
        with pytest.raises(ValueError, match="No openbraid account"):
            await tool_impls.tool_read_org_impl("ghost", "thingalog")


async def test_read_org_raises_on_unknown_slug():
    from server import tool_impls

    fake_account = {"id": "acct-uuid", "email": "scott@example.com"}
    with patch.object(tool_impls, "account_by_handle", return_value=fake_account), \
         patch.object(tool_impls, "artifact_by_account_and_slug", return_value=None):
        with pytest.raises(ValueError, match="No org artifact"):
            await tool_impls.tool_read_org_impl("scott", "ghost-org")


def test_export_endpoint_byte_equivalence_through_storage_simulation():
    """Full round-trip simulation: take a content dict, simulate Postgres
    JSONB storage (json.dumps + json.loads), serve via export, verify
    that exported bytes canonical-hash to the original."""
    from server import tool_impls
    fake_account = {"id": "acct-uuid", "email": "scott@example.com"}
    # Simulate Postgres-side: dict → JSON string → dict (loses key
    # order, normalizes whitespace, preserves types).
    stored = json.loads(json.dumps(SAMPLE_OPENCATALOG))
    fake_artifact = {
        "id": "art-uuid",
        "account_id": "acct-uuid",
        "org_slug": "thingalog",
        "content": stored,
        "version": "2.0.0",
    }
    # Patch through the shared impl (tool_read_org_impl in tool_impls)
    # since the REST handler now routes through there per the Phase D
    # no-drift discipline.
    from server import tool_impls
    with patch.object(tool_impls, "account_by_handle", return_value=fake_account), \
         patch.object(tool_impls, "artifact_by_account_and_slug", return_value=fake_artifact):
        r = client.get("/export/scott/thingalog")

    upload_hash = sha256_hex(SAMPLE_OPENCATALOG)
    export_hash = r.headers["x-content-sha256"]
    assert upload_hash == export_hash, (
        "round-trip canonical hash drifted between upload and export"
    )
