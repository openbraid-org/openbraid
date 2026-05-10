"""Unit tests for `server.db.ensure_personal_org`.

Phase C foundation. Every account gets a default 'personal' org during
migration 0004; this helper covers post-migration account creation
where the migration didn't run for that row. Idempotent: returns the
existing org's id on repeat calls.

Mocks the Supabase client; no env vars or network required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _build_fake_supabase(existing_orgs=None, insert_returns_id="new-org-id"):
    """Build a MagicMock that satisfies the chained calls
    ensure_personal_org makes.

    Chain shapes:
      .select('id').eq('account_id', X).eq('name', 'personal').is_('deleted_at', 'null').execute()
      .insert({...}).execute()
    """
    client = MagicMock()
    table = client.table.return_value

    select_chain = (
        table.select.return_value
        .eq.return_value.eq.return_value
        .is_.return_value
    )
    select_chain.execute.return_value.data = existing_orgs or []

    insert_chain = table.insert.return_value
    insert_chain.execute.return_value.data = [{"id": insert_returns_id}]

    return client


def test_ensure_personal_org_returns_existing_when_present():
    from server.db import ensure_personal_org

    fake = _build_fake_supabase(existing_orgs=[{"id": "existing-org-id"}])
    with patch("server.db.supabase", return_value=fake):
        result = ensure_personal_org("acct-uuid")

    assert result == "existing-org-id"
    fake.table.return_value.insert.assert_not_called()


def test_ensure_personal_org_inserts_when_missing():
    from server.db import ensure_personal_org

    fake = _build_fake_supabase(existing_orgs=[])
    with patch("server.db.supabase", return_value=fake):
        result = ensure_personal_org("acct-uuid")

    assert result == "new-org-id"
    fake.table.return_value.insert.assert_called_once_with(
        {"account_id": "acct-uuid", "name": "personal"}
    )
