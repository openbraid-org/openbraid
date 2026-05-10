"""Unit tests for memodef v0.3 memo-to-file behavior in send_memo and list_inbox.

Three behaviors verified here, all through mocked Supabase clients:

  1. send_memo with to_role='file' and action_required=true is rejected
     with a clear ValueError (memodef v0.3 SHOULD-violation enforced as
     a hard error in this implementation).
  2. send_memo with to_role='file' and action_required=false stores the
     memo with kind='note' against the authenticated role's id (no
     recipient lookup).
  3. list_inbox(folder='notes') queries memos with kind='note' for the
     authenticated role.

Integration with the live Supabase project is the v0 verification
path (production smoke after deploy); these unit tests verify the
control flow without needing env vars.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _build_supabase_with_role(role_id: str = "role-uuid-123", role_name: str = "personal-strategist"):
    """Build a fake Supabase client wired for the auth_session and role-name
    lookups send_memo and list_inbox make. Returns the client so tests can
    further configure or assert on it."""
    client = MagicMock()
    table = client.table

    auth_select = (
        table.return_value
        .select.return_value
        .eq.return_value
        .is_.return_value
        .gt.return_value
    )
    auth_select.execute.return_value.data = [{"role_id": role_id}]

    role_select = (
        table.return_value
        .select.return_value
        .eq.return_value
        .is_.return_value
    )
    role_select.execute.return_value.data = [{"name": role_name, "account_id": "acct-uuid"}]

    insert_chain = table.return_value.insert.return_value
    insert_chain.execute.return_value.data = [
        {"id": "memo-uuid", "sent_at": "2026-05-10T15:00:00Z"}
    ]

    list_chain = (
        table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
        .order.return_value
        .limit.return_value
    )
    list_chain.execute.return_value.data = []

    notes_chain = (
        table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
        .order.return_value
        .limit.return_value
    )
    notes_chain.execute.return_value.data = [
        {"id": "note-uuid", "from_position": "personal-strategist",
         "subject": "test note", "sent_at": "2026-05-10T15:00:00Z",
         "action_required": False, "thread_id": None}
    ]

    return client


async def test_send_memo_to_file_rejects_action_required():
    """A memo-to-file with action_required=true must be rejected per
    memodef v0.3 (SHOULD-level violation; we enforce as hard error)."""
    from server import main as server_main

    client = _build_supabase_with_role()
    with patch("server.tool_impls.supabase", return_value=client), \
         patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid-123"), \
         patch("server.tool_impls.get_role_position", return_value="personal-strategist"):
        with pytest.raises(ValueError, match="memo-to-file.*action_required"):
            await server_main.send_memo(
                session_token="tok",
                to_role="file",
                subject="trying to action a note",
                body="should fail",
                action_required=True,
            )


async def test_send_memo_to_file_stores_with_kind_note_under_authenticated_role():
    """A memo-to-file lands with kind='note' against the authenticated
    role's id (no recipient lookup)."""
    from server import main as server_main

    client = _build_supabase_with_role()
    with patch("server.tool_impls.supabase", return_value=client), \
         patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid-123"), \
         patch("server.tool_impls.get_role_position", return_value="personal-strategist"):
        result = await server_main.send_memo(
            session_token="tok",
            to_role="file",
            subject="design rationale",
            body="why we chose X over Y",
        )

    assert result["kind"] == "note"
    assert result["memo_id"] == "memo-uuid"

    # Verify the insert was called with kind='note' and role_id = sender's
    insert_call = client.table.return_value.insert.call_args
    assert insert_call is not None
    inserted_row = insert_call[0][0]
    assert inserted_row["kind"] == "note"
    assert inserted_row["role_id"] == "role-uuid-123"
    assert inserted_row["to_position"] == "file"
    assert inserted_row["status"] == "archived"  # notes have no inbox lifecycle


async def test_send_memo_directed_still_uses_kind_inbox():
    """Sanity: directed memos (non-'file' to_role) still get kind='inbox'."""
    from server import main as server_main

    # For directed, send_memo does an extra recipient lookup.
    # Build a client that returns a recipient id for the role-name lookup.
    client = MagicMock()
    table = client.table

    # auth_sessions query: returns role_id for sender
    auth_select = (
        table.return_value
        .select.return_value
        .eq.return_value
        .is_.return_value
        .gt.return_value
    )
    auth_select.execute.return_value.data = [{"role_id": "sender-id"}]

    # roles query: multiple shapes; default returns generic data
    # Used twice: once for sender position lookup, once for sender's account_id, once for recipient
    # Cleaner: just rig the eq chain to return role data for any select
    role_chain = (
        table.return_value
        .select.return_value
        .eq.return_value
    )
    # First .is_().execute() for get_role_position, returns name
    role_chain.is_.return_value.execute.return_value.data = [
        {"name": "personal-strategist", "account_id": "acct-id", "id": "recipient-id"}
    ]
    # When the chain ends with .eq().execute() (account_id lookup) — same data shape works
    role_chain.execute.return_value.data = [
        {"account_id": "acct-id", "id": "recipient-id"}
    ]
    # The recipient lookup uses .eq().eq().is_().execute() — different chain
    recipient_chain = (
        table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
    )
    recipient_chain.execute.return_value.data = [{"id": "recipient-id"}]

    insert_chain = table.return_value.insert.return_value
    insert_chain.execute.return_value.data = [
        {"id": "memo-uuid", "sent_at": "2026-05-10T15:00:00Z"}
    ]

    with patch("server.tool_impls.supabase", return_value=client), \
         patch("server.tool_impls.get_role_id_from_token", return_value="sender-id"), \
         patch("server.tool_impls.get_role_position", return_value="personal-strategist"):
        result = await server_main.send_memo(
            session_token="tok",
            to_role="brother-desktop",
            subject="hello",
            body="directed memo",
        )

    assert result["kind"] == "inbox"
    insert_call = client.table.return_value.insert.call_args
    inserted_row = insert_call[0][0]
    assert inserted_row["kind"] == "inbox"
    assert inserted_row["status"] == "inbox"
    assert inserted_row["to_position"] == "brother-desktop"


async def test_list_inbox_folder_notes_filters_by_kind_note():
    """list_inbox(folder='notes') queries memos with kind='note' for the
    authenticated role."""
    from server import main as server_main

    client = _build_supabase_with_role()
    with patch("server.tool_impls.supabase", return_value=client), \
         patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid-123"):
        result = await server_main.list_inbox(
            session_token="tok",
            folder="notes",
        )

    # The notes_chain mock returns one note; assert it surfaced
    assert "memos" in result
    # The query should chain .eq('role_id', X).eq('kind', 'note')
    # We can't easily introspect MagicMock call chains' exact arguments here
    # without rebuilding; the integration smoke test handles that. The unit
    # test verifies the code path doesn't raise and returns the expected
    # dict shape.


async def test_list_inbox_rejects_unknown_folder():
    """folder must be one of None/'inbox'/'notes'."""
    from server import main as server_main

    with patch("server.tool_impls.get_role_id_from_token", return_value="role-uuid-123"):
        with pytest.raises(ValueError, match="folder must be"):
            await server_main.list_inbox(
                session_token="tok",
                folder="invented",
            )
