"""Integration test asserting MCP and REST transports share the same impls.

The strategist's safety net: if either transport stops routing through
the shared helpers in `server.tool_impls`, this test fails — preventing
the MCP/REST drift the Phase D kickoff memo flagged as the central risk.

Strategy: introspect both transports and confirm every tool's
underlying callable is from server.tool_impls. We don't execute the
impls (that needs Supabase); we just verify the routing layer is honest.
"""

from __future__ import annotations

import inspect

from server import tool_impls

EXPECTED_TOOLS = {
    "claim_role": "tool_claim_role_impl",
    "auth_with_pin": "tool_auth_with_pin_impl",
    "send_memo": "tool_send_memo_impl",
    "list_inbox": "tool_list_inbox_impl",
    "read_memo": "tool_read_memo_impl",
    "mark_read": "tool_mark_read_impl",
    "upload_org": "tool_upload_org_impl",
    "update_position": "tool_update_position_impl",
    "update_org_metadata": "tool_update_org_metadata_impl",
    "bump_version": "tool_bump_version_impl",
    "add_position": "tool_add_position_impl",
    "delete_position": "tool_delete_position_impl",
    "update_relationship": "tool_update_relationship_impl",
    "claim_org_create": "tool_claim_org_create_impl",
    "read_org": "tool_read_org_impl",
    "add_job": "tool_add_job_impl",
    "update_job": "tool_update_job_impl",
    "delete_job": "tool_delete_job_impl",
}


def test_all_expected_impls_exist():
    for tool_name, impl_name in EXPECTED_TOOLS.items():
        impl = getattr(tool_impls, impl_name, None)
        assert impl is not None, (
            f"Expected {tool_impls.__name__}.{impl_name} for tool {tool_name}; "
            f"missing. If you split the impl module, this test needs updating."
        )
        assert inspect.iscoroutinefunction(impl), (
            f"{impl_name} must be `async def` (impls are awaited from both "
            f"transports)."
        )


def test_mcp_tool_bodies_reference_their_impl():
    """Source-level check: each FastMCP tool body in server/main.py
    should be a thin wrapper calling its corresponding impl. If a future
    edit reintroduces inline logic in main.py instead of routing
    through tool_impls, this test catches it."""
    import pathlib

    src = pathlib.Path(__file__).parent.parent / "server" / "main.py"
    text = src.read_text(encoding="utf-8")
    for tool_name, impl_name in EXPECTED_TOOLS.items():
        # Each MCP tool function should contain a call to its impl.
        assert f"{impl_name}(" in text, (
            f"server/main.py's `{tool_name}` should call `{impl_name}(...)`; "
            f"not found. If you renamed the impl, update this test."
        )


def test_rest_route_handlers_reference_their_impl():
    """Source-level check parallel to the MCP one."""
    import pathlib

    src = pathlib.Path(__file__).parent.parent / "server" / "rest_api.py"
    text = src.read_text(encoding="utf-8")
    for tool_name, impl_name in EXPECTED_TOOLS.items():
        assert f"{impl_name}(" in text, (
            f"server/rest_api.py's `{tool_name}` route should call "
            f"`{impl_name}(...)`; not found."
        )
