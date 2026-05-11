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


async def tool_upload_org_impl(
    session_token: str,
    org_slug: str,
    content: dict,
) -> dict:
    """Ingest an orgdef.openthing artifact as canonical content for an
    `<account>/<org_slug>` URL.

    Phase E E0-prep. Per the orgdef-strategist 10:30 memo: openbraid is
    the HOSTING layer; orgdef.openthing is the CONTENT layer. This
    helper accepts a parsed JSON artifact, validates the catdef envelope
    + the orgdef MUST fields, and stores the artifact byte-equivalent
    in `org_artifacts.content` (JSONB). Round-trip on export must be
    byte-equivalent; we store what we receive.

    Authorization: any session_token belonging to the uploading
    account grants account-level ingest authority. v0 posture; tighter
    per-account-role authorization can land in a future phase.

    Args:
        session_token: From a successful `auth_with_pin`. The role's
            account is the upload owner.
        org_slug: URL slug for the org. Used in canonical URLs:
            `mcp.openbraid.app/<account>/<org_slug>/<position>`.
            SHOULD match `content["id"]`; we don't enforce equality
            because adopters may prefer a friendlier slug than the
            artifact's id field, but a mismatch is a Pass-with-notes
            concern surfaced in the response.
        content: The orgdef.openthing artifact as a parsed dict.
            Stored as JSONB; must round-trip byte-equivalent.

    Returns:
        dict with: artifact_id (str), org_slug (str), version (str),
        position_count (int), byte_count (int), slug_id_mismatch (bool,
        true when org_slug != content["id"]).

    Raises:
        ValueError on validation failure with a user-presentable
        message identifying the missing/malformed field.
    """
    # Validate inputs BEFORE any DB work. Malformed input shouldn't
    # cost a Supabase round-trip; clearer errors and cheaper rejection.
    if not isinstance(content, dict):
        raise ValueError("content must be a JSON object (dict), got %s" % type(content).__name__)
    _require_field(content, "catdef", str)
    _require_field(content, "orgdef", str)
    _require_field(content, "type", str)
    if content["type"] != "orgdef:Organization":
        raise ValueError(
            f"content.type must be 'orgdef:Organization' for ingest; "
            f"got {content['type']!r}. orgdef:Library and other types "
            f"are out of scope for Phase E0-prep."
        )
    _require_field(content, "id", str)
    _require_field(content, "name", str)
    _require_field(content, "version", str)

    if not isinstance(org_slug, str) or not org_slug:
        raise ValueError("org_slug must be a non-empty string")
    if "/" in org_slug or " " in org_slug:
        raise ValueError(
            f"org_slug must not contain '/' or whitespace; got {org_slug!r}"
        )

    slug_id_mismatch = org_slug != content["id"]

    # Resolve uploader's account via the session_token → role → account chain.
    sender_role_id = get_role_id_from_token(session_token)
    role_lookup = (
        supabase()
        .table("roles")
        .select("account_id")
        .eq("id", sender_role_id)
        .execute()
    )
    if not role_lookup.data:
        raise ValueError("Session token's role no longer exists")
    account_id = role_lookup.data[0]["account_id"]

    # Upsert via select-then-update-or-insert. Postgres ON CONFLICT
    # could express this in one statement but the supabase-py client's
    # upsert path is awkward for partial-unique-index constraints; the
    # explicit two-step is clearer and equally safe at v0 scale.
    existing = (
        supabase()
        .table("org_artifacts")
        .select("id")
        .eq("account_id", account_id)
        .eq("org_slug", org_slug)
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        # Update in place; preserves the artifact_id for stable URLs.
        artifact_id = existing.data[0]["id"]
        supabase().table("org_artifacts").update(
            {
                "content": content,
                "version": content["version"],
                "updated_at": "now()",
            }
        ).eq("id", artifact_id).execute()
    else:
        inserted = (
            supabase()
            .table("org_artifacts")
            .insert(
                {
                    "account_id": account_id,
                    "org_slug": org_slug,
                    "content": content,
                    "version": content["version"],
                }
            )
            .execute()
        )
        artifact_id = inserted.data[0]["id"]

    # Count positions for the receipt. Spec says positions is an array
    # (may be empty for charter-only orgs).
    positions = content.get("positions") or []
    position_count = len(positions) if isinstance(positions, list) else 0

    # byte_count is approximate (JSON re-serialization); useful for
    # caller-side sanity ("the upload landed").
    import json
    byte_count = len(json.dumps(content, separators=(",", ":")))

    return {
        "artifact_id": artifact_id,
        "org_slug": org_slug,
        "version": content["version"],
        "position_count": position_count,
        "byte_count": byte_count,
        "slug_id_mismatch": slug_id_mismatch,
    }


async def tool_upload_job_impl(
    session_token: str,
    org_slug: str,
    content: dict,
) -> dict:
    """Ingest a roledef:Job artifact, scoped to an existing org_artifact.

    Phase E E2. Jobs are the "what does this seat actually produce"
    layer that hangs off an orgdef position's `job_definition.url`. We
    store them in `job_artifacts` parallel to `org_artifacts`, scoped
    to the owning org via FK. The artifact's `id` becomes the job's
    URL-resolvable slug (e.g. "implementer" for an
    /scott/thingalog/implementer-shaped job).

    Per the orgdef-strategist canonical-store principle, the artifact
    is stored byte-equivalent for E5 round-trip; the indexed columns
    (org_artifact_id, job_id, version) are derived-from-content.

    Authorization: identical to upload_org — any session_token from a
    role belonging to the org_artifact's owning account grants ingest
    authority for that org's jobs.

    Args:
        session_token: From a successful `auth_with_pin`.
        org_slug: The owning org's URL slug (must already be uploaded
            via upload_org; jobs cannot exist without a parent org).
        content: The roledef:Job artifact as a parsed dict. Stored
            byte-equivalent; round-trip must be lossless.

    Returns:
        dict with: artifact_id (str), org_slug (str), job_id (str),
        version (str), byte_count (int).

    Raises:
        ValueError on validation failure or when the parent org doesn't
        exist for the uploading account.
    """
    if not isinstance(content, dict):
        raise ValueError(
            "content must be a JSON object (dict), got %s" % type(content).__name__
        )
    _require_field(content, "catdef", str)
    _require_field(content, "roledef", str)
    _require_field(content, "type", str)
    if content["type"] != "roledef:Job":
        raise ValueError(
            f"content.type must be 'roledef:Job' for ingest; "
            f"got {content['type']!r}. Use upload_org for orgdef:Organization."
        )
    _require_field(content, "id", str)
    _require_field(content, "name", str)
    _require_field(content, "version", str)

    if not isinstance(org_slug, str) or not org_slug:
        raise ValueError("org_slug must be a non-empty string")
    if "/" in org_slug or " " in org_slug:
        raise ValueError(
            f"org_slug must not contain '/' or whitespace; got {org_slug!r}"
        )

    sender_role_id = get_role_id_from_token(session_token)
    role_lookup = (
        supabase()
        .table("roles")
        .select("account_id")
        .eq("id", sender_role_id)
        .execute()
    )
    if not role_lookup.data:
        raise ValueError("Session token's role no longer exists")
    account_id = role_lookup.data[0]["account_id"]

    # Parent-org gate: the job's org_slug must already exist as an
    # org_artifact for this account. Jobs are scoped to orgs; uploading
    # a job for a slug we've never heard of is rejected so the
    # FK-violation surface is a friendly ValueError instead of a 500.
    parent = (
        supabase()
        .table("org_artifacts")
        .select("id")
        .eq("account_id", account_id)
        .eq("org_slug", org_slug)
        .is_("deleted_at", "null")
        .execute()
    )
    if not parent.data:
        raise ValueError(
            f"No org artifact found for slug {org_slug!r} on this account. "
            f"Upload the orgdef artifact via upload_org before its jobs."
        )
    org_artifact_id = parent.data[0]["id"]
    job_id = content["id"]

    existing = (
        supabase()
        .table("job_artifacts")
        .select("id")
        .eq("org_artifact_id", org_artifact_id)
        .eq("job_id", job_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        artifact_id = existing.data[0]["id"]
        supabase().table("job_artifacts").update(
            {
                "content": content,
                "version": content["version"],
                "updated_at": "now()",
            }
        ).eq("id", artifact_id).execute()
    else:
        inserted = (
            supabase()
            .table("job_artifacts")
            .insert(
                {
                    "org_artifact_id": org_artifact_id,
                    "job_id": job_id,
                    "content": content,
                    "version": content["version"],
                }
            )
            .execute()
        )
        artifact_id = inserted.data[0]["id"]

    import json
    byte_count = len(json.dumps(content, separators=(",", ":")))

    return {
        "artifact_id": artifact_id,
        "org_slug": org_slug,
        "job_id": job_id,
        "version": content["version"],
        "byte_count": byte_count,
    }


def _require_field(obj: dict, name: str, expected_type: type) -> None:
    """Raise ValueError if `obj[name]` is missing or wrong type.

    Used by `tool_upload_org_impl` for catdef-envelope + orgdef-MUST
    field validation. Surfaces user-presentable error messages.
    """
    if name not in obj:
        raise ValueError(f"Missing required field: '{name}'")
    value = obj[name]
    if not isinstance(value, expected_type):
        raise ValueError(
            f"Field '{name}' must be {expected_type.__name__}, "
            f"got {type(value).__name__}"
        )
    if expected_type is str and not value:
        raise ValueError(f"Field '{name}' must be non-empty")


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
