"""Supabase access layer for the openbraid MCP server.

The server holds the Supabase **service role** key and bypasses RLS — that
is intentional for v0. Application-layer auth (PIN ceremony + session
tokens) is the only access control. RLS policies will land in a follow-on
when the panel reads directly from PostgREST.

Client init is lazy via `supabase()` so importing `server.main` does NOT
require the env vars to be set (contract tests can run without them).
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import cache

from supabase import Client, create_client


@cache
def supabase() -> Client:
    """Return the singleton Supabase client.

    Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from the environment.
    Cached so the connection is established once per process.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def generate_pin() -> str:
    """Generate a 9-digit one-time PIN as a zero-padded string.

    Cryptographically random (secrets.randbelow). The 9-digit space is
    10^9 = 1 billion; with 5-minute TTL and one-shot use the brute-force
    risk is acceptable for v0.
    """
    return f"{secrets.randbelow(10**9):09d}"


def generate_session_token() -> str:
    """Generate a URL-safe session token (~256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def session_expiry(hours: int = 24) -> str:
    """Return an ISO-8601 timestamp for `now + hours`. Default 24h."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def get_role_id_from_token(session_token: str) -> str:
    """Look up an authenticated session and return its role_id.

    Validates: token exists, not revoked, not expired. Raises
    ValueError on any failure (the MCP framework will surface that as
    the tool's error response).
    """
    result = (
        supabase()
        .table("auth_sessions")
        .select("role_id")
        .eq("session_token", session_token)
        .is_("revoked_at", "null")
        .gt("expires_at", "now()")
        .execute()
    )
    if not result.data:
        raise ValueError("Invalid or expired session token")
    return result.data[0]["role_id"]


def get_role_position(role_id: str) -> str:
    """Return a role's name for use as `from_position` on outgoing memos."""
    result = (
        supabase()
        .table("roles")
        .select("name")
        .eq("id", role_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise ValueError(f"Role {role_id} not found")
    return result.data[0]["name"]


def ensure_account(email: str, auth_user_id: str) -> str:
    """Idempotently ensure an `accounts` row exists for the given email.

    Returns the account's id. If a row already exists for the email
    (e.g. the bootstrap row Director seeded manually), this links it
    to the actual Supabase Auth user by updating `auth_user_id` and
    returns the existing id. Otherwise inserts a fresh row and returns
    the new id.

    Used by the email-signup handler so a freshly signed-up user lands
    on a working `/panel` instead of the "No openbraid account found"
    empty state. Not exposed as an MCP tool — purely internal.
    """
    existing = (
        supabase()
        .table("accounts")
        .select("id")
        .eq("email", email)
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        account_id = existing.data[0]["id"]
        supabase().table("accounts").update(
            {"auth_user_id": auth_user_id}
        ).eq("id", account_id).execute()
        return account_id
    inserted = (
        supabase()
        .table("accounts")
        .insert({"email": email, "auth_user_id": auth_user_id})
        .execute()
    )
    return inserted.data[0]["id"]


def resolve_role_by_name(account_email: str, role_name: str) -> str:
    """Return role_id for (account_email, role_name).

    Raises ValueError if either the account or the role is missing.
    """
    account = (
        supabase()
        .table("accounts")
        .select("id")
        .eq("email", account_email)
        .is_("deleted_at", "null")
        .execute()
    )
    if not account.data:
        raise ValueError(f"No account found for {account_email}")
    account_id = account.data[0]["id"]

    role = (
        supabase()
        .table("roles")
        .select("id")
        .eq("account_id", account_id)
        .eq("name", role_name)
        .is_("deleted_at", "null")
        .execute()
    )
    if not role.data:
        raise ValueError(
            f"No role '{role_name}' found for account {account_email}"
        )
    return role.data[0]["id"]
