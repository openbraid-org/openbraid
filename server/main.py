"""openbraid MCP server entry point.

Single Railway service hosting two surfaces:
  - MCP tool surface, mounted at `/mcp` (FastMCP streamable-HTTP)
  - Web panel, served at `/`, `/panel`, `/auth/*`

Six tools backed by Supabase. The server holds the service-role key and
is the trusted intermediary; v0 has no RLS. Auth for the MCP surface is
the inverse-sncro PIN ceremony; auth for the panel is Supabase Google
OAuth via PKCE.

Run locally:
    pip install -e ".[dev]"
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... SUPABASE_ANON_KEY=... \\
        PANEL_ORIGIN=http://localhost:8000 python -m server.main

Run on Railway:
    `Procfile` boots uvicorn on $PORT; env vars set in Railway.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastmcp import Context, FastMCP
from starlette.applications import Starlette
from starlette.routing import Host, Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from server.db import (
    generate_pin,
    generate_session_token,
    get_role_id_from_token,
    get_role_position,
    resolve_role_by_name,
    session_expiry,
    supabase,
)

mcp = FastMCP(
    name="openbraid",
    instructions=(
        "openbraid is a hosted memo store for stateless AI sessions. "
        "Claim a role with `claim_role` (give the role name and the human's "
        "Google account email), complete the inverse-sncro PIN ceremony "
        "with `auth_with_pin`, then use the resulting session token to "
        "`send_memo`, `list_inbox`, `read_memo`, and `mark_read`."
    ),
)


@mcp.tool()
async def claim_role(
    role_name: str,
    account_email: str,
    ctx: Context,
    claim_what: str = "read+write memos",
) -> dict:
    """Begin a role-claim ceremony.

    Generates a 9-digit one-time PIN and writes it to the pin_challenges
    table. The human gatekeeper retrieves the PIN out-of-band (web panel
    in v1; Supabase table editor for v0) and reads it back to the AI,
    which then calls `auth_with_pin`.

    Args:
        role_name: The role being claimed (e.g. "personal-strategist").
            Must exist under the given account.
        account_email: Google email of the account that owns the role.
            Required because role names are unique per-account, not
            globally — this disambiguates which X is being claimed.
        claim_what: Human-readable description of what's being authorized,
            shown in the panel so the user knows what they're approving.
            Defaults to "read+write memos".

    Returns:
        dict with: challenge_id (str), expires_at (ISO-8601 str),
        message (instruction for the AI to relay to the user).
    """
    role_id = resolve_role_by_name(account_email, role_name)
    pin = generate_pin()

    result = (
        supabase()
        .table("pin_challenges")
        .insert(
            {
                "role_id": role_id,
                "pin": pin,
                "client_session_id": ctx.session_id or "",
                "claim_what": claim_what,
            }
        )
        .execute()
    )
    row = result.data[0]
    return {
        "challenge_id": row["id"],
        "expires_at": row["expires_at"],
        "message": (
            f"Tell the user: openbraid is requesting access as "
            f"'{role_name}' ({claim_what}). Ask them to read the 9-digit "
            f"PIN from their openbraid panel and give it to you, then "
            f"call auth_with_pin."
        ),
    }


@mcp.tool()
async def auth_with_pin(challenge_id: str, pin: str, ctx: Context) -> dict:
    """Complete a role-claim ceremony by presenting the one-time PIN.

    Validates the PIN against the outstanding challenge atomically (single
    UPDATE with all preconditions in WHERE), burns it on success, and
    issues a session token bound to the originating MCP session.

    Args:
        challenge_id: The id returned from a prior `claim_role` call.
        pin: The 9-digit PIN the user read from the panel. Whitespace
            is stripped before comparison so a user can read the PIN
            in `123 456 789` form without breaking auth.

    Returns:
        dict with: session_token (str), expires_at (ISO-8601 str),
        role (str — the role name now authenticated).
    """
    pin = "".join(pin.split())
    burn = (
        supabase()
        .table("pin_challenges")
        .update({"used_at": "now()"})
        .eq("id", challenge_id)
        .eq("pin", pin)
        .is_("used_at", "null")
        .gt("expires_at", "now()")
        .execute()
    )
    if not burn.data:
        raise ValueError("Invalid, expired, or already-used PIN")
    role_id = burn.data[0]["role_id"]

    token = generate_session_token()
    expiry = session_expiry()
    inserted = (
        supabase()
        .table("auth_sessions")
        .insert(
            {
                "role_id": role_id,
                "session_token": token,
                "client_session_id": ctx.session_id or "",
                "expires_at": expiry,
            }
        )
        .execute()
    )
    role_name = get_role_position(role_id)
    return {
        "session_token": token,
        "expires_at": inserted.data[0]["expires_at"],
        "role": role_name,
    }


@mcp.tool()
async def send_memo(
    session_token: str,
    to_role: str,
    subject: str,
    body: str,
    body_ref: str | None = None,
    action_required: bool = False,
    in_reply_to: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """Send a memo, either directed to a recipient role or filed for the
    authenticated role's accumulated context.

    Two modes, distinguished by `to_role`:

    1. **Directed memo** (`to_role` = a sibling role's name):
       The memo is written to the recipient role's mailbox; from_position
       is derived from the session's role. Cross-account routing is out
       of scope for v0 — recipient must be in the same account.

    2. **Memo-to-file** (`to_role` = `"file"`, the memodef v0.3 sentinel):
       The memo is filed under the authenticated role's notes folder
       for accumulated context. No per-recipient processing event;
       successive incumbents of the role read the notes to inherit
       context. Per memodef v0.3, `action_required=true` is rejected for
       memos-to-file (a filed-for-record memo has no recipient to act).

    Args:
        session_token: From a successful `auth_with_pin`.
        to_role: Recipient role name within the same account, OR the
            literal string `"file"` to file a memo-to-file under the
            authenticated role's notes folder.
        subject: Short memo subject.
        body: Memo body text.
        body_ref: Optional pointer to a longer-form body file.
        action_required: Whether the memo requires a response. MUST be
            false (the default) when `to_role="file"`.
        in_reply_to: Optional reference to the memo this replies to.
        thread_id: Optional thread identifier for multi-memo conversations.

    Returns:
        dict with: memo_id (str), sent_at (ISO-8601 str), kind (str —
        either "inbox" for directed memos or "note" for memos-to-file).
    """
    sender_role_id = get_role_id_from_token(session_token)
    sender_position = get_role_position(sender_role_id)

    if to_role == "file":
        # memodef v0.3 memo-to-file: filed under the authenticated role's
        # notes folder, not directed at any recipient.
        if action_required:
            raise ValueError(
                "memo-to-file (to_role='file') cannot be combined with "
                "action_required=true: a memo filed for the role's record "
                "has no recipient to act on it"
            )
        target_role_id = sender_role_id
        kind = "note"
    else:
        # Directed memo to a sibling role within the same account.
        sender_account = (
            supabase()
            .table("roles")
            .select("account_id")
            .eq("id", sender_role_id)
            .execute()
        )
        account_id = sender_account.data[0]["account_id"]

        recipient = (
            supabase()
            .table("roles")
            .select("id")
            .eq("account_id", account_id)
            .eq("name", to_role)
            .is_("deleted_at", "null")
            .execute()
        )
        if not recipient.data:
            raise ValueError(
                f"No role '{to_role}' found in this account (v0 cross-account "
                f"routing is not supported; use 'file' to file a memo-to-file "
                f"in your own role's notes folder)"
            )
        target_role_id = recipient.data[0]["id"]
        kind = "inbox"

    inserted = (
        supabase()
        .table("memos")
        .insert(
            {
                "role_id": target_role_id,
                "from_position": sender_position,
                "to_position": to_role,
                "subject": subject,
                "body": body,
                "body_ref": body_ref,
                "sent_at": "now()",
                "action_required": action_required,
                "in_reply_to": in_reply_to,
                "thread_id": thread_id,
                "status": "inbox" if kind == "inbox" else "archived",
                "kind": kind,
            }
        )
        .execute()
    )
    return {
        "memo_id": inserted.data[0]["id"],
        "sent_at": inserted.data[0]["sent_at"],
        "kind": kind,
    }


@mcp.tool()
async def list_inbox(
    session_token: str,
    status: str = "inbox",
    limit: int = 50,
    folder: str | None = None,
) -> dict:
    """List memos in the authenticated role's mailbox or notes folder.

    Two modes via the `folder` argument:

    - `folder=None` (default): list directed-memo mailbox (kind='inbox').
      The `status` filter applies in this mode.
    - `folder="notes"`: list memos-to-file filed under the authenticated
      role's accumulated context (kind='note', per memodef v0.3). The
      `status` filter is ignored — notes have no maildir lifecycle.

    Cross-role notes access (`folder="notes/<other-role>"`) is out of
    scope for v0; deferred per memodef v0.3 decision Q4.

    Args:
        session_token: From a successful `auth_with_pin`.
        status: One of "inbox", "read", "archived". Defaults to "inbox".
            Ignored when `folder="notes"`.
        limit: Maximum memos to return. Defaults to 50.
        folder: None or "inbox" for the directed-memo mailbox (default);
            "notes" for the authenticated role's notes folder.

    Returns:
        dict with: memos (list of summaries — id, from_position,
        subject, sent_at, action_required, thread_id).
    """
    role_id = get_role_id_from_token(session_token)

    if folder == "notes":
        result = (
            supabase()
            .table("memos")
            .select(
                "id, from_position, subject, sent_at, action_required, thread_id"
            )
            .eq("role_id", role_id)
            .eq("kind", "note")
            .is_("deleted_at", "null")
            .order("sent_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"memos": result.data}

    if folder not in (None, "inbox"):
        raise ValueError(
            f"folder must be None, 'inbox', or 'notes'; got {folder!r}"
        )
    if status not in {"inbox", "read", "archived"}:
        raise ValueError(
            f"status must be inbox|read|archived, got {status!r}"
        )
    result = (
        supabase()
        .table("memos")
        .select(
            "id, from_position, subject, sent_at, action_required, thread_id"
        )
        .eq("role_id", role_id)
        .eq("kind", "inbox")
        .eq("status", status)
        .is_("deleted_at", "null")
        .order("sent_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"memos": result.data}


@mcp.tool()
async def read_memo(session_token: str, memo_id: str) -> dict:
    """Read the full content of a memo by id.

    Does NOT mark the memo read; call `mark_read` separately. Reading and
    acknowledging are distinct operations so an AI can preview content
    without committing to "I've handled this."

    Args:
        session_token: From a successful `auth_with_pin`.
        memo_id: The id of the memo to retrieve.

    Returns:
        dict with the full memodef:Memo shape plus status.
    """
    role_id = get_role_id_from_token(session_token)
    result = (
        supabase()
        .table("memos")
        .select(
            "id, from_position, to_position, subject, body, body_ref, "
            "sent_at, action_required, in_reply_to, thread_id, status, kind"
        )
        .eq("id", memo_id)
        .eq("role_id", role_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise ValueError(
            f"Memo {memo_id} not found in this role's mailbox"
        )
    return result.data[0]


@mcp.tool()
async def mark_read(session_token: str, memo_id: str) -> dict:
    """Mark a memo as read, transitioning its status from "inbox" to "read".

    Args:
        session_token: From a successful `auth_with_pin`.
        memo_id: The id of the memo to mark.

    Returns:
        dict with: ok (bool), status (str — the new status).
    """
    role_id = get_role_id_from_token(session_token)
    result = (
        supabase()
        .table("memos")
        .update({"status": "read"})
        .eq("id", memo_id)
        .eq("role_id", role_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise ValueError(
            f"Memo {memo_id} not found in this role's mailbox"
        )
    return {"ok": True, "status": result.data[0]["status"]}


# --- HTTP host: per-domain routing -----------------------------------------
#
# Single Railway dyno hosts both surfaces, but split by Host header in
# production:
#
#   mcp.openbraid.app  -> MCP only, served at the root (/)
#                         (legacy /mcp also accepted via path-rewrite)
#   www.openbraid.app  -> panel only
#
# For any other host (localhost, the bare *.up.railway.app domain, IPs
# during dev), fall through to the v0 layout: panel at /, MCP at /mcp.

_mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def _lifespan(app):
    async with _mcp_app.router.lifespan_context(app):
        yield


class _LegacyMCPPathRewriter:
    """ASGI wrapper that rewrites /mcp → / on the way in.

    Lets clients registered against the v0 URL (mcp.openbraid.app/mcp)
    keep working after the MCP endpoint moves to the bare host. Pure
    path rewrite — body, headers, query string preserved.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/"
            scope["raw_path"] = b"/"
        await self.app(scope, receive, send)




from server.boot_url import boot_url_routes  # noqa: E402
from server.panel import panel_routes  # noqa: E402

_panel_app = Starlette(routes=panel_routes)

# mcp.openbraid.app inner stack: boot URL routes for /{account},
# /{account}/{seg2}, /{account}/{org}/{position}, then a catch-all
# Mount that sends bare / to FastMCP. The whole stack is wrapped in
# _LegacyMCPPathRewriter so /mcp gets rewritten to / before routing
# happens — boot_url's /{account} pattern would otherwise match /mcp
# with account="mcp" and short-circuit to 404 (per the reserved-
# handle gate in server.boot_url._account_by_handle).
_mcp_host_inner = Starlette(
    routes=[
        *boot_url_routes,
        Mount("/", app=_mcp_app),
    ]
)
_mcp_host_app = _LegacyMCPPathRewriter(_mcp_host_inner)

app = Starlette(
    routes=[
        # Production hosts: hard split.
        Host("mcp.openbraid.app", app=_mcp_host_app),
        Host("www.openbraid.app", app=_panel_app),
        # Fallback for unmatched hosts (localhost dev, *.up.railway.app,
        # IPs): combined layout. /mcp on the fallback hits the boot URL
        # /{account} pattern with handle="mcp" → reserved-handle gate
        # returns JSON 404. For local MCP testing, hit `/` directly
        # (FastMCP's bare endpoint) — the legacy /mcp URL is only
        # rewired on the production mcp.openbraid.app host.
        *panel_routes,
        *boot_url_routes,
        Mount("/", app=_mcp_app),
    ],
    lifespan=_lifespan,
)


def main() -> None:
    """Run the openbraid MCP server + panel."""
    transport = os.environ.get("FASTMCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        # Stdio transport is for local MCP-client integration testing only;
        # the panel is HTTP and is not exposed in stdio mode.
        mcp.run(transport="stdio")
    else:
        import uvicorn

        port = int(os.environ.get("PORT", "8000"))
        uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
