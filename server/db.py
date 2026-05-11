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


RESERVED_HANDLES = frozenset({"mcp", "api"})


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


_ORG_COLUMNS = (
    "id, name, mission, vision, scope, governance_model, "
    "org_location, created_at"
)


def orgs_for_account(account_id: str) -> list[dict]:
    """Return all live orgs for the account, ordered by created_at asc."""
    result = (
        supabase()
        .table("orgs")
        .select(_ORG_COLUMNS)
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
        .select(_ORG_COLUMNS)
        .eq("account_id", account_id)
        .eq("name", org_name)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


def position_by_name(org_id: str, position_name: str) -> dict | None:
    """Resolve a legacy role by (org_id, position_name).

    Phase F F0 migration unified role naming on
    `<account_handle>/<org_slug>/<position_id>` (canonical URL form;
    migration 0010 rewrote all legacy names). This helper joins the
    org → account to compute the expected canonical name from the
    short position_name the URL parser produced, then does the lookup.
    """
    sb = supabase()
    org_row = (
        sb.table("orgs")
        .select("name, account_id")
        .eq("id", org_id)
        .execute()
    )
    if not org_row.data:
        return None
    org = org_row.data[0]
    acct_row = (
        sb.table("accounts")
        .select("email")
        .eq("id", org["account_id"])
        .execute()
    )
    if not acct_row.data:
        return None
    handle = acct_row.data[0]["email"].split("@", 1)[0]
    canonical_name = f"{handle}/{org['name']}/{position_name}"
    return position_by_canonical_name(org_id, canonical_name)


def position_by_canonical_name(org_id: str, canonical_name: str) -> dict | None:
    """Lookup a role by its post-0010 canonical name within an org."""
    result = (
        supabase()
        .table("roles")
        .select("id, name, roledef_url, created_at, org_id, account_id")
        .eq("org_id", org_id)
        .eq("name", canonical_name)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


_ARTIFACT_COLUMNS = (
    "id, account_id, org_slug, content, version, created_at, updated_at"
)


def artifact_by_account_and_slug(account_id: str, org_slug: str) -> dict | None:
    """Return the live `org_artifacts` row for (account_id, org_slug), or None.

    Phase E E1-cutover: boot URL handlers call this first; if it returns
    a row, the boot payload derives from the artifact's `content` (the
    canonical orgdef.openthing JSON). If None, handlers fall back to
    the legacy `orgs`/`roles` read path.
    """
    result = (
        supabase()
        .table("org_artifacts")
        .select(_ARTIFACT_COLUMNS)
        .eq("account_id", account_id)
        .eq("org_slug", org_slug)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


def artifacts_for_account(account_id: str) -> list[dict]:
    """Return all live `org_artifacts` rows for an account, ordered by created_at asc."""
    result = (
        supabase()
        .table("org_artifacts")
        .select(_ARTIFACT_COLUMNS)
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def find_position_in_artifact(content: dict, position_name: str) -> dict | None:
    """Find a position in an .opencatalog artifact's items[] by id or name.

    Per orgdef SCHEMA v1.0.0 the content carries an `items[]` array of
    type-tagged entries; positions are items with `type ==
    "orgdef:Position"`. The SCHEMA addresses positions by `id`; URL
    handlers accept either id or name for friendliness. First match
    wins.
    """
    items = content.get("items") or []
    if not isinstance(items, list):
        return None
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("type") != "orgdef:Position":
            continue
        if it.get("id") == position_name or it.get("name") == position_name:
            return it
    return None


def find_job_in_artifact(content: dict, job_id: str) -> dict | None:
    """Find a roledef:Job item in an .opencatalog by id.

    Phase E opencatalog-refactor: positions reference jobs via
    `job_definition.id`; the boot payload looks up the job inside the
    SAME bundle's items[] array. Returns None if no matching Job item.
    """
    items = content.get("items") or []
    if not isinstance(items, list):
        return None
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("type") != "roledef:Job":
            continue
        if it.get("id") == job_id:
            return it
    return None


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

    Used by claim_role's URL form. Tries the artifact path first (the
    canonical store as of Phase E); falls back to legacy roles/orgs
    tables when no artifact matches.

    Artifact path (Phase F F0):
      - URL parses to (handle, org_slug, position_id)
      - account lookup → account row
      - org_artifacts(account_id, org_slug) → artifact row
      - find_position_in_artifact(content, position_id) → position item
      - ensure_artifact_bound_role(...) → role_id (creates synthetic
        role + incumbents binding on first claim; reuses on subsequent
        claims of the same seat)

    Legacy path:
      - URL parses to (handle, org_name, position_name)
      - orgs(account_id, name) → org row
      - roles(org_id, name) → role row

    Raises ValueError on any resolution failure with a user-presentable
    message (account not found, org/artifact not found, position not
    found, etc.) so the AI client can act on the error.
    """
    handle, org_name, position_name = parse_position_url(url)

    account = account_by_handle(handle)
    if not account:
        raise ValueError(f"No account found for handle '{handle}'")

    # Determine the effective org slug. For two-segment sugar we still
    # require exactly one org under the account; "org" here means
    # either an artifact OR a legacy orgs row.
    if org_name is None:
        artifacts = artifacts_for_account(account["id"])
        legacy_orgs = orgs_for_account(account["id"])
        candidate_slugs = {a["org_slug"] for a in artifacts} | {
            o["name"] for o in legacy_orgs
        }
        if len(candidate_slugs) != 1:
            raise ValueError(
                f"Two-segment URL form requires the account to host exactly "
                f"one org; account '{handle}' hosts {len(candidate_slugs)}. "
                f"Use the three-segment form: "
                f"/<account>/<org>/{position_name}"
            )
        effective_org_slug = next(iter(candidate_slugs))
    else:
        effective_org_slug = org_name

    # Artifact path first: this is the canonical store as of Phase E.
    artifact = artifact_by_account_and_slug(account["id"], effective_org_slug)
    if artifact:
        position_item = find_position_in_artifact(artifact["content"], position_name)
        if position_item:
            role_id, role_name = ensure_artifact_bound_role(
                account_id=account["id"],
                account_handle=handle,
                artifact=artifact,
                position_item=position_item,
            )
            return role_id, account["email"], role_name

    # Legacy fallback: pre-Phase-E orgs/roles tables.
    org = org_by_name(account["id"], effective_org_slug)
    if not org:
        raise ValueError(
            f"No org '{effective_org_slug}' found for account '{handle}'"
        )

    canonical_name = f"{handle}/{org['name']}/{position_name}"
    position = position_by_canonical_name(org["id"], canonical_name)
    if not position:
        raise ValueError(
            f"No position '{position_name}' found in org '{org['name']}' "
            f"for account '{handle}'"
        )

    return position["id"], account["email"], position["name"]


# --- Phase F F0: artifact-bound incumbents -----------------------------------

_INCUMBENT_COLUMNS = (
    "id, org_artifact_id, position_id, claimed_role_id, account_id, "
    "created_at, ended_at"
)


def incumbent_by_artifact_position(
    org_artifact_id: str, position_id: str
) -> dict | None:
    """Return the live incumbents row for (artifact, position), or None.

    "Live" means ended_at IS NULL. A vacancy (no row, or row with
    ended_at set) means the seat is claimable.
    """
    result = (
        supabase()
        .table("incumbents")
        .select(_INCUMBENT_COLUMNS)
        .eq("org_artifact_id", org_artifact_id)
        .eq("position_id", position_id)
        .is_("ended_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


_ORG_CREATE_SUFFIX = "/__org-create__"


def ensure_org_create_role(account_id: str, account_handle: str) -> str:
    """Return the synthetic org-create role for an account.

    Phase F follow-up — the "Create Organization via AI Agent" flow.
    A fresh account with no orgs (or any account creating a new org)
    needs a session_token to call upload_org, but the normal PIN
    ceremony requires a role to claim. This synthetic role bootstraps
    that: claim it once, get a session_token, use it for upload_org
    + any other account-level operation.

    Name convention: `<handle>/__org-create__`. The double-underscored
    suffix marks it as openbraid-internal infrastructure (rendered
    distinctively in the panel rather than in the main roles list).

    Idempotent — reuses an existing row when present. Subsequent
    `Create Organization via AI Agent` clicks against the same
    account land on the same role and just generate fresh PINs.
    """
    synthetic_name = f"{account_handle}{_ORG_CREATE_SUFFIX}"
    sb = supabase()
    existing = (
        sb.table("roles")
        .select("id, name")
        .eq("account_id", account_id)
        .eq("name", synthetic_name)
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    inserted = (
        sb.table("roles")
        .insert(
            {
                "account_id": account_id,
                "name": synthetic_name,
            }
        )
        .execute()
    )
    return inserted.data[0]["id"]


def is_org_create_role_name(role_name: str) -> bool:
    """True iff the given role name is the synthetic org-create
    bootstrap role (filtered out of /panel/roles main list and shown
    in its own surface instead)."""
    return isinstance(role_name, str) and role_name.endswith(_ORG_CREATE_SUFFIX)


def ensure_artifact_bound_role(
    account_id: str,
    account_handle: str,
    artifact: dict,
    position_item: dict,
) -> tuple[str, str]:
    """Return (role_id, role_name) for an artifact-bound position,
    creating the role + incumbents binding on first claim.

    Synthetic role name convention: `<account_handle>/<org_slug>/<position_id>`
    (e.g. `scott/thingalog/implementer`). The full URL path encodes
    who owns the role and which org+position it is bound to —
    Director's call 2026-05-11 so role rows self-describe under
    future cross-account claim flows.

    Idempotent: if a live incumbents row already exists for this
    artifact+position, returns its claimed_role_id unchanged. If the
    binding doesn't exist, creates the role row first (inheriting
    the roledef URL from position_item.role_definition.url when
    present) then inserts the incumbents row binding them.
    """
    artifact_id = artifact["id"]
    position_id = position_item["id"]

    existing = incumbent_by_artifact_position(artifact_id, position_id)
    if existing:
        role_id = existing["claimed_role_id"]
        role_lookup = (
            supabase()
            .table("roles")
            .select("name")
            .eq("id", role_id)
            .execute()
        )
        if role_lookup.data:
            return role_id, role_lookup.data[0]["name"]
        # Defensive: incumbent row points at a role that no longer
        # exists (shouldn't happen — would imply manual SQL surgery).
        # Fall through to fresh-create.

    org_slug = artifact["org_slug"]
    synthetic_name = f"{account_handle}/{org_slug}/{position_id}"
    role_definition = position_item.get("role_definition")
    roledef_url = (
        role_definition.get("url")
        if isinstance(role_definition, dict)
        else None
    )

    inserted_role = (
        supabase()
        .table("roles")
        .insert(
            {
                "account_id": account_id,
                "name": synthetic_name,
                "roledef_url": roledef_url,
            }
        )
        .execute()
    )
    role_id = inserted_role.data[0]["id"]

    (
        supabase()
        .table("incumbents")
        .insert(
            {
                "org_artifact_id": artifact_id,
                "position_id": position_id,
                "claimed_role_id": role_id,
                "account_id": account_id,
            }
        )
        .execute()
    )

    return role_id, synthetic_name


def active_session_count_for_role(role_id: str) -> int:
    """Count live auth_sessions for a role (not revoked, not expired).

    Used by the boot payload's `incumbent.active_session_count` field
    so a fresh agent can see how busy the seat is before claiming.
    """
    result = (
        supabase()
        .table("auth_sessions")
        .select("id")
        .eq("role_id", role_id)
        .is_("revoked_at", "null")
        .gt("expires_at", "now()")
        .execute()
    )
    return len(result.data or [])


