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

from server.canonical_json import sha256_hex
from server.db import (
    account_by_handle,
    artifact_by_account_and_slug,
    ensure_org_create_role,
    generate_pin,
    generate_session_token,
    get_role_id_from_token,
    get_role_position,
    resolve_position_url,
    session_expiry,
    supabase,
)
from server.master_state import detect_master_state


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


async def tool_claim_org_create_impl(
    account_handle: str,
    claim_what: str,
    client_session_id: str,
) -> dict:
    """Begin an org-create ceremony for an account.

    Mirrors `tool_claim_role_impl` but works at the account level
    rather than the position level. Lets a fresh user create their
    first org (or any subsequent org) via the standard PIN ceremony
    without first having to claim a position role.

    Internally: looks up the account by handle, ensures the synthetic
    bootstrap role exists (`<handle>/__org-create__`), generates a
    9-digit PIN against that role, returns the challenge id + relay
    instructions. The PIN surfaces in the user's openbraid panel like
    any other PIN; they read it back to the AI, which calls
    `auth_with_pin` (unchanged) to mint a session_token. That token
    works against `upload_org` (and any other account-level tool)
    because it resolves through the standard role -> account chain.
    """
    if not isinstance(account_handle, str) or not account_handle:
        raise ValueError("account_handle must be a non-empty string")

    account = account_by_handle(account_handle)
    if not account:
        raise ValueError(
            f"No openbraid account found for handle {account_handle!r}. "
            f"Confirm the handle (email-localpart of the signup email) "
            f"or visit openbraid.app/panel to sign in first."
        )

    role_id = ensure_org_create_role(account["id"], account_handle)
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
            f"Tell the user: openbraid is requesting authorization to "
            f"{claim_what}. Ask them to read the 9-digit PIN from their "
            f"openbraid panel at https://www.openbraid.app/panel/roles "
            f"(the org-create PIN is shown in its own card near the top "
            f"of the page) and give it to you, then call auth_with_pin."
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

        # Phase F migration 0010 unified role.name on
        # `<handle>/<org>/<position>`; the to_role argument stays as
        # the bare position id (or accepts a canonical full path). We
        # match suffix `/{to_role}` to find the recipient regardless
        # of which org under this account they sit in. Exact-match the
        # full canonical form first; fall through to suffix-match if
        # the caller passed a short name.
        recipient = (
            supabase()
            .table("roles")
            .select("id, name")
            .eq("account_id", account_id)
            .eq("name", to_role)
            .is_("deleted_at", "null")
            .execute()
        )
        if not recipient.data:
            recipient = (
                supabase()
                .table("roles")
                .select("id, name")
                .eq("account_id", account_id)
                .like("name", f"%/{to_role}")
                .is_("deleted_at", "null")
                .execute()
            )
        if not recipient.data:
            raise ValueError(
                f"No role '{to_role}' found in this account (v0 cross-account "
                f"routing is not supported; use 'file' to file a memo-to-file "
                f"in your own role's notes folder)"
            )
        if len(recipient.data) > 1:
            matches = ", ".join(r["name"] for r in recipient.data)
            raise ValueError(
                f"Ambiguous recipient '{to_role}' — multiple roles match "
                f"({matches}). Use the full canonical name (e.g. "
                f"'<handle>/<org>/<position>') to disambiguate."
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
    """Ingest an orgdef .opencatalog artifact as canonical content for
    an `<account>/<org_slug>` URL.

    Phase E opencatalog-refactor (post orgdef SCHEMA v1.0.0). An
    orgdef is now ONE atomic catalog: the top-level catdef envelope
    plus an `items[]` array carrying type-tagged entries
    (`orgdef:Position`, `roledef:Job`, optionally `roledef:Role`).
    Jobs live INSIDE the bundle; there is no separate upload_job
    surface. The artifact is stored byte-equivalent in JSONB.

    Validation runs BEFORE any DB work:
      - catdef substrate envelope (catdef, orgdef, type, id, name, version)
      - type MUST be "orgdef:Organization"
      - items MUST be an array (may be empty); each item MUST carry
        type + id (string, non-empty)
      - internal consistency:
          - every Position.job_definition.id resolves to a sibling
            roledef:Job item with the same id (unless the position
            carries an explicit URL declaring external resolution)
          - every relationships[].from / .to that doesn't start with
            "external:" resolves to a sibling Position item id

    Args:
        session_token: From a successful `auth_with_pin`. The role's
            account is the upload owner.
        org_slug: URL slug. SHOULD equal content["id"]; mismatch
            surfaces via `slug_id_mismatch` in the receipt.
        content: The .opencatalog artifact as a parsed dict.

    Returns:
        dict with: artifact_id, org_slug, version, position_count,
        job_count, role_count, byte_count, slug_id_mismatch.
    """
    # Validate BEFORE any DB call so malformed input fast-fails without
    # a Supabase round-trip (and so unit tests don't need to mock the
    # role lookup just to exercise validation).
    _validate_opencatalog_content(content, org_slug)

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

    return upload_org_for_account(account_id, org_slug, content)


def _validate_opencatalog_content(content, org_slug: str) -> None:
    """SCHEMA v1.0.0 envelope + items + internal-consistency checks.

    Shared by `tool_upload_org_impl` (MCP) and `upload_org_for_account`
    (panel). Raises ValueError on any failure. No DB calls.
    """
    if not isinstance(content, dict):
        raise ValueError(
            "content must be a JSON object (dict), got %s" % type(content).__name__
        )
    _require_field(content, "catdef", str)
    _require_field(content, "orgdef", str)
    _require_field(content, "type", str)
    if content["type"] != "orgdef:Organization":
        raise ValueError(
            f"content.type must be 'orgdef:Organization' for ingest; "
            f"got {content['type']!r}."
        )
    _require_field(content, "id", str)
    _require_field(content, "name", str)
    _require_field(content, "version", str)

    items = content.get("items")
    if not isinstance(items, list):
        raise ValueError(
            "content.items must be an array per orgdef SCHEMA v1.0.0 "
            f"(.opencatalog substrate); got {type(items).__name__}"
        )
    _validate_items(items)
    _validate_internal_consistency(content)

    if not isinstance(org_slug, str) or not org_slug:
        raise ValueError("org_slug must be a non-empty string")
    if "/" in org_slug or " " in org_slug:
        raise ValueError(
            f"org_slug must not contain '/' or whitespace; got {org_slug!r}"
        )


def upload_org_for_account(
    account_id: str,
    org_slug: str,
    content: dict,
) -> dict:
    """Ingest path shared by the MCP tool wrapper and the panel upload
    affordance. Validates + upserts the artifact under the given
    account. Same receipt shape as `tool_upload_org_impl`.

    Synchronous helper — no auth lookup. Callers are responsible for
    resolving the account_id (MCP via session_token, panel via the
    Supabase user session).
    """
    _validate_opencatalog_content(content, org_slug)

    slug_id_mismatch = org_slug != content["id"]
    items = content["items"]

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

    position_count = sum(
        1 for it in items if isinstance(it, dict) and it.get("type") == "orgdef:Position"
    )
    job_count = sum(
        1 for it in items if isinstance(it, dict) and it.get("type") == "roledef:Job"
    )
    role_count = sum(
        1 for it in items if isinstance(it, dict) and it.get("type") == "roledef:Role"
    )

    import json
    byte_count = len(json.dumps(content, separators=(",", ":")))

    return {
        "artifact_id": artifact_id,
        "org_slug": org_slug,
        "version": content["version"],
        "position_count": position_count,
        "job_count": job_count,
        "role_count": role_count,
        "byte_count": byte_count,
        "slug_id_mismatch": slug_id_mismatch,
    }


async def tool_read_org_impl(account_handle: str, org_slug: str) -> dict:
    """Return the stored opencatalog content for `<account>/<org_slug>`.

    Phase F follow-up — closes the read-side gap in the MCP edit
    surface. AI clients calling `update_position` / `update_org_metadata`
    / `update_relationship` etc. need visibility into current state to
    compose useful patches; before this tool, they had to fetch via
    the public REST `/api/export/<account>/<org_slug>` endpoint
    out-of-band. Now both transports route through this shared impl.

    Auth posture mirrors `export_org`: public read. Boot URLs are
    public per OAGP v0; this is the same content with a structured
    return shape suited to MCP consumers.

    Returns:
        dict with: artifact_id (str), org_slug (str), version (str),
        content (dict — the full opencatalog), content_sha256 (str —
        lowercase-hex SHA-256 of canonical JSON bytes; matches what
        the export endpoint serves in `X-Content-SHA256`).

    Raises:
        ValueError on unknown handle or unknown slug (the MCP / REST
        wrappers translate to 404).
    """
    if not isinstance(account_handle, str) or not account_handle:
        raise ValueError("account_handle must be a non-empty string")
    if not isinstance(org_slug, str) or not org_slug:
        raise ValueError("org_slug must be a non-empty string")

    account = account_by_handle(account_handle)
    if not account:
        raise ValueError(f"No openbraid account found for handle {account_handle!r}")
    artifact = artifact_by_account_and_slug(account["id"], org_slug)
    if not artifact:
        raise ValueError(
            f"No org artifact found at {account_handle}/{org_slug}"
        )
    content = artifact["content"]
    return {
        "artifact_id": artifact["id"],
        "org_slug": artifact["org_slug"],
        "version": artifact.get("version") or content.get("version"),
        "content": content,
        "content_sha256": sha256_hex(content),
    }


def _validate_items(items: list) -> None:
    """Validate each item carries non-empty type + id."""
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"items[{idx}] must be an object; got {type(item).__name__}"
            )
        item_type = item.get("type")
        if not isinstance(item_type, str) or not item_type:
            raise ValueError(
                f"items[{idx}] must carry a non-empty 'type' field"
            )
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(
                f"items[{idx}] (type={item_type!r}) must carry a "
                f"non-empty 'id' field"
            )


def _validate_internal_consistency(content: dict) -> None:
    """Enforce SCHEMA v1.0.0 internal-consistency rules.

    Two checks:
      1. Every Position.job_definition.id resolves to a sibling
         roledef:Job item in the same opencatalog (unless the
         job_definition declares an explicit external URL).
      2. Every relationships[].from/to that's not prefixed
         "external:" resolves to a sibling Position item id.
    """
    items = content.get("items") or []
    position_ids = {
        it["id"] for it in items
        if isinstance(it, dict) and it.get("type") == "orgdef:Position"
    }
    job_ids = {
        it["id"] for it in items
        if isinstance(it, dict) and it.get("type") == "roledef:Job"
    }

    for it in items:
        if not isinstance(it, dict) or it.get("type") != "orgdef:Position":
            continue
        jd = it.get("job_definition")
        if not isinstance(jd, dict):
            continue
        jd_id = jd.get("id")
        if not isinstance(jd_id, str):
            continue
        if jd_id in job_ids:
            continue
        if isinstance(jd.get("url"), str) and jd["url"]:
            # External resolution declared; consistency check skipped.
            continue
        raise ValueError(
            f"Position {it['id']!r}.job_definition.id={jd_id!r} does "
            f"not resolve to a sibling roledef:Job item in this "
            f"opencatalog, and no external URL is declared."
        )

    relationships = content.get("relationships") or []
    if not isinstance(relationships, list):
        return
    for idx, rel in enumerate(relationships):
        if not isinstance(rel, dict):
            continue
        for endpoint in ("from", "to"):
            target = rel.get(endpoint)
            if not isinstance(target, str) or not target:
                continue
            if target.startswith("external:"):
                continue
            # The org's own id is also a valid endpoint (the org itself
            # is in a relationship with externals, e.g. "implements_for").
            if target == content.get("id"):
                continue
            if target not in position_ids:
                raise ValueError(
                    f"relationships[{idx}].{endpoint}={target!r} does "
                    f"not resolve to a sibling Position item id, the "
                    f"org's own id, or an external: reference."
                )


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


# --- F-edit: patch-shaped edit tools for org_artifacts --------------------
#
# Per the 2026-05-11 reframe memo (engineer → strategist): editing
# happens conversationally in the user's AI client via MCP tools.
# openbraid stays the persistence + auth substrate; the panel stays
# read-only. The tools below take patches and write back the full
# canonical artifact, bumping version + logging an audit row each time.


_SEMVER_PARTS = ("major", "minor", "patch")


def _bump_semver(version: str, kind: str = "patch") -> str:
    """Increment a dotted semver-ish string.

    Tolerant: non-numeric segments are left intact (e.g. "1.0.0-rc1"
    → "1.0.1-rc1" on patch bump). Three-segment "M.N.P" is the common
    case; shorter strings get padded with zeros before bumping.
    """
    if kind not in _SEMVER_PARTS:
        raise ValueError(
            f"bump kind must be one of {_SEMVER_PARTS}; got {kind!r}"
        )
    if not isinstance(version, str) or not version:
        return "0.0.1"
    parts = version.split(".")
    # Pad to three numeric parts.
    while len(parts) < 3:
        parts.append("0")
    idx = _SEMVER_PARTS.index(kind)
    # Strip any trailing non-numeric suffix on the target segment.
    target = parts[idx]
    digits = ""
    suffix = ""
    for i, ch in enumerate(target):
        if ch.isdigit():
            digits += ch
        else:
            suffix = target[i:]
            break
    n = int(digits) if digits else 0
    parts[idx] = f"{n + 1}{suffix}"
    # Zero everything to the right of the bumped segment.
    for i in range(idx + 1, 3):
        parts[i] = "0"
    return ".".join(parts)


def _resolve_account_for_session(session_token: str) -> str:
    """Resolve session_token → account_id via the role lookup chain."""
    role_id = get_role_id_from_token(session_token)
    lookup = (
        supabase()
        .table("roles")
        .select("account_id")
        .eq("id", role_id)
        .execute()
    )
    if not lookup.data:
        raise ValueError("Session token's role no longer exists")
    return role_id, lookup.data[0]["account_id"]


def _load_artifact_for_edit(
    account_id: str,
    org_slug: str,
    expected_version: str | None,
) -> dict:
    """Fetch the artifact + content for an edit operation.

    Returns the org_artifacts row (with `content` populated). Raises:
      - ValueError if no artifact for (account, slug)
      - ValueError if the artifact is in replicant state (master_url
        points elsewhere — editing is locked)
      - ValueError if expected_version is set and doesn't match the
        stored version (optimistic concurrency check)
    """
    result = (
        supabase()
        .table("org_artifacts")
        .select("id, account_id, org_slug, content, version, created_at, updated_at")
        .eq("account_id", account_id)
        .eq("org_slug", org_slug)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        raise ValueError(
            f"No org artifact found for slug {org_slug!r} on this account. "
            f"Upload it via upload_org before editing."
        )
    artifact = result.data[0]
    master = detect_master_state(artifact["content"])
    if not master["is_editable"]:
        raise ValueError(
            f"Org {org_slug!r} is a replicant (master at "
            f"{master['master_url']!r}); editing is locked here. "
            f"Edit at the master and resync."
        )
    if expected_version is not None and expected_version != artifact["version"]:
        raise ValueError(
            f"version conflict: expected {expected_version!r}, "
            f"current is {artifact['version']!r}. Refetch and retry."
        )
    return artifact


def _save_artifact_after_edit(
    artifact: dict,
    new_content: dict,
    tool_name: str,
    patch_summary: str,
    edited_by_role_id: str,
    applied_fields: list[str] | None = None,
) -> dict:
    """Write the new content back + log the audit row.

    Re-validates the full content against SCHEMA v1.0.0 so a patch
    can't bypass the same gates upload_org enforces. Bumps version
    when the patch didn't explicitly set one. Returns the receipt
    the tool impls hand to MCP / REST.

    Receipt shape (per strategist's note 4):
      - artifact_id, org_slug — identifiers
      - version_before, version_after — version trail
      - edit_log_id — the audit row's id so callers can reference
      - applied_fields — list of top-level keys touched (RFC 7396);
        deletions appear as "-fieldname"
    """
    _validate_opencatalog_content(new_content, artifact["org_slug"])
    new_version = new_content["version"]
    sb = supabase()
    sb.table("org_artifacts").update(
        {
            "content": new_content,
            "version": new_version,
            "updated_at": "now()",
        }
    ).eq("id", artifact["id"]).execute()
    audit_insert = (
        sb.table("org_artifact_edits")
        .insert(
            {
                "org_artifact_id": artifact["id"],
                "edited_by_role_id": edited_by_role_id,
                "tool_name": tool_name,
                "patch_summary": patch_summary,
                "version_before": artifact["version"],
                "version_after": new_version,
            }
        )
        .execute()
    )
    edit_log_id = (
        audit_insert.data[0]["id"]
        if audit_insert.data
        else None
    )
    return {
        "artifact_id": artifact["id"],
        "org_slug": artifact["org_slug"],
        "version_before": artifact["version"],
        "version_after": new_version,
        "edit_log_id": edit_log_id,
        "applied_fields": applied_fields or [],
    }


def _apply_patch(target: dict, patch: dict) -> list[str]:
    """Apply a JSON Merge Patch (RFC 7396) to `target` in place.

    Per RFC 7396:
      - Each top-level key in `patch` replaces the same key in `target`
      - A `null` value in `patch` REMOVES that key from `target`
        (rather than setting it to None)
      - Nested dicts are replaced wholesale — we do NOT recurse into
        them. This is a deliberate simplification: openbraid's
        position-level fields and catalog-level fields are flat enough
        that wholesale replacement is the predictable semantic; AI
        clients composing nested edits should pass the full new
        nested value.

    Returns the list of top-level keys that were touched (for the
    receipt's `applied_fields` per strategist's note 4).
    """
    applied = []
    for k, v in patch.items():
        if v is None:
            if k in target:
                del target[k]
                applied.append(f"-{k}")
        else:
            target[k] = v
            applied.append(k)
    return applied


def _summarize_patch(prefix: str, patch: dict) -> str:
    """Render a short human-readable patch summary for the audit row."""
    bits = []
    for k, v in patch.items():
        if v is None:
            bits.append(f"-{k}")  # RFC 7396 deletion
        elif isinstance(v, list):
            bits.append(f"{k} ({len(v)} items)")
        elif isinstance(v, dict):
            bits.append(f"{k} (object)")
        elif isinstance(v, str):
            n = len(v)
            bits.append(f"{k} ({n} chars)" if n > 60 else f"{k}")
        else:
            bits.append(k)
    return f"{prefix} → " + ", ".join(bits) if bits else prefix


async def tool_update_position_impl(
    session_token: str,
    org_slug: str,
    position_id: str,
    patch: dict,
    expected_version: str | None = None,
) -> dict:
    """Patch a single Position item's fields.

    `patch` is a partial dict of position-level fields. Top-level keys
    in patch replace the same keys in the position item; arrays
    (responsibilities[], deliverables[], success_indicators[]) are
    replaced wholesale rather than appended — callers compose the
    full new array.

    Auto-bumps the artifact's patch-level version unless `patch`
    explicitly carries a `version` field at the catalog level (it
    doesn't — patch applies to the position item, not the catalog).

    Replicant orgs reject editing with a friendly error.
    """
    if not isinstance(patch, dict) or not patch:
        raise ValueError("patch must be a non-empty JSON object")
    if "id" in patch and patch["id"] != position_id:
        raise ValueError(
            "patch must not change the position's id; "
            "delete + add a fresh item if you need to rename"
        )
    if "type" in patch and patch["type"] != "orgdef:Position":
        raise ValueError(
            "patch must not change item type"
        )

    role_id, account_id = _resolve_account_for_session(session_token)
    artifact = _load_artifact_for_edit(account_id, org_slug, expected_version)

    content = artifact["content"]
    items = content.get("items") or []
    target_idx = None
    for i, it in enumerate(items):
        if isinstance(it, dict) and it.get("id") == position_id and it.get("type") == "orgdef:Position":
            target_idx = i
            break
    if target_idx is None:
        raise ValueError(
            f"No Position item with id {position_id!r} in org {org_slug!r}"
        )

    new_content = dict(content)
    new_items = list(items)
    new_position = dict(items[target_idx])
    applied_fields = _apply_patch(new_position, patch)
    new_items[target_idx] = new_position
    new_content["items"] = new_items
    new_content["version"] = _bump_semver(content.get("version", "0.0.0"), "patch")

    return _save_artifact_after_edit(
        artifact,
        new_content,
        tool_name="update_position",
        patch_summary=_summarize_patch(
            f"update_position {position_id}", patch
        ),
        edited_by_role_id=role_id,
        applied_fields=applied_fields,
    )


_PROTECTED_CATALOG_KEYS = frozenset({"catdef", "orgdef", "type", "id", "items"})


async def tool_update_org_metadata_impl(
    session_token: str,
    org_slug: str,
    patch: dict,
    expected_version: str | None = None,
) -> dict:
    """Patch catalog-level org metadata.

    `patch` is a partial dict of top-level fields: name, mission,
    vision, scope, governance_model, values, red_lines, description,
    recommended_patterns, relationships, x.org.master_url,
    x.org.org_location, x.* extensions. Same wholesale-replacement
    semantics as update_position.

    Cannot touch: catdef envelope (catdef, orgdef, type), id, or
    items[] — those have dedicated tools / immutable structure.
    `version` patches are accepted (caller can drive explicit semver);
    when absent, patch-version auto-bumps.
    """
    if not isinstance(patch, dict) or not patch:
        raise ValueError("patch must be a non-empty JSON object")
    forbidden = _PROTECTED_CATALOG_KEYS & set(patch.keys())
    if forbidden:
        raise ValueError(
            f"patch cannot change protected catalog keys "
            f"{sorted(forbidden)}; use the dedicated tools or upload "
            f"a new artifact via upload_org."
        )

    role_id, account_id = _resolve_account_for_session(session_token)
    artifact = _load_artifact_for_edit(account_id, org_slug, expected_version)

    new_content = dict(artifact["content"])
    applied_fields = _apply_patch(new_content, patch)
    if "version" not in patch:
        new_content["version"] = _bump_semver(
            new_content.get("version", "0.0.0"), "patch"
        )

    return _save_artifact_after_edit(
        artifact,
        new_content,
        tool_name="update_org_metadata",
        patch_summary=_summarize_patch("update_org_metadata", patch),
        edited_by_role_id=role_id,
        applied_fields=applied_fields,
    )


async def tool_bump_version_impl(
    session_token: str,
    org_slug: str,
    kind: str = "patch",
    expected_version: str | None = None,
) -> dict:
    """Explicit version bump without other changes.

    Callers that want to batch several edits and stamp a coherent
    version at the end can call this last with kind="minor" or
    kind="major". Updates the audit log with a "bump_version" row so
    the version trail is reconstructable.
    """
    if kind not in _SEMVER_PARTS:
        raise ValueError(
            f"kind must be one of {_SEMVER_PARTS}; got {kind!r}"
        )
    role_id, account_id = _resolve_account_for_session(session_token)
    artifact = _load_artifact_for_edit(account_id, org_slug, expected_version)

    new_content = dict(artifact["content"])
    new_content["version"] = _bump_semver(
        new_content.get("version", "0.0.0"), kind
    )

    return _save_artifact_after_edit(
        artifact,
        new_content,
        tool_name="bump_version",
        patch_summary=f"bump_version → {kind}",
        edited_by_role_id=role_id,
    )


_KNOWN_RELATIONSHIP_TYPES = frozenset({
    "reports_to",
    "directs",
    "coordinates_with",
    "validates_for",
    "peer_of",
    "implements_for",
    "derives_from",
})


async def tool_add_position_impl(
    session_token: str,
    org_slug: str,
    position: dict,
    expected_version: str | None = None,
) -> dict:
    """Add a new orgdef:Position item to an opencatalog.

    `position` is the full item dict (id, name, optional role_definition,
    optional job_definition, optional description / responsibilities /
    deliverables / etc.). The item's `type` field is set to
    `orgdef:Position` if absent; an explicit non-Position type is
    rejected.

    Validations beyond catalog-level revalidation:
      - position.id must be non-empty and not already taken
      - if position.job_definition.id is set, must resolve to a
        sibling roledef:Job item (or carry external URL); same
        consistency rule upload_org enforces
    """
    if not isinstance(position, dict):
        raise ValueError("position must be a JSON object")
    if not position.get("type"):
        position = {**position, "type": "orgdef:Position"}
    if position.get("type") != "orgdef:Position":
        raise ValueError(
            f"position.type must be 'orgdef:Position'; "
            f"got {position.get('type')!r}"
        )
    new_id = position.get("id")
    if not isinstance(new_id, str) or not new_id:
        raise ValueError("position.id must be a non-empty string")
    if not position.get("name"):
        raise ValueError("position.name must be set")

    role_id, account_id = _resolve_account_for_session(session_token)
    artifact = _load_artifact_for_edit(account_id, org_slug, expected_version)

    content = artifact["content"]
    items = content.get("items") or []
    for it in items:
        if isinstance(it, dict) and it.get("type") == "orgdef:Position" and it.get("id") == new_id:
            raise ValueError(
                f"Position id {new_id!r} already exists in org {org_slug!r}"
            )

    new_content = dict(content)
    new_content["items"] = list(items) + [position]
    new_content["version"] = _bump_semver(
        content.get("version", "0.0.0"), "patch"
    )

    return _save_artifact_after_edit(
        artifact,
        new_content,
        tool_name="add_position",
        patch_summary=f"add_position {new_id}",
        edited_by_role_id=role_id,
        applied_fields=[f"+position:{new_id}"],
    )


async def tool_delete_position_impl(
    session_token: str,
    org_slug: str,
    position_id: str,
    expected_version: str | None = None,
) -> dict:
    """Remove an orgdef:Position item from an opencatalog.

    Per orgdef-strategist's 2026-05-11 17:30 memo: a position with a
    live incumbents binding carrying active auth_sessions BLOCKS the
    delete. Director must revoke active sessions (or end the binding)
    before delete is allowed. This is the most conservative of the
    three options the strategist memo enumerated.

    Also cleans up the relationships[] array — any edge whose
    endpoint is the deleted position is removed so the artifact's
    internal consistency stays whole.

    Pure-data delete (no incumbents row, no active sessions) succeeds
    immediately.
    """
    if not isinstance(position_id, str) or not position_id:
        raise ValueError("position_id must be a non-empty string")

    role_id, account_id = _resolve_account_for_session(session_token)
    artifact = _load_artifact_for_edit(account_id, org_slug, expected_version)

    content = artifact["content"]
    items = content.get("items") or []

    found = False
    for it in items:
        if isinstance(it, dict) and it.get("type") == "orgdef:Position" and it.get("id") == position_id:
            found = True
            break
    if not found:
        raise ValueError(
            f"No Position item with id {position_id!r} in org {org_slug!r}"
        )

    # Block-when-claimed: an incumbents row + active auth_sessions on
    # the bound role means a fresh AI is currently inhabiting this
    # position. Refuse the delete and tell the caller what to do.
    sb = supabase()
    incumbent_row = (
        sb.table("incumbents")
        .select("id, claimed_role_id")
        .eq("org_artifact_id", artifact["id"])
        .eq("position_id", position_id)
        .is_("ended_at", "null")
        .execute()
    )
    if incumbent_row.data:
        bound_role_id = incumbent_row.data[0]["claimed_role_id"]
        sessions = (
            sb.table("auth_sessions")
            .select("id")
            .eq("role_id", bound_role_id)
            .is_("revoked_at", "null")
            .gt("expires_at", "now()")
            .execute()
        )
        if sessions.data:
            raise ValueError(
                f"Cannot delete position {position_id!r}: "
                f"{len(sessions.data)} active session(s) on the bound role. "
                f"Revoke the session(s) via /panel/sessions/<id>/revoke "
                f"or end the incumbents binding, then retry."
            )

    new_items = [
        it for it in items
        if not (
            isinstance(it, dict)
            and it.get("type") == "orgdef:Position"
            and it.get("id") == position_id
        )
    ]
    relationships = content.get("relationships") or []
    new_relationships = [
        rel for rel in relationships
        if not (
            isinstance(rel, dict)
            and (rel.get("from") == position_id or rel.get("to") == position_id)
        )
    ]
    edges_removed = len(relationships) - len(new_relationships)

    new_content = dict(content)
    new_content["items"] = new_items
    new_content["relationships"] = new_relationships
    new_content["version"] = _bump_semver(
        content.get("version", "0.0.0"), "patch"
    )

    applied = [f"-position:{position_id}"]
    if edges_removed:
        applied.append(f"-edges:{edges_removed}")

    return _save_artifact_after_edit(
        artifact,
        new_content,
        tool_name="delete_position",
        patch_summary=(
            f"delete_position {position_id}"
            + (f" (also dropped {edges_removed} relationships)" if edges_removed else "")
        ),
        edited_by_role_id=role_id,
        applied_fields=applied,
    )


async def tool_update_relationship_impl(
    session_token: str,
    org_slug: str,
    rtype: str,
    from_id: str,
    to_id: str,
    op: str = "add",
    expected_version: str | None = None,
) -> dict:
    """Add or remove a relationships[] entry.

    `op` is "add" or "remove". For "add", a relationship row
    `{type: rtype, from: from_id, to: to_id}` is appended (idempotent —
    if an identical row already exists, the call is a no-op succeeded).
    For "remove", any matching `(type, from, to)` rows are dropped.

    Validations:
      - rtype must be in the known set (reports_to / directs /
        coordinates_with / validates_for / peer_of / implements_for /
        derives_from). Unknown types are rejected — addiing a new
        relationship type belongs upstream in orgdef-spec, not here.
      - For "add": from_id and to_id must resolve to sibling Position
        items, the org's own id, or an `external:` reference. Same
        endpoint resolution rule upload_org enforces.
      - For "remove": no endpoint validation (idempotent cleanup).
    """
    if rtype not in _KNOWN_RELATIONSHIP_TYPES:
        raise ValueError(
            f"rtype must be one of {sorted(_KNOWN_RELATIONSHIP_TYPES)}; "
            f"got {rtype!r}. Adding a new relationship type belongs "
            f"upstream in orgdef-spec."
        )
    if op not in ("add", "remove"):
        raise ValueError(f"op must be 'add' or 'remove'; got {op!r}")
    if not isinstance(from_id, str) or not from_id:
        raise ValueError("from_id must be a non-empty string")
    if not isinstance(to_id, str) or not to_id:
        raise ValueError("to_id must be a non-empty string")

    role_id, account_id = _resolve_account_for_session(session_token)
    artifact = _load_artifact_for_edit(account_id, org_slug, expected_version)

    content = artifact["content"]
    items = content.get("items") or []
    position_ids = {
        it["id"] for it in items
        if isinstance(it, dict) and it.get("type") == "orgdef:Position"
    }
    org_self_id = content.get("id")

    def _endpoint_ok(ep: str) -> bool:
        return (
            ep in position_ids
            or ep == org_self_id
            or ep.startswith("external:")
        )

    if op == "add":
        if not _endpoint_ok(from_id):
            raise ValueError(
                f"from_id {from_id!r} does not resolve to a sibling "
                f"Position, the org's own id, or an 'external:' reference"
            )
        if not _endpoint_ok(to_id):
            raise ValueError(
                f"to_id {to_id!r} does not resolve to a sibling "
                f"Position, the org's own id, or an 'external:' reference"
            )

    relationships = content.get("relationships") or []
    if op == "add":
        already = any(
            isinstance(r, dict)
            and r.get("type") == rtype
            and r.get("from") == from_id
            and r.get("to") == to_id
            for r in relationships
        )
        if already:
            # Idempotent no-op — return the receipt without bumping
            # version. Audit row also skipped (nothing changed).
            return {
                "artifact_id": artifact["id"],
                "org_slug": artifact["org_slug"],
                "version_before": artifact["version"],
                "version_after": artifact["version"],
                "edit_log_id": None,
                "applied_fields": [],
            }
        new_relationships = list(relationships) + [
            {"type": rtype, "from": from_id, "to": to_id}
        ]
        applied = [f"+edge:{rtype}:{from_id}->{to_id}"]
        summary = f"update_relationship add {rtype} {from_id}→{to_id}"
    else:  # remove
        new_relationships = [
            r for r in relationships
            if not (
                isinstance(r, dict)
                and r.get("type") == rtype
                and r.get("from") == from_id
                and r.get("to") == to_id
            )
        ]
        removed = len(relationships) - len(new_relationships)
        if not removed:
            # Idempotent no-op for unknown edges; same shape as add.
            return {
                "artifact_id": artifact["id"],
                "org_slug": artifact["org_slug"],
                "version_before": artifact["version"],
                "version_after": artifact["version"],
                "edit_log_id": None,
                "applied_fields": [],
            }
        applied = [f"-edge:{rtype}:{from_id}->{to_id}"]
        summary = f"update_relationship remove {rtype} {from_id}→{to_id}"

    new_content = dict(content)
    new_content["relationships"] = new_relationships
    new_content["version"] = _bump_semver(
        content.get("version", "0.0.0"), "patch"
    )

    return _save_artifact_after_edit(
        artifact,
        new_content,
        tool_name="update_relationship",
        patch_summary=summary,
        edited_by_role_id=role_id,
        applied_fields=applied,
    )
