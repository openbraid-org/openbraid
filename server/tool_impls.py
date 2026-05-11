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
) -> dict:
    """Write the new content back + log the audit row.

    Re-validates the full content against SCHEMA v1.0.0 so a patch
    can't bypass the same gates upload_org enforces. Bumps version
    when the patch didn't explicitly set one. Returns the receipt
    the tool impls hand to MCP / REST.
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
    sb.table("org_artifact_edits").insert(
        {
            "org_artifact_id": artifact["id"],
            "edited_by_role_id": edited_by_role_id,
            "tool_name": tool_name,
            "patch_summary": patch_summary,
            "version_before": artifact["version"],
            "version_after": new_version,
        }
    ).execute()
    return {
        "artifact_id": artifact["id"],
        "org_slug": artifact["org_slug"],
        "version_before": artifact["version"],
        "version_after": new_version,
    }


def _apply_patch(target: dict, patch: dict) -> None:
    """Top-level key replacement: each key in patch overwrites the
    same key in target. Nested dicts/lists are replaced wholesale,
    not deep-merged — caller is expected to compose the full new
    field value when patching arrays."""
    for k, v in patch.items():
        target[k] = v


def _summarize_patch(prefix: str, patch: dict) -> str:
    """Render a short human-readable patch summary for the audit row."""
    bits = []
    for k, v in patch.items():
        if isinstance(v, list):
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
    _apply_patch(new_position, patch)
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
    _apply_patch(new_content, patch)
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
