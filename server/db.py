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


def ensure_personal_org(account_id: str) -> str:
    """Idempotently ensure the account has a 'personal' org and return its id.

    Phase C introduced orgs as the layer between accounts and roles (per
    OAGP canonical addressing). Each account gets a default 'personal'
    org during migration 0004; this helper covers the edge case where
    a fresh account was created post-migration without one. Cheap when
    the org already exists (one SELECT); only writes on miss.
    """
    existing = (
        supabase()
        .table("orgs")
        .select("id")
        .eq("account_id", account_id)
        .eq("name", "personal")
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    inserted = (
        supabase()
        .table("orgs")
        .insert({"account_id": account_id, "name": "personal"})
        .execute()
    )
    return inserted.data[0]["id"]


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


RESERVED_HANDLES = frozenset({"mcp"})


def account_by_handle(handle: str) -> dict | None:
    """Resolve a URL handle to an `accounts` row.

    v0 strategy: handle == email-localpart. Returns the first account
    whose email begins with `handle@`. Returns None if no match or if
    the handle is reserved.
    """
    if (
        not handle
        or handle in RESERVED_HANDLES
        or "@" in handle
        or "/" in handle
    ):
        return None
    pattern = f"{handle}@%"
    result = (
        supabase()
        .table("accounts")
        .select("id, email, auth_user_id, created_at")
        .ilike("email", pattern)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def orgs_for_account(account_id: str) -> list[dict]:
    """Return all live orgs for the account, ordered by created_at asc."""
    result = (
        supabase()
        .table("orgs")
        .select(
            "id, name, mission, vision, scope, governance_model, created_at"
        )
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def org_by_name(account_id: str, org_name: str) -> dict | None:
    """Resolve an org by (account_id, name)."""
    result = (
        supabase()
        .table("orgs")
        .select(
            "id, name, mission, vision, scope, governance_model, created_at"
        )
        .eq("account_id", account_id)
        .eq("name", org_name)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


def position_by_name(org_id: str, position_name: str) -> dict | None:
    """Resolve a position (role) by (org_id, name)."""
    result = (
        supabase()
        .table("roles")
        .select("id, name, roledef_url, created_at, org_id, account_id")
        .eq("org_id", org_id)
        .eq("name", position_name)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


def parse_position_url(url: str) -> tuple[str, str | None, str]:
    """Parse a position URL to (handle, org_name | None, position_name).

    Accepts a permissive set of URL shapes per the OAGP canonical
    addressing spec (orgdef-spec ba004ca):

      - With scheme:    https://mcp.openbraid.app/scott/personal/personal-strategist
      - Without scheme: mcp.openbraid.app/scott/personal-strategist
      - Path-only:      /scott/personal/personal-strategist
      - Path-only:      scott/personal-strategist

    Two-segment forms (account_handle + position_name; no org) return
    org_name=None; the resolver decides whether the account's
    implicit-single-org rule applies.

    Raises ValueError if the URL doesn't have 2 or 3 path segments.
    The host (if present) is not validated against the current
    instance's hostname — self-hosted openbraid forks resolve their
    own URLs at their own hosts; for v0 we accept any URL whose path
    parses correctly and let downstream lookups 404 if the account
    doesn't exist on this instance.
    """
    # Strip scheme:// if present.
    if "://" in url:
        url = url.split("://", 1)[1]

    parts = url.lstrip("/").split("/")
    # If the first segment looks like a hostname (contains a dot),
    # treat it as the host and skip it.
    if parts and "." in parts[0]:
        parts = parts[1:]

    parts = [p for p in parts if p]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise ValueError(
        f"Invalid position URL: expected 2 or 3 path segments, got "
        f"{len(parts)}: {url!r}"
    )


def resolve_position_url(url: str) -> tuple[str, str, str]:
    """Resolve a position URL to (role_id, account_email, role_name).

    Used by claim_role's URL form (Phase C C5). Performs the same
    handle / org / position lookups the boot URL endpoints do, but
    returns the three values claim_role's PIN-ceremony path needs.

    Raises ValueError on any resolution failure with a user-presentable
    message (account not found, org not found, position not found, etc.)
    so the AI client can act on the error.
    """
    handle, org_name, position_name = parse_position_url(url)

    account = account_by_handle(handle)
    if not account:
        raise ValueError(f"No account found for handle '{handle}'")

    if org_name is None:
        # Two-segment sugar: account must host exactly one org.
        orgs = orgs_for_account(account["id"])
        if len(orgs) != 1:
            raise ValueError(
                f"Two-segment URL form requires the account to host exactly "
                f"one org; account '{handle}' hosts {len(orgs)}. Use the "
                f"three-segment form: /<account>/<org>/{position_name}"
            )
        org = orgs[0]
    else:
        org = org_by_name(account["id"], org_name)
        if not org:
            raise ValueError(
                f"No org '{org_name}' found for account '{handle}'"
            )

    position = position_by_name(org["id"], position_name)
    if not position:
        raise ValueError(
            f"No position '{position_name}' found in org '{org['name']}' "
            f"for account '{handle}'"
        )

    return position["id"], account["email"], position["name"]


