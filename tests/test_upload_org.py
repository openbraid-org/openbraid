"""Unit tests for `tool_upload_org_impl` (Phase E E0-prep).

Covers:
- catdef envelope validation (catdef / orgdef / type fields)
- orgdef MUST-field validation (id / name / version)
- type-must-be-orgdef:Organization gate
- org_slug validation (non-empty, no slashes/whitespace)
- slug_id_mismatch flag in response
- insert path (no existing artifact)
- update path (existing artifact for same account+slug)

Supabase is mocked end-to-end — these tests run without env vars or
network. Live integration is verified via production smoke.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

VALID_ARTIFACT = {
    "catdef": "1.4",
    "orgdef": "0.2.0",
    "type": "orgdef:Organization",
    "id": "thingalog",
    "name": "Thingalog",
    "version": "1.0.0",
    "mission": "test",
    "positions": [
        {"id": "product-strategist", "name": "Product Strategist"},
        {"id": "implementer", "name": "Implementer"},
    ],
}


def _build_supabase_for_upload(existing_artifact=None):
    """Build a mock Supabase client wired for the chained calls
    `tool_upload_org_impl` makes. Two distinct query patterns:

    1. roles lookup (.eq("id", X)) — returns account_id
    2. org_artifacts existing lookup (.eq.eq.is_) — returns existing or empty
    3. org_artifacts insert OR update — returns the row

    We rig a single MagicMock with the right return paths.
    """
    client = MagicMock()
    table = client.table.return_value

    # roles lookup: .select("account_id").eq("id", role_id).execute()
    # The .eq().execute() chain.
    roles_chain = table.select.return_value.eq.return_value
    roles_chain.execute.return_value.data = [{"account_id": "acct-uuid-123"}]

    # org_artifacts existing-lookup: .select("id").eq().eq().is_().execute()
    # Three-eq chain. Tests sometimes go down this path and sometimes don't,
    # so the chain has to respond to either pattern.
    existing_chain = (
        table.select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
    )
    existing_chain.execute.return_value.data = (
        [existing_artifact] if existing_artifact else []
    )

    # Insert: .insert().execute()
    insert_chain = table.insert.return_value
    insert_chain.execute.return_value.data = [{"id": "artifact-uuid-new"}]

    # Update: .update().eq().execute()
    update_chain = table.update.return_value.eq.return_value
    update_chain.execute.return_value.data = [{"id": "artifact-uuid-existing"}]

    return client


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_inserts_new_artifact_when_none_exists(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=VALID_ARTIFACT,
        )

    assert result["artifact_id"] == "artifact-uuid-new"
    assert result["org_slug"] == "thingalog"
    assert result["version"] == "1.0.0"
    assert result["position_count"] == 2
    assert result["slug_id_mismatch"] is False
    assert result["byte_count"] > 0
    # Verify insert was called with the right shape
    insert_call = fake.table.return_value.insert.call_args
    inserted = insert_call[0][0]
    assert inserted["account_id"] == "acct-uuid-123"
    assert inserted["org_slug"] == "thingalog"
    assert inserted["content"] == VALID_ARTIFACT


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_updates_existing_artifact_when_slug_matches(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    fake = _build_supabase_for_upload(
        existing_artifact={"id": "artifact-uuid-existing"}
    )
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=VALID_ARTIFACT,
        )

    assert result["artifact_id"] == "artifact-uuid-existing"
    fake.table.return_value.insert.assert_not_called()
    fake.table.return_value.update.assert_called_once()


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_flags_slug_id_mismatch(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="my-thingalog",  # differs from content.id == "thingalog"
            content=VALID_ARTIFACT,
        )

    assert result["slug_id_mismatch"] is True


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_wrong_type(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {**VALID_ARTIFACT, "type": "orgdef:Library"}
    with pytest.raises(ValueError, match="orgdef:Organization"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_missing_catdef_field(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {k: v for k, v in VALID_ARTIFACT.items() if k != "catdef"}
    with pytest.raises(ValueError, match="catdef"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_missing_id_field(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {k: v for k, v in VALID_ARTIFACT.items() if k != "id"}
    with pytest.raises(ValueError, match="'id'"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_empty_string_field(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {**VALID_ARTIFACT, "name": ""}
    with pytest.raises(ValueError, match="non-empty"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_non_dict_content(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    with pytest.raises(ValueError, match="JSON object"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content="not a dict",  # type: ignore[arg-type]
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_slug_with_slash(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    with pytest.raises(ValueError, match="must not contain"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="bad/slug",
            content=VALID_ARTIFACT,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_empty_slug(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    with pytest.raises(ValueError, match="non-empty"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="",
            content=VALID_ARTIFACT,
        )
