"""Contract tests for the openbraid MCP tool surface.

These verify the *shape* of each tool — name, parameters, return-stub
behavior — independent of any storage. They are the gate that catches
"tool got renamed", "parameter dropped", "stub silently became no-op"
regressions.

Once the tools have real implementations, behavioral tests live in
sibling files (e.g. test_send_memo.py); these contract tests stay focused
on the wire-level contract that an MCP client sees.
"""

from __future__ import annotations

import pytest

from server import main as server_main

EXPECTED_TOOLS: dict[str, dict[str, set[str]]] = {
    "claim_role": {
        "required": {"role_name"},
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
        "optional": {"status", "limit"},
    },
    "read_memo": {
        "required": {"session_token", "memo_id"},
        "optional": set(),
    },
    "mark_read": {
        "required": {"session_token", "memo_id"},
        "optional": set(),
    },
}


async def _list_tools_by_name(server) -> dict:
    tools = await server.list_tools()
    return {t.name: t for t in tools}


async def test_all_six_tools_are_registered(server):
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


async def test_stubs_raise_not_implemented():
    """Confirm every tool is a stub that raises NotImplementedError —
    catches the regression where someone accidentally lands a real
    implementation without updating the test."""
    stub_calls = [
        lambda: server_main.claim_role(role_name="r"),
        lambda: server_main.auth_with_pin(challenge_id="c", pin="123456789"),
        lambda: server_main.send_memo(
            session_token="s", to_role="r", subject="s", body="b"
        ),
        lambda: server_main.list_inbox(session_token="s"),
        lambda: server_main.read_memo(session_token="s", memo_id="m"),
        lambda: server_main.mark_read(session_token="s", memo_id="m"),
    ]
    for call in stub_calls:
        with pytest.raises(NotImplementedError, match="v0 stub"):
            await call()
