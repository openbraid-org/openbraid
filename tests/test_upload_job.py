"""Unit tests for `tool_upload_job_impl` (Phase E E2).

Covers:
- catdef envelope validation (catdef / roledef / type fields)
- roledef MUST-field validation (id / name / version)
- type-must-be-roledef:Job gate
- parent-org gate: rejects upload when the org_artifact doesn't exist
- insert path (no existing job)
- update path (existing job_artifacts row for same parent+job_id)

Supabase is mocked end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

VALID_JOB = {
    "catdef": "1.4",
    "roledef": "0.2.0",
    "type": "roledef:Job",
    "id": "implementer",
    "name": "Implementer for Thingalog",
    "version": "1.0.0",
    "charter": "test charter",
    "identity": "test identity",
    "voice": "test voice",
    "output_contract": [],
}


def _build_supabase_for_upload_job(
    parent_org_artifact_id: str | None = "org-uuid-thingalog",
    existing_job=None,
):
    """Build a mock Supabase client wired for upload_job's chained calls.

    Three distinct query patterns:
      1. roles lookup: .select("account_id").eq("id", X).execute()
      2. org_artifacts parent lookup: .select.eq.eq.is_.execute()
      3. job_artifacts existing lookup: same .select.eq.eq.is_.execute()
      4. insert OR update: .insert.execute() or .update.eq.execute()

    Patterns (2) and (3) collide in MagicMock's call resolution; we
    set the same chain to return different values based on the table
    that's currently being addressed via a side_effect on .table().
    """
    client = MagicMock()

    org_table = MagicMock()
    job_table = MagicMock()
    roles_table = MagicMock()

    def table_dispatch(name):
        if name == "roles":
            return roles_table
        if name == "org_artifacts":
            return org_table
        if name == "job_artifacts":
            return job_table
        return MagicMock()

    client.table.side_effect = table_dispatch

    # roles: .select(...).eq(...).execute()
    roles_chain = roles_table.select.return_value.eq.return_value
    roles_chain.execute.return_value.data = [{"account_id": "acct-uuid-123"}]

    # org_artifacts parent lookup: .select.eq.eq.is_.execute()
    org_parent_chain = (
        org_table.select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
    )
    org_parent_chain.execute.return_value.data = (
        [{"id": parent_org_artifact_id}] if parent_org_artifact_id else []
    )

    # job_artifacts existing lookup
    job_existing_chain = (
        job_table.select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
    )
    job_existing_chain.execute.return_value.data = (
        [existing_job] if existing_job else []
    )

    # job_artifacts insert: .insert().execute()
    job_table.insert.return_value.execute.return_value.data = [
        {"id": "job-artifact-uuid-new"}
    ]

    # job_artifacts update: .update().eq().execute()
    job_update_chain = job_table.update.return_value.eq.return_value
    job_update_chain.execute.return_value.data = [
        {"id": "job-artifact-uuid-existing"}
    ]

    return client, job_table


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_inserts_new_job_when_none_exists(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    fake, job_table = _build_supabase_for_upload_job()
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_job_impl(
            session_token="tok",
            org_slug="thingalog",
            content=VALID_JOB,
        )

    assert result["artifact_id"] == "job-artifact-uuid-new"
    assert result["org_slug"] == "thingalog"
    assert result["job_id"] == "implementer"
    assert result["version"] == "1.0.0"
    assert result["byte_count"] > 0
    insert_call = job_table.insert.call_args
    inserted = insert_call[0][0]
    assert inserted["org_artifact_id"] == "org-uuid-thingalog"
    assert inserted["job_id"] == "implementer"
    assert inserted["content"] == VALID_JOB


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_updates_existing_job_when_id_matches(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    fake, job_table = _build_supabase_for_upload_job(
        existing_job={"id": "job-artifact-uuid-existing"}
    )
    with patch("server.tool_impls.supabase", return_value=fake):
        result = await tool_upload_job_impl(
            session_token="tok",
            org_slug="thingalog",
            content=VALID_JOB,
        )

    assert result["artifact_id"] == "job-artifact-uuid-existing"
    job_table.insert.assert_not_called()
    job_table.update.assert_called_once()


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_rejects_when_parent_org_missing(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    fake, _ = _build_supabase_for_upload_job(parent_org_artifact_id=None)
    with patch("server.tool_impls.supabase", return_value=fake):
        with pytest.raises(ValueError, match="No org artifact found"):
            await tool_upload_job_impl(
                session_token="tok",
                org_slug="thingalog",
                content=VALID_JOB,
            )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_rejects_wrong_type(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    bad = {**VALID_JOB, "type": "orgdef:Organization"}
    with pytest.raises(ValueError, match="roledef:Job"):
        await tool_upload_job_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_rejects_missing_roledef_field(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    bad = {k: v for k, v in VALID_JOB.items() if k != "roledef"}
    with pytest.raises(ValueError, match="roledef"):
        await tool_upload_job_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_rejects_missing_id_field(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    bad = {k: v for k, v in VALID_JOB.items() if k != "id"}
    with pytest.raises(ValueError, match="'id'"):
        await tool_upload_job_impl(
            session_token="tok",
            org_slug="thingalog",
            content=bad,
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_rejects_non_dict_content(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    with pytest.raises(ValueError, match="JSON object"):
        await tool_upload_job_impl(
            session_token="tok",
            org_slug="thingalog",
            content="not a dict",  # type: ignore[arg-type]
        )


@patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid")
async def test_upload_job_rejects_slug_with_slash(_mock_role):
    from server.tool_impls import tool_upload_job_impl

    with pytest.raises(ValueError, match="must not contain"):
        await tool_upload_job_impl(
            session_token="tok",
            org_slug="bad/slug",
            content=VALID_JOB,
        )
