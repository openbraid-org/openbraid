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


# --- add_position ----------------------------------------------------------


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_add_position_appends_to_items(_mock_role):
    from server.tool_impls import tool_add_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_add_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position={
                "id": "fresh-seat",
                "name": "Fresh Seat",
                "summary": "a newly added position",
            },
        )

    assert "+position:fresh-seat" in receipt["applied_fields"]
    assert receipt["version_after"] == "2.0.1"
    new_content = fake.table.return_value.update.call_args[0][0]["content"]
    ids = [it["id"] for it in new_content["items"] if isinstance(it, dict)]
    assert "fresh-seat" in ids
    # Type defaulted when absent
    new_item = next(it for it in new_content["items"] if it.get("id") == "fresh-seat")
    assert new_item["type"] == "orgdef:Position"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_add_position_rejects_duplicate_id(_mock_role):
    from server.tool_impls import tool_add_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="already exists"):
            await tool_add_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position={"id": "implementer", "name": "Dupe"},
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_add_position_rejects_wrong_type(_mock_role):
    from server.tool_impls import tool_add_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="type"):
            await tool_add_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position={"id": "x", "name": "x", "type": "roledef:Job"},
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_add_position_rejects_missing_name(_mock_role):
    from server.tool_impls import tool_add_position_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="name"):
            await tool_add_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position={"id": "x"},
            )


# --- delete_position -------------------------------------------------------


def _build_supabase_for_delete(
    has_incumbent=False,
    has_active_sessions=False,
    content=None,
    audit_id="audit-uuid",
):
    """Build a Supabase mock that responds differently to incumbents
    and auth_sessions queries (which delete_position uses for its
    block-when-claimed check)."""
    client = MagicMock()

    org_table = MagicMock()
    roles_table = MagicMock()
    incumbents_table = MagicMock()
    sessions_table = MagicMock()
    audit_table = MagicMock()

    def table_dispatch(name):
        return {
            "roles": roles_table,
            "org_artifacts": org_table,
            "incumbents": incumbents_table,
            "auth_sessions": sessions_table,
            "org_artifact_edits": audit_table,
        }.get(name, MagicMock())

    client.table.side_effect = table_dispatch

    # roles → account_id
    roles_table.select.return_value.eq.return_value.execute.return_value.data = [
        {"account_id": "acct-uuid"}
    ]

    # org_artifacts edit-load chain
    artifact_content = content if content is not None else dict(VALID_OPENCATALOG)
    org_table.select.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = [{
        "id": "art-uuid",
        "account_id": "acct-uuid",
        "org_slug": "thingalog",
        "content": artifact_content,
        "version": "2.0.0",
        "created_at": "2026-05-10T00:00:00Z",
        "updated_at": "2026-05-10T00:00:00Z",
    }]
    org_table.update.return_value.eq.return_value.execute.return_value.data = [{"id": "art-uuid"}]

    # incumbents lookup
    incumbent_data = (
        [{"id": "inc-uuid", "claimed_role_id": "bound-role-uuid"}]
        if has_incumbent else []
    )
    incumbents_table.select.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = incumbent_data

    # auth_sessions lookup (4-stage chain: select.eq.is_.gt)
    sessions_data = [{"id": "s1"}, {"id": "s2"}] if has_active_sessions else []
    sessions_table.select.return_value.eq.return_value.is_.return_value.gt.return_value.execute.return_value.data = sessions_data

    # audit insert
    audit_table.insert.return_value.execute.return_value.data = [{"id": audit_id}]

    return client


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_delete_position_pure_data_succeeds(_mock_role):
    """No incumbents row → straightforward delete + relationships
    cleanup."""
    from server.tool_impls import tool_delete_position_impl

    # Seed with a relationships entry pointing at the doomed position
    seeded = dict(VALID_OPENCATALOG)
    seeded["relationships"] = [
        {"type": "reports_to", "from": "implementer", "to": "product-owner"},
        {"type": "coordinates_with", "from": "implementer", "to": "external:x"},
    ]
    fake = _build_supabase_for_delete(has_incumbent=False, content=seeded)
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_delete_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position_id="implementer",
        )

    assert "-position:implementer" in receipt["applied_fields"]
    assert "-edges:2" in receipt["applied_fields"]
    new_content = fake.table("org_artifacts").update.call_args[0][0]["content"]
    ids = [it["id"] for it in new_content["items"]]
    assert "implementer" not in ids
    # Relationships referencing the deleted position are gone
    rels = new_content["relationships"]
    assert all(r["from"] != "implementer" and r["to"] != "implementer" for r in rels)


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_delete_position_blocks_when_active_sessions(_mock_role):
    """Strategist's block-when-claimed rule: a live incumbents binding
    with active auth_sessions rejects the delete with a friendly error."""
    from server.tool_impls import tool_delete_position_impl

    fake = _build_supabase_for_delete(
        has_incumbent=True, has_active_sessions=True,
    )
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="active session"):
            await tool_delete_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="implementer",
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_delete_position_allows_with_binding_but_no_sessions(_mock_role):
    """A bound role with zero active sessions can still be deleted —
    the incumbents row exists but no AI is currently inhabiting."""
    from server.tool_impls import tool_delete_position_impl

    fake = _build_supabase_for_delete(
        has_incumbent=True, has_active_sessions=False,
    )
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_delete_position_impl(
            session_token="tok",
            org_slug="thingalog",
            position_id="implementer",
        )

    assert "-position:implementer" in receipt["applied_fields"]


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_delete_position_404s_on_unknown_id(_mock_role):
    from server.tool_impls import tool_delete_position_impl

    fake = _build_supabase_for_delete(has_incumbent=False)
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="No Position item"):
            await tool_delete_position_impl(
                session_token="tok",
                org_slug="thingalog",
                position_id="ghost",
            )


# --- update_relationship ---------------------------------------------------


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_add_appends_edge(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_relationship_impl(
            session_token="tok",
            org_slug="thingalog",
            rtype="reports_to",
            from_id="implementer",
            to_id="product-owner",
            op="add",
        )

    assert "+edge:reports_to:implementer->product-owner" in receipt["applied_fields"]
    new_content = fake.table.return_value.update.call_args[0][0]["content"]
    rels = new_content["relationships"]
    assert any(
        r.get("type") == "reports_to"
        and r.get("from") == "implementer"
        and r.get("to") == "product-owner"
        for r in rels
    )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_add_idempotent_when_edge_exists(_mock_role):
    """Adding an edge that already exists is a successful no-op —
    no version bump, no audit row, no applied_fields entries."""
    from server.tool_impls import tool_update_relationship_impl

    seeded = dict(VALID_OPENCATALOG)
    seeded["relationships"] = [
        {"type": "reports_to", "from": "implementer", "to": "product-owner"},
    ]
    fake = _build_supabase(content=seeded)
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_relationship_impl(
            session_token="tok",
            org_slug="thingalog",
            rtype="reports_to",
            from_id="implementer",
            to_id="product-owner",
            op="add",
        )

    assert receipt["version_after"] == receipt["version_before"]
    assert receipt["applied_fields"] == []
    assert receipt["edit_log_id"] is None


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_remove_drops_matching_edge(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    seeded = dict(VALID_OPENCATALOG)
    seeded["relationships"] = [
        {"type": "reports_to", "from": "implementer", "to": "product-owner"},
        {"type": "coordinates_with", "from": "implementer", "to": "product-owner"},
    ]
    fake = _build_supabase(content=seeded)
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_relationship_impl(
            session_token="tok",
            org_slug="thingalog",
            rtype="reports_to",
            from_id="implementer",
            to_id="product-owner",
            op="remove",
        )

    assert "-edge:reports_to:implementer->product-owner" in receipt["applied_fields"]
    new_content = fake.table.return_value.update.call_args[0][0]["content"]
    rels = new_content["relationships"]
    # The coordinates_with one survives
    assert len(rels) == 1
    assert rels[0]["type"] == "coordinates_with"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_remove_idempotent_when_absent(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_relationship_impl(
            session_token="tok",
            org_slug="thingalog",
            rtype="reports_to",
            from_id="implementer",
            to_id="product-owner",
            op="remove",
        )

    assert receipt["applied_fields"] == []
    assert receipt["edit_log_id"] is None


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_rejects_unknown_rtype(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="rtype must be one of"):
            await tool_update_relationship_impl(
                session_token="tok",
                org_slug="thingalog",
                rtype="invented_type",
                from_id="implementer",
                to_id="product-owner",
                op="add",
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_add_rejects_dangling_endpoint(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="does not resolve"):
            await tool_update_relationship_impl(
                session_token="tok",
                org_slug="thingalog",
                rtype="reports_to",
                from_id="ghost-position",
                to_id="product-owner",
                op="add",
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_add_accepts_external_endpoint(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_relationship_impl(
            session_token="tok",
            org_slug="thingalog",
            rtype="coordinates_with",
            from_id="implementer",
            to_id="external:other-org",
            op="add",
        )

    assert any("external:other-org" in f for f in receipt["applied_fields"])


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_add_accepts_org_self_endpoint(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        receipt = await tool_update_relationship_impl(
            session_token="tok",
            org_slug="thingalog",
            rtype="implements_for",
            from_id="thingalog",
            to_id="external:catdef-org",
            op="add",
        )

    assert any("thingalog->external:catdef-org" in f for f in receipt["applied_fields"])


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_update_relationship_rejects_unknown_op(_mock_role):
    from server.tool_impls import tool_update_relationship_impl

    fake = _build_supabase()
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="op must be"):
            await tool_update_relationship_impl(
                session_token="tok",
                org_slug="thingalog",
                rtype="reports_to",
                from_id="implementer",
                to_id="product-owner",
                op="set",
            )


# --- claim_org_create ------------------------------------------------------


async def test_claim_org_create_rejects_unknown_handle():
    from server.tool_impls import tool_claim_org_create_impl

    with patch("server.tool_impls.account_by_handle", return_value=None):
        with pytest.raises(ValueError, match="No openbraid account"):
            await tool_claim_org_create_impl(
                account_handle="ghost",
                claim_what="test",
                client_session_id="cs",
            )


async def test_claim_org_create_issues_pin_against_synthetic_role():
    """Resolves account → ensures synthetic bootstrap role exists →
    inserts pin_challenges row → returns challenge_id + relay
    instruction. End-to-end with mocked db."""
    from server import tool_impls

    fake_account = {"id": "acct-uuid"}

    fake_sb = MagicMock()
    fake_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "challenge-uuid", "expires_at": "2026-05-11T20:00:00+00:00"}
    ]

    with patch.object(tool_impls, "account_by_handle", return_value=fake_account), \
         patch.object(tool_impls, "ensure_org_create_role", return_value="bootstrap-role-uuid"), \
         patch.object(tool_impls, "supabase", return_value=fake_sb), \
         patch.object(tool_impls, "generate_pin", return_value="123456789"):
        result = await tool_impls.tool_claim_org_create_impl(
            account_handle="newuser",
            claim_what="Create org",
            client_session_id="cs-1",
        )

    assert result["challenge_id"] == "challenge-uuid"
    assert "openbraid panel" in result["message"]
    # Verify pin_challenges insert carried the synthetic role id + the
    # client session id (so audit ties back to the originating session).
    insert_call = fake_sb.table.return_value.insert.call_args[0][0]
    assert insert_call["role_id"] == "bootstrap-role-uuid"
    assert insert_call["client_session_id"] == "cs-1"
    assert insert_call["pin"] == "123456789"
    assert insert_call["claim_what"] == "Create org"


async def test_claim_org_create_rejects_empty_handle():
    from server.tool_impls import tool_claim_org_create_impl

    with pytest.raises(ValueError, match="non-empty string"):
        await tool_claim_org_create_impl(
            account_handle="",
            claim_what="test",
            client_session_id="cs",
        )
