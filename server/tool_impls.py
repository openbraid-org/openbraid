"""Transport-agnostic tool implementations.

The six openbraid tools (claim_role, auth_with_pin, send_memo,
list_inbox, read_memo, mark_read) have their full logic here as plain
async functions taking primitives. Both transports — FastMCP (server/
main.py) and FastAPI REST (server/rest_api.py) — call into these
helpers. The transport-side wrappers are thin: extract parameters,
call impl, return / serialize.

This is the safety net for "MCP and REST can't drift" — the contract
test asserts both transports route to the same impl module.

Phase D extraction (PR #20) of pre-existing logic from server/main.py.
No behavior change in the extraction step itself.
"""

from __future__ import annotations

from server.db import (
    generate_pin,
    generate_session_token,
    get_role_id_from_token,
    get_role_position,
    resolve_position_url,
    session_expiry,
    supabase,
)


async def tool_claim_role_impl(
    position_url: str,
    claim_what: str,
    client_session_id: str,
) -> dict:
    """Begin a role-claim ceremony.

    Resolves the position URL, generates a 9-digit PIN, writes a
    pin_challenges row, returns the challenge id + relay instructions.
    """
    role_id, _resolved_email, role_name = resolve_position_url(position_url)
    pin = generate_pin()

    result = (
        supabase()
        .table("pin_challenges")
        .insert(
            {
                "role_id": role_id,
                "pin": pin,
                "client_session_id": client_session_id,
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


async def tool_auth_with_pin_impl(
    challenge_id: str,
    pin: str,
    client_session_id: str,
) -> dict:
    """Complete a role-claim ceremony by burning the one-time PIN.

    Atomic UPDATE-with-WHERE-clauses guarantees single-use. On
    success, mints a 24h session_token bound to the originating
    session (for audit) and returns it. Token is transport-agnostic
    — works as MCP session credential or REST Bearer.
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
                "client_session_id": client_session_id,
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


async def tool_send_memo_impl(
    session_token: str,
    to_role: str,
    subject: str,
    body: str,
    body_ref: str | None = None,
    action_required: bool = False,
    in_reply_to: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """Send a memo, either directed to a recipient role or filed as
    a memo-to-file under the authenticated role's notes folder.
    """
    sender_role_id = get_role_id_from_token(session_token)
    sender_position = get_role_position(sender_role_id)

    if to_role == "file":
        if action_required:
            raise ValueError(
                "memo-to-file (to_role='file') cannot be combined with "
                "action_required=true: a memo filed for the role's record "
                "has no recipient to act on it"
            )
        target_role_id = sender_role_id
        kind = "note"
    else:
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


async def tool_list_inbox_impl(
    session_token: str,
    status: str = "inbox",
    limit: int = 50,
    folder: str | None = None,
) -> dict:
    """List memos in the authenticated role's mailbox or notes folder."""
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


async def tool_read_memo_impl(session_token: str, memo_id: str) -> dict:
    """Return the full content of a memo by id."""
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


async def tool_mark_read_impl(session_token: str, memo_id: str) -> dict:
    """Transition a memo's status from inbox to read."""
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
