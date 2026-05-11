"""Unit tests for `tool_upload_org_impl` (Phase E opencatalog-refactor).

Covers the orgdef SCHEMA v1.0.0 ingest path:
- catdef envelope validation (catdef / orgdef / type fields)
- orgdef MUST-field validation (id / name / version)
- type-must-be-orgdef:Organization gate
- items[] validation (must be array; each item has type + id)
- internal consistency: position.job_definition.id resolves to sibling Job
- internal consistency: relationships endpoints resolve
- org_slug validation
- slug_id_mismatch flag in response
- insert path / update path

Supabase is mocked end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
            "job_definition": {"id": "implementer", "version": "1.0.0"},
        },
        {
            "type": "orgdef:Position",
            "id": "product-owner",
            "name": "Product Owner",
            "status": "staffed",
        },
        {
            "type": "roledef:Job",
            "id": "implementer",
            "name": "Implementer for Thingalog",
            "version": "1.0.0",
            "charter": "test charter",
        },
    ],
    "relationships": [
        {"type": "reports_to", "from": "implementer", "to": "product-owner"},
    ],
}


def _build_supabase_for_upload(existing_artifact=None):
    """Mock Supabase for the upload_org chained call pattern.

    Calls:
      1. roles lookup: .select("account_id").eq("id", X).execute()
      2. org_artifacts existing-lookup: .select.eq.eq.is_.execute()
      3. insert OR update: .insert.execute() / .update.eq.execute()
    """
    client = MagicMock()
    table = client.table.return_value

    roles_chain = table.select.return_value.eq.return_value
    roles_chain.execute.return_value.data = [{"account_id": "acct-uuid-123"}]

    existing_chain = (
        table.select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
    )
    existing_chain.execute.return_value.data = (
        [existing_artifact] if existing_artifact else []
    )

    insert_chain = table.insert.return_value
    insert_chain.execute.return_value.data = [{"id": "artifact-uuid-new"}]

    update_chain = table.update.return_value.eq.return_value
    update_chain.execute.return_value.data = [{"id": "artifact-uuid-existing"}]

    return client


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_inserts_new_opencatalog_when_none_exists(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=VALID_OPENCATALOG,
        )

    assert result["artifact_id"] == "artifact-uuid-new"
    assert result["org_slug"] == "thingalog"
    assert result["version"] == "2.0.0"
    assert result["position_count"] == 2
    assert result["job_count"] == 1
    assert result["role_count"] == 0
    assert result["slug_id_mismatch"] is False
    assert result["byte_count"] > 0
    insert_call = fake.table.return_value.insert.call_args
    inserted = insert_call[0][0]
    assert inserted["account_id"] == "acct-uuid-123"
    assert inserted["org_slug"] == "thingalog"
    assert inserted["content"] == VALID_OPENCATALOG


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
            content=VALID_OPENCATALOG,
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
            org_slug="my-thingalog",
            content=VALID_OPENCATALOG,
        )

    assert result["slug_id_mismatch"] is True


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_counts_role_items(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    with_role = {
        **VALID_OPENCATALOG,
        "items": VALID_OPENCATALOG["items"] + [
            {"type": "roledef:Role", "id": "thingalog-director", "name": "Director"},
        ],
    }
    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=with_role,
        )

    assert result["role_count"] == 1


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_wrong_type(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {**VALID_OPENCATALOG, "type": "orgdef:Library"}
    with pytest.raises(ValueError, match="orgdef:Organization"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_missing_catdef_field(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {k: v for k, v in VALID_OPENCATALOG.items() if k != "catdef"}
    with pytest.raises(ValueError, match="catdef"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_missing_items_array(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {k: v for k, v in VALID_OPENCATALOG.items() if k != "items"}
    with pytest.raises(ValueError, match="items"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_item_missing_type(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {
        **VALID_OPENCATALOG,
        "items": [{"id": "no-type-here"}],
        "relationships": [],
    }
    with pytest.raises(ValueError, match="type"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_item_missing_id(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {
        **VALID_OPENCATALOG,
        "items": [{"type": "orgdef:Position", "name": "no-id"}],
        "relationships": [],
    }
    with pytest.raises(ValueError, match="'id'"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_dangling_job_definition_reference(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {
        **VALID_OPENCATALOG,
        "items": [
            {
                "type": "orgdef:Position",
                "id": "implementer",
                "name": "Implementer",
                "job_definition": {"id": "ghost-job", "version": "1.0.0"},
            },
        ],
        "relationships": [],
    }
    with pytest.raises(ValueError, match="ghost-job"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_accepts_external_job_definition_url(_mock_role):
    """A job_definition with no sibling match but an explicit external
    URL passes consistency (E3-style external resolution)."""
    from server.tool_impls import tool_upload_org_impl

    ok = {
        **VALID_OPENCATALOG,
        "items": [
            {
                "type": "orgdef:Position",
                "id": "implementer",
                "name": "Implementer",
                "job_definition": {
                    "id": "external-job",
                    "version": "1.0.0",
                    "url": "https://other.example/jobs/external-job",
                },
            },
        ],
        "relationships": [],
    }
    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=ok,
        )
    assert result["artifact_id"] == "artifact-uuid-new"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_rejects_dangling_relationship_endpoint(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    bad = {
        **VALID_OPENCATALOG,
        "relationships": [
            {"type": "reports_to", "from": "implementer", "to": "ghost-position"},
        ],
    }
    with pytest.raises(ValueError, match="ghost-position"):
        await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_accepts_external_relationship_endpoint(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    ok = {
        **VALID_OPENCATALOG,
        "relationships": [
            {"type": "coordinates_with", "from": "implementer", "to": "external:other-org"},
        ],
    }
    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=ok,
        )
    assert result["artifact_id"] == "artifact-uuid-new"


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_org_accepts_org_self_id_as_relationship_endpoint(_mock_role):
    from server.tool_impls import tool_upload_org_impl

    ok = {
        **VALID_OPENCATALOG,
        "relationships": [
            {"type": "implements_for", "from": "thingalog", "to": "external:catdef-org"},
        ],
    }
    fake = _build_supabase_for_upload(existing_artifact=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_org_impl(
            session_token="tok",
            org_slug="thingalog",
            content=ok,
        )
    assert result["artifact_id"] == "artifact-uuid-new"


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
            content=VALID_OPENCATALOG,
        )
