"""Unit tests for the F-edit MCP patch tools.

Covers:
- update_position: patch merges into the target item, version bumps,
  replicant rejected, version-mismatch rejected, protected fields
  (id, type) rejected.
- update_org_metadata: patch merges at catalog level, protected keys
  rejected, version auto-bumps when absent.
- bump_version: explicit semver bump kinds; rejects unknown kind.
- _bump_semver: a few edge cases (suffix preservation, zero-pad).
- Audit row written for each successful edit.

Supabase mocked end-to-end via the same patterns as test_upload_org.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.tool_impls import _bump_semver


VALID_OPENCATALOG = {
    "catdef": "1.4",
    "orgdef": "1.0.0",
    "type": "orgdef:Organization",
    "id": "thingalog",
    "name": "Thingalog",
    "version": "2.0.0",
    "mission": "test mission",
    "items": [
        {
            "type": "orgdef:Position",
            "id": "implementer",
            "name": "Implementer",
            "status": "staffed",
            "summary": "old summary",
        },
        {
            "type": "orgdef:Position",
            "id": "product-owner",
            "name": "Product Owner",
            "status": "staffed",
        },
    ],
}


def _build_supabase(content=None, existing_version="2.0.0", master_url=None, audit_id="audit-uuid-stub"):
    """Build a mock Supabase client wired for the edit flow's chained
    calls. Re-used across the update_position / update_org_metadata /
    bump_version tests."""
    client = MagicMock()
    table = client.table.return_value

    # roles lookup for session-token resolution
    roles_chain = table.select.return_value.eq.return_value
    roles_chain.execute.return_value.data = [{"account_id": "acct-uuid"}]

    # org_artifacts edit-load chain: select().eq().eq().is_().execute()
    artifact_content = content if content is not None else dict(VALID_OPENCATALOG)
    if master_url is not None:
        artifact_content["x.org.master_url"] = master_url
    edit_load_chain = (
        table.select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
    )
    edit_load_chain.execute.return_value.data = [{
        "id": "art-uuid",
        "account_id": "acct-uuid",
        "org_slug": "thingalog",
        "content": artifact_content,
        "version": existing_version,
        "created_at": "2026-05-10T00:00:00Z",
        "updated_at": "2026-05-10T00:00:00Z",
    }]

    # update + insert chains
    update_chain = table.update.return_value.eq.return_value
    update_chain.execute.return_value.data = [{"id": "art-uuid"}]
    insert_chain = table.insert.return_value
    insert_chain.execute.return_value.data = [{"id": audit_id}]

    return client


# --- _bump_semver -----------------------------------------------------------


def test_bump_semver_patch_default():
    assert _bump_semver("1.2.3") == "1.2.4"


def test_bump_semver_minor_zeros_patch():
    assert _bump_semver("1.2.3", "minor") == "1.3.0"


def test_bump_semver_major_zeros_below():
    assert _bump_semver("1.2.3", "major") == "2.0.0"


def test_bump_semver_preserves_suffix_on_target_segment():
    assert _bump_semver("1.0.0-rc1", "patch") == "1.0.1-rc1"


def test_bump_semver_pads_short_strings():
    assert _bump_semver("1", "patch") == "1.0.1"


def test_bump_semver_invalid_kind_rejects():
    with pytest.raises(ValueError, match="must be one of"):
        _bump_semver("1.0.0", "huge")


# --- update_position --------------------------------------------------------


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_merges_patch_and_bumps_version(_mock_role):
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position_id="implementer",
            patch={
                "summary": "new summary",
                "responsibilities": ["r1", "r2"],
            },
        )

    assert receipt["version_before"] == "2.0.0"
    assert receipt["version_after"] == "2.0.1"
    # The org_artifacts update call should carry the merged content
    update_call = fake.table.return_value.update.call_args_list[0]
    new_content = update_call[0][0]["content"]
    impl = next(it for it in new_content["items"] if it["id"] == "implementer")
    assert impl["summary"] == "new summary"
    assert impl["responsibilities"] == ["r1", "r2"]
    # Other position untouched
    po = next(it for it in new_content["items"] if it["id"] == "product-owner")
    assert po["status"] == "staffed"
    # Audit row inserted
    fake.table.return_value.insert.assert_called_once()
    audit_row = fake.table.return_value.insert.call_args[0][0]
    assert audit_row["tool_name"] == "update_position"
    assert "implementer" in audit_row["patch_summary"]
    assert audit_row["version_before"] == "2.0.0"
    assert audit_row["version_after"] == "2.0.1"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_receipt_includes_edit_log_id_and_applied_fields(_mock_role):
    """Strategist note 4: receipt must surface edit_log_id +
    applied_fields so AI clients can verify a patch landed and which
    keys it touched."""
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase(audit_id="audit-row-42")
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position_id="implementer",
            patch={"summary": "new", "responsibilities": ["r1", "r2"]},
        )

    assert receipt["edit_log_id"] == "audit-row-42"
    assert sorted(receipt["applied_fields"]) == sorted(["summary", "responsibilities"])


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_null_value_deletes_field_per_rfc_7396(_mock_role):
    """Strategist note 3: JSON Merge Patch semantics — a null value in
    the patch REMOVES the key from the target rather than setting it
    to None. applied_fields uses `-key` prefix to mark deletions."""
    from server.tool_impls import tool_update_position_impl

    # Seed the artifact's implementer with a `summary` field we'll
    # then delete.
    seeded = dict(VALID_OPENCATALOG)
    seeded["items"] = list(VALID_OPENCATALOG["items"])
    seeded["items"][0] = {**seeded["items"][0], "summary": "to be removed"}
    fake = _build_supabase(content=seeded)
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position_id="implementer",
            patch={"summary": None},
        )

    assert "-summary" in receipt["applied_fields"]
    new_content = fake.table.return_value.update.call_args[0][0]["content"]
    impl = next(it for it in new_content["items"] if it["id"] == "implementer")
    assert "summary" not in impl, "summary key should be removed entirely, not nulled"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_null_on_absent_key_is_noop(_mock_role):
    """RFC 7396: deleting an absent key is silently a no-op (no
    error). applied_fields just omits the entry."""
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position_id="implementer",
            patch={"never_existed": None, "summary": "new"},
        )

    assert "-never_existed" not in receipt["applied_fields"]
    assert "summary" in receipt["applied_fields"]


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_rejects_id_change(_mock_role):
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="must not change.*id"):
            await tool_update_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="implementer",
                patch={"id": "different-id"},
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_rejects_type_change(_mock_role):
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="must not change item type"):
            await tool_update_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="implementer",
                patch={"type": "roledef:Job"},
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_404s_on_unknown_position(_mock_role):
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="No Position item"):
            await tool_update_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="ghost",
                patch={"summary": "x"},
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_rejects_when_replicant(_mock_role):
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase(
        master_url="https://github.com/scottconfusedgorilla/thingalog/...",
    )
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="replicant"):
            await tool_update_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="implementer",
                patch={"summary": "x"},
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_position_rejects_version_mismatch(_mock_role):
    from server.tool_impls import tool_update_position_impl

    fake = _build_supabase(existing_version="2.0.0")
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="version conflict"):
            await tool_update_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="implementer",
                patch={"summary": "x"},
                expected_version="1.0.0",
            )


# --- update_org_metadata ----------------------------------------------------


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_org_metadata_merges_top_level_fields(_mock_role):
    from server.tool_impls import tool_update_org_metadata_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_org_metadata_impl(
            session_token="tok",
            org_slug="thingalog",
            patch={
                "vision": "a brand new vision",
                "values": [{"name": "v1", "description": "d1"}],
            },
        )

    assert receipt["version_after"] == "2.0.1"
    new_content = fake.table.return_value.update.call_args[0][0]["content"]
    assert new_content["vision"] == "a brand new vision"
    assert new_content["values"][0]["name"] == "v1"
    # items untouched
    assert len(new_content["items"]) == 2


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_org_metadata_rejects_protected_keys(_mock_role):
    from server.tool_impls import tool_update_org_metadata_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        for forbidden in ("catdef", "orgdef", "type", "id", "items"):
            with pytest.raises(ValueError, match="protected"):
                await tool_update_org_metadata_impl(
                    session_token="tok",
                    org_slug="thingalog",
                    patch={forbidden: "anything"},
                )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_org_metadata_explicit_version_skips_autobump(_mock_role):
    from server.tool_impls import tool_update_org_metadata_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_org_metadata_impl(
            session_token="tok",
            org_slug="thingalog",
            patch={"vision": "x", "version": "5.0.0"},
        )

    assert receipt["version_after"] == "5.0.0"


# --- bump_version -----------------------------------------------------------


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_bump_version_patch_default(_mock_role):
    from server.tool_impls import tool_bump_version_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_bump_version_impl(
            session_token="tok",
            org_slug="thingalog",
        )

    assert receipt["version_before"] == "2.0.0"
    assert receipt["version_after"] == "2.0.1"
    audit = fake.table.return_value.insert.call_args[0][0]
    assert audit["tool_name"] == "bump_version"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_bump_version_minor(_mock_role):
    from server.tool_impls import tool_bump_version_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_bump_version_impl(
            session_token="tok",
            org_slug="thingalog",
            kind="minor",
        )

    assert receipt["version_after"] == "2.1.0"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_bump_version_major(_mock_role):
    from server.tool_impls import tool_bump_version_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_bump_version_impl(
            session_token="tok",
            org_slug="thingalog",
            kind="major",
        )

    assert receipt["version_after"] == "3.0.0"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_bump_version_rejects_unknown_kind(_mock_role):
    from server.tool_impls import tool_bump_version_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="kind must be one of"):
            await tool_bump_version_impl(
                session_token="tok",
                org_slug="thingalog",
                kind="huge",
            )
