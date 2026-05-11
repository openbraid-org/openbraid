"""Contract tests for the openbraid MCP tool surface.

These verify the *shape* of each tool — name, parameters, descriptions
— independent of any storage. They are the gate that catches "tool got
renamed" or "parameter dropped" regressions.

Behavioral tests live in sibling files marked `@pytest.mark.integration`
and run against a live Supabase project (skipped by default; production
smoke is the v0 verification path until a test schema lands).
"""

from __future__ import annotations

import pytest

EXPECTED_TOOLS: dict[str, dict[str, set[str]]] = {
    "claim_role": {
        # Phase C C5 simplified to URL-only (single user; clean break
        # from the v0 name+email form per Director's call 2026-05-10).
        "required": {"position_url"},
        "optional": {"claim_what"},
    },
    "claim_org_create": {
        "required": {"account_handle"},
        "optional": {"claim_what"},
    },
    "auth_with_pin": {
        "required": {"challenge_id", "pin"},
        "optional": set(),
    },
    "send_memo": {
        "required": {"session_token", "to_role", "subject", "body"},
        "optional": {"body_ref", "action_required", "in_reply_to", "thread_id"},
    },
    "list_inbox": {
        "required": {"session_token"},
        "optional": {"status", "limit", "folder"},
    },
    "read_memo": {
        "required": {"session_token", "memo_id"},
        "optional": set(),
    },
    "mark_read": {
        "required": {"session_token", "memo_id"},
        "optional": set(),
    },
    "upload_org": {
        "required": {"session_token", "org_slug", "content"},
        "optional": set(),
    },
    "update_position": {
        "required": {"session_token", "org_slug", "position_id", "patch"},
        "optional": {"expected_version"},
    },
    "update_org_metadata": {
        "required": {"session_token", "org_slug", "patch"},
        "optional": {"expected_version"},
    },
    "bump_version": {
        "required": {"session_token", "org_slug"},
        "optional": {"kind", "expected_version"},
    },
    "add_position": {
        "required": {"session_token", "org_slug", "position"},
        "optional": {"expected_version"},
    },
    "delete_position": {
        "required": {"session_token", "org_slug", "position_id"},
        "optional": {"expected_version"},
    },
    "update_relationship": {
        "required": {"session_token", "org_slug", "rtype", "from_id", "to_id"},
        "optional": {"op", "expected_version"},
    },
}


async def _list_tools_by_name(server) -> dict:
    tools = await server.list_tools()
    return {t.name: t for t in tools}


async def test_all_expected_tools_are_registered(server):
    tools = await _list_tools_by_name(server)
    assert set(tools.keys()) == set(EXPECTED_TOOLS.keys()), (
        f"Tool registration mismatch. "
        f"Got: {sorted(tools.keys())}. "
        f"Expected: {sorted(EXPECTED_TOOLS.keys())}."
    )


@pytest.mark.parametrize("tool_name", list(EXPECTED_TOOLS.keys()))
async def test_tool_has_expected_parameters(server, tool_name):
    tools = await _list_tools_by_name(server)
    tool = tools[tool_name]
    schema = tool.parameters

    properties = set(schema.get("properties", {}).keys())
    required = set(schema.get("required", []))

    expected = EXPECTED_TOOLS[tool_name]
    expected_all = expected["required"] | expected["optional"]

    assert properties == expected_all, (
        f"{tool_name} parameter set mismatch. "
        f"Got: {sorted(properties)}. Expected: {sorted(expected_all)}."
    )
    assert required == expected["required"], (
        f"{tool_name} required-parameter set mismatch. "
        f"Got: {sorted(required)}. Expected: {sorted(expected['required'])}."
    )


@pytest.mark.parametrize("tool_name", list(EXPECTED_TOOLS.keys()))
async def test_tool_has_description(server, tool_name):
    """Every tool needs a description so MCP clients (and humans) can
    discover what it does without reading the source."""
    tools = await _list_tools_by_name(server)
    tool = tools[tool_name]
    assert tool.description and tool.description.strip(), (
        f"{tool_name} has no description"
    )
