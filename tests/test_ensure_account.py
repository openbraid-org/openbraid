"""Unit tests for `server.db.ensure_account`.

Verifies the auto-create-accounts-on-email-signup helper handles both
paths: link an existing row (e.g. Director's bootstrap row) by updating
its auth_user_id, or insert a fresh row for a net-new user.

The Supabase client is mocked — these tests run without env vars and
without network. A live integration test against a real Supabase
project belongs in a sibling file marked @pytest.mark.integration; the
v0 verification path is production smoke against the live deploy.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _build_fake_supabase(existing_rows=None, insert_returns_id="new-account-id"):
    """Build a MagicMock that satisfies the chained calls ensure_account makes.

    ensure_account uses three chains against `supabase().table('accounts')`:
      .select('id').eq('email', X).is_('deleted_at', 'null').execute()
      .update({...}).eq('id', X).execute()
      .insert({...}).execute()

    Each chain ends in `.execute()` returning an object with a `.data`
    list attribute. We rig the same MagicMock to support all three.
    """
    client = MagicMock()
    table = client.table.return_value

    select_chain = (
        table.select.return_value.eq.return_value.is_.return_value
    )
    select_chain.execute.return_value.data = existing_rows or []

    update_chain = table.update.return_value.eq.return_value
    update_chain.execute.return_value.data = [{"id": "updated"}]

    insert_chain = table.insert.return_value
    insert_chain.execute.return_value.data = [{"id": insert_returns_id}]

    return client


def test_ensure_account_inserts_new_row_when_email_unknown():
    from server.db import ensure_account

    fake = _build_fake_supabase(existing_rows=[])
    with patch("server.db.supabase", return_value=fake):
        result = ensure_account("alice@example.com", "auth-uuid-123")

    assert result == "new-account-id"
    fake.table.return_value.insert.assert_called_once_with(
        {"email": "alice@example.com", "auth_user_id": "auth-uuid-123"}
    )


def test_ensure_account_links_existing_row_when_email_known():
    from server.db import ensure_account

    fake = _build_fake_supabase(
        existing_rows=[{"id": "existing-bootstrap-id"}]
    )
    with patch("server.db.supabase", return_value=fake):
        result = ensure_account(
            "scott@confusedgorilla.com", "auth-uuid-456"
        )

    assert result == "existing-bootstrap-id"
    # No insert when row already exists
    fake.table.return_value.insert.assert_not_called()
    # Update was called to link the row to the Supabase auth user
    fake.table.return_value.update.assert_called_once_with(
        {"auth_user_id": "auth-uuid-456"}
    )
