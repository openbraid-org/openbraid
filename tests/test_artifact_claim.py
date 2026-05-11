"""Tests for Phase F F0: artifact-position claimability.

Covers:
- resolve_position_url: artifact path creates a synthetic role + incumbents
  binding on first call; reuses on second call (idempotent)
- resolve_position_url: legacy fallback when no artifact matches
- boot payload incumbent block reshapes when a binding exists
- claim_role end-to-end for artifact URL goes through the new path

Supabase is mocked end-to-end.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


ARTIFACT_ROW = {
    "id": "art-uuid-thingalog",
    "account_id": "acct-uuid",
    "org_slug": "thingalog",
    "content": {
        "id": "thingalog",
        "name": "Thingalog",
        "version": "2.0.0",
        "items": [
            {
                "type": "orgdef:Position",
                "id": "implementer",
                "name": "Implementer",
                "role_definition": {
                    "id": "senior-project-oriented-software-engineer",
                    "version": "1.0.0",
                    "url": "https://roledef.org/r.openthing",
                },
            },
        ],
    },
    "version": "2.0.0",
}

ACCOUNT_ROW = {
    "id": "acct-uuid",
    "email": "scott@confusedgorilla.com",
    "auth_user_id": "x",
    "created_at": "2026-05-08T00:00:00Z",
}


# --- ensure_artifact_bound_role: idempotent binding creation ----------------


def test_ensure_artifact_bound_role_creates_on_first_call():
    from server import db

    fake = MagicMock()
    # incumbents lookup → empty (no existing binding)
    incumbents_chain = (
        fake.table.return_value.select.return_value
        .eq.return_value.eq.return_value.is_.return_value
    )
    incumbents_chain.execute.return_value.data = []
    # roles insert → returns new row
    fake.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "new-role-uuid"}
    ]

    with patch.object(db, "supabase", return_value=fake):
        role_id, role_name = db.ensure_artifact_bound_role(
            account_id="acct-uuid",
            account_handle="scott",
            artifact=ARTIFACT_ROW,
            position_item=ARTIFACT_ROW["content"]["items"][0],
        )

    assert role_id == "new-role-uuid"
    assert role_name == "scott/thingalog/implementer"
    # Verify a role insert happened with the synthetic name + roledef_url
    role_insert_calls = [
        c for c in fake.table.return_value.insert.call_args_list
        if c[0][0].get("name") == "scott/thingalog/implementer"
    ]
    assert len(role_insert_calls) == 1
    role_payload = role_insert_calls[0][0][0]
    assert role_payload["account_id"] == "acct-uuid"
    assert role_payload["roledef_url"] == "https://roledef.org/r.openthing"
    # Verify an incumbents insert happened with the binding
    incumbent_insert_calls = [
        c for c in fake.table.return_value.insert.call_args_list
        if "org_artifact_id" in c[0][0]
    ]
    assert len(incumbent_insert_calls) == 1
    binding = incumbent_insert_calls[0][0][0]
    assert binding["org_artifact_id"] == "art-uuid-thingalog"
    assert binding["position_id"] == "implementer"
    assert binding["claimed_role_id"] == "new-role-uuid"


def test_ensure_artifact_bound_role_reuses_existing_binding():
    """Second claim of the same artifact position returns the same role,
    does not create a new one. The seat is shareable across sessions
    via auth_sessions on the bound role (multi-occupant per F0 design)."""
    from server import db

    fake = MagicMock()
    # incumbents lookup → returns existing binding
    incumbents_chain = (
        fake.table.return_value.select.return_value
        .eq.return_value.eq.return_value.is_.return_value
    )
    incumbents_chain.execute.return_value.data = [
        {
            "id": "incumbent-uuid",
            "org_artifact_id": "art-uuid-thingalog",
            "position_id": "implementer",
            "claimed_role_id": "existing-role-uuid",
            "account_id": "acct-uuid",
            "created_at": "2026-05-10T20:00:00Z",
            "ended_at": None,
        }
    ]
    # roles lookup by id → returns the canonical synthetic name
    roles_chain = fake.table.return_value.select.return_value.eq.return_value
    roles_chain.execute.return_value.data = [{"name": "scott/thingalog/implementer"}]

    with patch.object(db, "supabase", return_value=fake):
        role_id, role_name = db.ensure_artifact_bound_role(
            account_id="acct-uuid",
            account_handle="scott",
            artifact=ARTIFACT_ROW,
            position_item=ARTIFACT_ROW["content"]["items"][0],
        )

    assert role_id == "existing-role-uuid"
    assert role_name == "scott/thingalog/implementer"
    # Verify no role-insert and no incumbents-insert occurred
    insert_calls = fake.table.return_value.insert.call_args_list
    assert len(insert_calls) == 0


# --- resolve_position_url routing -------------------------------------------


def test_resolve_position_url_artifact_path_creates_synthetic_role():
    from server import db

    with patch.object(db, "account_by_handle", return_value=ACCOUNT_ROW), \
         patch.object(db, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW), \
         patch.object(db, "ensure_artifact_bound_role",
                      return_value=("synth-role-uuid", "scott/thingalog/implementer")):
        role_id, email, role_name = db.resolve_position_url(
            "https://mcp.openbraid.app/scott/thingalog/implementer"
        )

    assert role_id == "synth-role-uuid"
    assert email == "scott@confusedgorilla.com"
    assert role_name == "scott/thingalog/implementer"


def test_resolve_position_url_falls_back_to_legacy_when_no_artifact():
    """Legacy URLs like /scott/personal/personal-strategist still route
    through orgs + roles tables when no artifact exists for the slug."""
    from server import db

    legacy_org = {"id": "org-uuid", "name": "personal"}
    legacy_position = {
        "id": "legacy-role-uuid",
        "name": "scott/personal/personal-strategist",
    }
    with patch.object(db, "account_by_handle", return_value=ACCOUNT_ROW), \
         patch.object(db, "artifact_by_account_and_slug", return_value=None), \
         patch.object(db, "org_by_name", return_value=legacy_org), \
         patch.object(db, "position_by_canonical_name", return_value=legacy_position):
        role_id, email, role_name = db.resolve_position_url(
            "https://mcp.openbraid.app/scott/personal/personal-strategist"
        )

    assert role_id == "legacy-role-uuid"
    assert role_name == "scott/personal/personal-strategist"


def test_resolve_position_url_artifact_path_404s_if_position_not_in_items():
    """If the artifact exists but the requested position id is not an
    item, fall through to legacy path (which then 404s with a legacy
    error message)."""
    from server import db

    with patch.object(db, "account_by_handle", return_value=ACCOUNT_ROW), \
         patch.object(db, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW), \
         patch.object(db, "org_by_name", return_value=None):
        with pytest.raises(ValueError, match="No org 'thingalog'"):
            db.resolve_position_url(
                "https://mcp.openbraid.app/scott/thingalog/does-not-exist"
            )


# --- boot payload incumbent block -------------------------------------------


def test_boot_payload_incumbent_block_when_bound():
    """A position with a live incumbents binding emits
    type=ai-session-arc with role_id and active_session_count."""
    from server import boot_url

    fake_account = ACCOUNT_ROW
    incumbent_row = {
        "id": "incumbent-uuid",
        "claimed_role_id": "bound-role-uuid",
        "created_at": "2026-05-10T20:00:00Z",
    }
    fake_supabase = MagicMock()
    # inbox_unread count
    inbox_chain = (
        fake_supabase.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value.is_.return_value
    )
    inbox_chain.execute.return_value.data = [{"id": "m1"}, {"id": "m2"}]
    # notes_count
    notes_chain = (
        fake_supabase.table.return_value.select.return_value
        .eq.return_value.eq.return_value.is_.return_value
    )
    notes_chain.execute.return_value.data = [{"id": "n1"}]

    async def _stub_resolve(url):
        return ({"type": "roledef:Role"}, None)

    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW), \
         patch.object(boot_url, "resolve_roledef", side_effect=_stub_resolve), \
         patch.object(boot_url, "incumbent_by_artifact_position", return_value=incumbent_row), \
         patch.object(boot_url, "active_session_count_for_role", return_value=3), \
         patch.object(boot_url, "supabase", return_value=fake_supabase):

        from starlette.requests import Request

        scope = {
            "type": "http", "method": "GET",
            "path_params": {"account": "scott", "org": "thingalog", "position": "implementer"},
            "scheme": "https",
            "server": ("mcp.openbraid.app", 443),
            "headers": [(b"host", b"mcp.openbraid.app")],
            "query_string": b"", "path": "/", "raw_path": b"/",
        }
        request = Request(scope)
        response = await_helper(boot_url.position_boot_endpoint(request))

    import json
    body = json.loads(response.body)
    assert body["incumbent"]["type"] == "ai-session-arc"
    assert body["incumbent"]["claimable"] is True  # multi-occupant
    assert body["incumbent"]["role_id"] == "bound-role-uuid"
    assert body["incumbent"]["active_session_count"] == 3


def await_helper(coro):
    """Run an async coroutine synchronously for tests that aren't
    declared async (pytest-asyncio handles `async def test_…` but this
    inner test uses sync test boundaries). Spins a fresh event loop."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
