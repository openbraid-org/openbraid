"""URL-shaped position addressing per OAGP canonical addressing v1.3.0.

Three-level URL semantics on `mcp.openbraid.app`:

  GET /{account}                       -> ordered list of orgs for the account
  GET /{account}/{seg2}                -> two-segment sugar:
                                          - if account has 1 org: position URL
                                          - else: org URL (positions list)
  GET /{account}/{org}/{position}      -> fresh-agent boot payload

Boot payload shape per orgdef-strategist memo §Boot payload (Director-
ratified verbatim 2026-05-10): position metadata + org_summary +
role_definition + job_definition + incumbent state + inbox_summary +
claim_instruction. SHOULD shape (OQ4); openbraid is implementation #1
so this becomes the de facto template until 2+ implementations exist.

Account resolution: for v0, `{account}` is the email-localpart of the
authenticated openbraid account (Supabase Auth's email field, before
the `@`). Future multi-user scenarios that surface handle collisions
will warrant a dedicated `accounts.handle` column; deferring until
empirical signal.

These endpoints have NO transport-layer auth — read access to a
position's boot context is intentionally public per orgdef OQ2's v0
posture (PIN ceremony for claim, public for read; PUBLIC vs PROTECTED
distinction deferred to a future autonomous-agent-era proposal).
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from server.db import supabase


_RESERVED_HANDLES = frozenset({"mcp"})


def _account_by_handle(handle: str) -> dict | None:
    """Resolve a URL handle to an `accounts` row.

    v0 strategy: handle == email-localpart. Returns the first account
    whose email begins with `handle@`. Returns None if no match or if
    the handle is reserved (e.g., "mcp" — used by the protocol endpoint
    on the bare host).
    """
    if (
        not handle
        or handle in _RESERVED_HANDLES
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


def _orgs_for_account(account_id: str) -> list[dict]:
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


def _org_by_name(account_id: str, org_name: str) -> dict | None:
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


def _positions_for_org(org_id: str) -> list[dict]:
    """Return positions (roles) within an org.

    Phase C C3 calls for depth-first ordering via the orgdef artifact's
    relationships. v0 doesn't store relationships yet, so this falls
    back to the ordering rule the orgdef memo specifies for the
    ambiguous case: the `positions` array order, which we approximate
    by created_at asc (the order they were added).
    """
    result = (
        supabase()
        .table("roles")
        .select("id, name, roledef_url, created_at, org_id")
        .eq("org_id", org_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def _position_by_name(org_id: str, position_name: str) -> dict | None:
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


def _build_boot_payload(
    account: dict, org: dict, position: dict
) -> dict:
    """Build the C4 boot payload for a fresh-agent instantiation.

    Field set is the orgdef-strategist memo's shape verbatim per
    Director's "ship something, fix in v2" ratification. SHOULD-level
    (OQ4); promote to MUST when a 2nd implementation stabilizes.
    """
    sb = supabase()

    # Active session count for this position (tells the caller how many
    # incumbents are currently inhabiting the seat).
    active_sessions = (
        sb.table("auth_sessions")
        .select("id")
        .eq("role_id", position["id"])
        .is_("revoked_at", "null")
        .gt("expires_at", "now()")
        .execute()
    )

    # Inbox summary: counts only, not contents (so an unauthenticated
    # boot reader sees activity-level signal but not memo bodies).
    inbox_unread = (
        sb.table("memos")
        .select("id")
        .eq("role_id", position["id"])
        .eq("kind", "inbox")
        .eq("status", "inbox")
        .is_("deleted_at", "null")
        .execute()
    )
    notes_count = (
        sb.table("memos")
        .select("id")
        .eq("role_id", position["id"])
        .eq("kind", "note")
        .is_("deleted_at", "null")
        .execute()
    )

    return {
        "position": {
            "id": position["id"],
            "name": position["name"],
            "org_id": position["org_id"],
            "account_id": position.get("account_id"),
            "roledef_url": position.get("roledef_url"),
            "created_at": position["created_at"],
        },
        "org_summary": {
            "id": org["id"],
            "name": org["name"],
            "mission": org.get("mission"),
            "vision": org.get("vision"),
            "scope": org.get("scope"),
            "governance_model": org.get("governance_model"),
        },
        "role_definition": (
            {"url": position["roledef_url"]}
            if position.get("roledef_url")
            else None
        ),
        "job_definition": None,  # not stored in openbraid v0; future feature
        "incumbent": {
            "active_sessions": len(active_sessions.data or []),
            "claimable": True,  # always claimable in v0 via PIN ceremony
        },
        "inbox_summary": {
            "inbox_unread": len(inbox_unread.data or []),
            "notes_count": len(notes_count.data or []),
        },
        "claim_instruction": (
            f"To claim this seat: call openbraid's `claim_role` MCP tool with "
            f"role_name=\"{position['name']}\" and account_email=\"{account['email']}\". "
            f"You will receive a challenge_id; the human gatekeeper delivers a "
            f"9-digit PIN out-of-band (via the openbraid panel); call `auth_with_pin` "
            f"with the challenge_id and PIN to complete the claim. Subsequent tool "
            f"calls use the returned session_token."
        ),
    }


# --- Route handlers ---------------------------------------------------------


async def account_orgs_endpoint(request: Request) -> JSONResponse:
    """GET /{account} — list of orgs the account hosts."""
    handle = request.path_params["account"]
    account = _account_by_handle(handle)
    if not account:
        return JSONResponse({"error": "account not found"}, status_code=404)

    orgs = _orgs_for_account(account["id"])
    return JSONResponse(
        {
            "account": {
                "id": account["id"],
                "handle": handle,
                "email": account["email"],
            },
            "orgs": [
                {
                    "id": o["id"],
                    "name": o["name"],
                    "mission": o.get("mission"),
                }
                for o in orgs
            ],
        }
    )


async def account_seg2_endpoint(request: Request) -> JSONResponse:
    """GET /{account}/{seg2} — two-segment URL sugar.

    Resolves seg2 as a position name (when the account hosts exactly
    one org) or as an org name (when it hosts multiple). Mirrors
    GitHub's `github.com/<user>/<repo>` convention and the orgdef-
    strategist memo's two-segment sugar specification.
    """
    handle = request.path_params["account"]
    seg2 = request.path_params["seg2"]
    account = _account_by_handle(handle)
    if not account:
        return JSONResponse({"error": "account not found"}, status_code=404)

    orgs = _orgs_for_account(account["id"])
    if len(orgs) == 1:
        # Implicit-org case: seg2 is a position name.
        org = orgs[0]
        position = _position_by_name(org["id"], seg2)
        if not position:
            return JSONResponse(
                {"error": "position not found in account's only org"},
                status_code=404,
            )
        return JSONResponse(_build_boot_payload(account, org, position))

    # Multi-org case: seg2 is an org name; return positions list.
    org = _org_by_name(account["id"], seg2)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    positions = _positions_for_org(org["id"])
    return JSONResponse(
        {
            "account": {
                "id": account["id"],
                "handle": handle,
                "email": account["email"],
            },
            "org": {
                "id": org["id"],
                "name": org["name"],
                "mission": org.get("mission"),
                "vision": org.get("vision"),
                "scope": org.get("scope"),
                "governance_model": org.get("governance_model"),
            },
            "positions": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "roledef_url": p.get("roledef_url"),
                }
                for p in positions
            ],
        }
    )


async def position_boot_endpoint(request: Request) -> JSONResponse:
    """GET /{account}/{org}/{position} — fresh-agent boot payload."""
    handle = request.path_params["account"]
    org_name = request.path_params["org"]
    position_name = request.path_params["position"]

    account = _account_by_handle(handle)
    if not account:
        return JSONResponse({"error": "account not found"}, status_code=404)

    org = _org_by_name(account["id"], org_name)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)

    position = _position_by_name(org["id"], position_name)
    if not position:
        return JSONResponse({"error": "position not found"}, status_code=404)

    return JSONResponse(_build_boot_payload(account, org, position))


boot_url_routes = [
    Route("/{account}", account_orgs_endpoint, methods=["GET"]),
    Route("/{account}/{seg2}", account_seg2_endpoint, methods=["GET"]),
    Route(
        "/{account}/{org}/{position}",
        position_boot_endpoint,
        methods=["GET"],
    ),
]
