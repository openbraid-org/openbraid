"""openbraid MCP server entry point.

This is a v0 scaffold — the six tools are registered but raise
NotImplementedError. Storage (Supabase) is not wired up yet; that lands in a
later session once the Supabase project is provisioned and credentials are
in Railway env vars.

Run locally:
    pip install -e ".[dev]"
    python -m server.main

Run on Railway:
    Procfile entry `web: python -m server.main` boots the streamable-HTTP
    transport on $PORT.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

mcp = FastMCP(
    name="openbraid",
    instructions=(
        "openbraid is a hosted memo store for stateless AI sessions. "
        "Claim a role with `claim_role`, complete the inverse-sncro PIN ceremony "
        "with `auth_with_pin`, then use the resulting session token to "
        "`send_memo`, `list_inbox`, `read_memo`, and `mark_read`."
    ),
)


@mcp.tool()
async def claim_role(
    role_name: str,
    claim_what: str = "read+write memos",
) -> dict:
    """Begin a role-claim ceremony.

    Generates a 9-digit one-time PIN delivered out-of-band to the human
    gatekeeper (web panel in v0). Returns a challenge_id the caller submits
    to `auth_with_pin` along with the PIN the user reads back.

    Args:
        role_name: The role being claimed, e.g. "scotts-personal-strategist".
        claim_what: Human-readable description of what's being authorized,
            shown in the panel so the user knows what they're approving.
            Defaults to "read+write memos".

    Returns:
        dict with keys: challenge_id (str), expires_at (ISO-8601 str).
    """
    raise NotImplementedError("v0 stub: storage and PIN delivery not yet wired")


@mcp.tool()
async def auth_with_pin(challenge_id: str, pin: str) -> dict:
    """Complete a role-claim ceremony by presenting the one-time PIN.

    Validates the PIN against the outstanding challenge, burns it
    (atomically), and issues a session token bound to the originating
    Claude conversation.

    Args:
        challenge_id: The id returned from a prior `claim_role` call.
        pin: The 9-digit PIN the user read from the openbraid web panel.

    Returns:
        dict with keys: session_token (str), expires_at (ISO-8601 str),
        role (str — the role name now authenticated).
    """
    raise NotImplementedError("v0 stub: PIN validation and token issuance not yet wired")


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
    """Send a memo from the authenticated role to another role's mailbox.

    Mirrors memodef:Memo wire shape. body_ref is optional; when present it
    points at a longer-form attachment archived alongside the memo.

    Args:
        session_token: From a successful `auth_with_pin`.
        to_role: Recipient role name (must exist in the same account or
            be reachable per cross-org conventions — TBD).
        subject: Short memo subject.
        body: Memo body text.
        body_ref: Optional pointer to a longer-form body file.
        action_required: Whether the memo requires a response.
        in_reply_to: Optional reference to the memo this replies to.
        thread_id: Optional thread identifier for multi-memo conversations.

    Returns:
        dict with keys: memo_id (str), sent_at (ISO-8601 str).
    """
    raise NotImplementedError("v0 stub: memo persistence not yet wired")


@mcp.tool()
async def list_inbox(
    session_token: str,
    status: str = "inbox",
    limit: int = 50,
) -> dict:
    """List memos in the authenticated role's mailbox.

    Args:
        session_token: From a successful `auth_with_pin`.
        status: One of "inbox", "read", "archived". Defaults to "inbox".
        limit: Maximum memos to return. Defaults to 50.

    Returns:
        dict with key: memos (list of summaries — id, from_position,
        subject, sent_at, action_required).
    """
    raise NotImplementedError("v0 stub: memo persistence not yet wired")


@mcp.tool()
async def read_memo(session_token: str, memo_id: str) -> dict:
    """Read the full content of a memo by id.

    Does NOT mark the memo read; call `mark_read` separately. This split
    matches the memodef adopter pattern where reading and acknowledging
    are distinct operations.

    Args:
        session_token: From a successful `auth_with_pin`.
        memo_id: The id of the memo to retrieve.

    Returns:
        dict with the full memodef:Memo shape (from_position, to_position,
        subject, body, body_ref, sent_at, action_required, in_reply_to,
        thread_id, status).
    """
    raise NotImplementedError("v0 stub: memo persistence not yet wired")


@mcp.tool()
async def mark_read(session_token: str, memo_id: str) -> dict:
    """Mark a memo as read, transitioning its status from "inbox" to "read".

    Args:
        session_token: From a successful `auth_with_pin`.
        memo_id: The id of the memo to mark.

    Returns:
        dict with keys: ok (bool), status (str — the new status, "read").
    """
    raise NotImplementedError("v0 stub: memo persistence not yet wired")


def main() -> None:
    """Run the openbraid MCP server.

    Uses streamable-HTTP transport for hosted deployment (Railway sets
    $PORT). For local stdio transport during MCP-client integration
    testing, override the transport via FASTMCP_TRANSPORT=stdio.
    """
    transport = os.environ.get("FASTMCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
