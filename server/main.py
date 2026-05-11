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

from server.tool_impls import (
    tool_auth_with_pin_impl,
    tool_claim_role_impl,
    tool_list_inbox_impl,
    tool_mark_read_impl,
    tool_read_memo_impl,
    tool_send_memo_impl,
    tool_upload_org_impl,
)

mcp = FastMCP(
    name="openbraid",
    instructions=(
        "openbraid is a hosted memo store for stateless AI sessions, "
        "addressed via canonical OAGP position URLs of the form "
        "`https://mcp.openbraid.app/<account>/<org>/<position>` (or the "
        "two-segment sugar `<account>/<position>` when the account hosts "
        "exactly one org). Claim a role with `claim_role(position_url=...)`; "
        "complete the inverse-sncro PIN ceremony with "
        "`auth_with_pin(challenge_id, pin)`; use the returned session_token "
        "with `send_memo`, `list_inbox`, `read_memo`, and `mark_read`."
    ),
)


@mcp.tool()
async def claim_role(
    position_url: str,
    ctx: Context,
    claim_what: str = "read+write memos",
) -> dict:
    """Begin a role-claim ceremony.

    Pass a canonical OAGP position URL — three-segment form
    (`/account/org/position`) or two-segment sugar
    (`/account/position`, when the account hosts exactly one org).
    Full URLs with scheme, host-only forms, and bare paths all
    accepted; the parser strips scheme + host and works on the path.

    Generates a 9-digit one-time PIN written to pin_challenges. The
    human gatekeeper retrieves the PIN out-of-band (web panel) and
    reads it back to the AI, which calls auth_with_pin to complete.

    Args:
        position_url: Canonical position URL per OAGP addressing
            (orgdef-spec ba004ca). Examples:
              "https://mcp.openbraid.app/scott/personal/personal-strategist"
              "https://mcp.openbraid.app/scott/personal-strategist"
              "/scott/personal/personal-strategist"
        claim_what: Human-readable description of what's being authorized,
            shown in the panel so the user knows what they're approving.
            Defaults to "read+write memos".

    Returns:
        dict with: challenge_id (str), expires_at (ISO-8601 str),
        message (instruction for the AI to relay to the user).
    """
    return await tool_claim_role_impl(
        position_url=position_url,
        claim_what=claim_what,
        client_session_id=ctx.session_id or "",
    )


@mcp.tool()
async def auth_with_pin(challenge_id: str, pin: str, ctx: Context) -> dict:
    """Complete a role-claim ceremony by presenting the one-time PIN.

    The returned session_token is transport-agnostic — works as the
    MCP session credential AND as a REST Authorization Bearer token
    on `/api/...` endpoints. Same token; same lifecycle; 24h expiry.

    Args:
        challenge_id: The id returned from a prior `claim_role` call.
        pin: The 9-digit PIN the user read from the panel. Whitespace
            is stripped before comparison so a user can read the PIN
            in `123 456 789` form without breaking auth.

    Returns:
        dict with: session_token (str), expires_at (ISO-8601 str),
        role (str — the role name now authenticated).
    """
    return await tool_auth_with_pin_impl(
        challenge_id=challenge_id,
        pin=pin,
        client_session_id=ctx.session_id or "",
    )


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
       for accumulated context. Per memodef v0.3, `action_required=true`
       is rejected for memos-to-file.

    Args:
        session_token: From a successful `auth_with_pin`.
        to_role: Recipient role name within the same account, OR the
            literal string `"file"` for a memo-to-file.
        subject: Short memo subject.
        body: Memo body text.
        body_ref: Optional pointer to a longer-form body file.
        action_required: Whether the memo requires a response. MUST be
            false when `to_role="file"`.
        in_reply_to: Optional reference to the memo this replies to.
        thread_id: Optional thread identifier.

    Returns:
        dict with: memo_id (str), sent_at (ISO-8601 str), kind (str).
    """
    return await tool_send_memo_impl(
        session_token=session_token,
        to_role=to_role,
        subject=subject,
        body=body,
        body_ref=body_ref,
        action_required=action_required,
        in_reply_to=in_reply_to,
        thread_id=thread_id,
    )


@mcp.tool()
async def list_inbox(
    session_token: str,
    status: str = "inbox",
    limit: int = 50,
    folder: str | None = None,
) -> dict:
    """List memos in the authenticated role's mailbox or notes folder.

    Args:
        session_token: From a successful `auth_with_pin`.
        status: One of "inbox", "read", "archived". Defaults to "inbox".
            Ignored when `folder="notes"`.
        limit: Maximum memos to return. Defaults to 50.
        folder: None or "inbox" for the directed-memo mailbox (default);
            "notes" for the authenticated role's notes folder.

    Returns:
        dict with: memos (list of summaries).
    """
    return await tool_list_inbox_impl(
        session_token=session_token,
        status=status,
        limit=limit,
        folder=folder,
    )


@mcp.tool()
async def read_memo(session_token: str, memo_id: str) -> dict:
    """Read the full content of a memo by id.

    Does NOT mark the memo read; call `mark_read` separately.

    Args:
        session_token: From a successful `auth_with_pin`.
        memo_id: The id of the memo to retrieve.

    Returns:
        dict with the full memodef:Memo shape plus status and kind.
    """
    return await tool_read_memo_impl(
        session_token=session_token,
        memo_id=memo_id,
    )


@mcp.tool()
async def mark_read(session_token: str, memo_id: str) -> dict:
    """Mark a memo as read, transitioning its status from "inbox" to "read".

    Args:
        session_token: From a successful `auth_with_pin`.
        memo_id: The id of the memo to mark.

    Returns:
        dict with: ok (bool), status (str — the new status).
    """
    return await tool_mark_read_impl(
        session_token=session_token,
        memo_id=memo_id,
    )


@mcp.tool()
async def upload_org(
    session_token: str,
    org_slug: str,
    content: dict,
) -> dict:
    """Ingest an orgdef.openthing artifact as canonical content for an
    `<account>/<org_slug>` URL.

    Phase E E0-prep. Per the OAGP canonical-store principle: openbraid
    is the HOSTING layer; orgdef.openthing is the CONTENT layer. This
    tool stores the artifact byte-equivalent so full-fidelity export
    round-trips later (Phase E5). Validation: catdef envelope check
    (catdef, orgdef, type fields) + orgdef MUST fields (id, name,
    version). The artifact is stored as JSONB; the type MUST be
    `"orgdef:Organization"` (libraries and job artifacts are separate
    surfaces).

    Authorization: any session_token from a role belonging to the
    uploading account grants account-level ingest authority.

    Args:
        session_token: From a successful `auth_with_pin`.
        org_slug: URL slug for the org (e.g. "thingalog"). Used in
            `mcp.openbraid.app/<account>/<org_slug>/<position>`.
            SHOULD match `content["id"]`; if not, the response flags
            `slug_id_mismatch: true`.
        content: The orgdef.openthing artifact as a parsed JSON
            object. Round-trip byte-equivalent storage required for
            Phase E5 full-fidelity export.

    Returns:
        dict with: artifact_id (str), org_slug (str), version (str),
        position_count (int), byte_count (int), slug_id_mismatch (bool).
    """
    return await tool_upload_org_impl(
        session_token=session_token,
        org_slug=org_slug,
        content=content,
    )


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
from server.rest_api import api as _rest_api  # noqa: E402

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
        # REST + OpenAPI under /api/... (Phase D D1): mounted FIRST so
        # the /{account} pattern can't shadow it. "api" is reserved in
        # _account_by_handle as additional defense in depth.
        Mount("/api", app=_rest_api),
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
        Mount("/api", app=_rest_api),
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
        # proxy_headers=True trusts X-Forwarded-Proto / X-Forwarded-For from
        # Railway's reverse proxy so request.url.scheme is "https" (not "http",
        # which is the dyno-internal scheme). Critical for the canonical URL
        # in boot payloads' claim_instruction. forwarded_allow_ips="*" because
        # Railway doesn't expose a stable proxy IP we can pin.
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=port,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )


if __name__ == "__main__":
    main()
