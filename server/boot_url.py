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

from server.db import (
    account_by_handle,
    artifact_by_account_and_slug,
    artifacts_for_account,
    find_job_in_artifact,
    find_position_in_artifact,
    org_by_name,
    orgs_for_account,
    position_by_name,
    supabase,
)


def _resolve_job_definition_payload(
    artifact_content: dict, position_data: dict
) -> dict | None:
    """Build the `job_definition` field for an artifact-backed boot payload.

    Per orgdef SCHEMA v1.0.0 (.opencatalog), the job a position references
    lives as a sibling item inside the same artifact's items[] array,
    looked up by `position.job_definition.id`. We embed the full Job
    item inline when present. If the position carries `job_definition`
    but no matching sibling Job exists (and no external URL is declared),
    return a reference shape with a diagnostic.
    """
    jd = position_data.get("job_definition")
    if not isinstance(jd, dict):
        return None
    jd_id = jd.get("id")
    base = {
        "id": jd_id,
        "version": jd.get("version"),
        "url": jd.get("url"),
    }
    if isinstance(jd_id, str) and jd_id:
        job_item = find_job_in_artifact(artifact_content, jd_id)
        if job_item:
            base["content"] = job_item
            return base
    if isinstance(jd.get("url"), str) and jd["url"]:
        base["diagnostic"] = (
            "Job referenced via external URL; cross-bundle resolution "
            "is deferred to E3-style on-demand fetch."
        )
        return base
    base["diagnostic"] = (
        f"Position references job_definition.id={jd_id!r} but no "
        f"sibling roledef:Job item with that id exists in this "
        f"opencatalog. Re-upload the orgdef with the job included."
    )
    return base


def _build_artifact_boot_payload(
    account: dict,
    artifact: dict,
    position_data: dict,
    canonical_url: str,
) -> dict:
    """Build the C4 boot payload from an artifact-backed position.

    Phase E1-cutover: when a position resolves from `org_artifacts`
    instead of the legacy `orgs`/`roles` tables, the boot payload's
    `position` and `org_summary` come from the artifact's canonical
    `content`. `role_definition` and `job_definition` are passed
    through as references for E3/E2 to fetch later. `incumbent` and
    `inbox_summary` are stub-shaped — full population lands when the
    `incumbents` table maps artifact positions to openbraid roles
    (future PR; tracked in the Phase E roadmap).
    """
    content = artifact["content"]
    return {
        "position": {
            "id": position_data.get("id"),
            "name": position_data.get("name", position_data.get("id")),
            "org_id": artifact["id"],
            "account_id": account["id"],
            "role_definition": position_data.get("role_definition"),
            "description": position_data.get("description"),
            "status": position_data.get("status"),
            "incumbent": position_data.get("incumbent"),
        },
        "org_summary": {
            "id": artifact["id"],
            "name": content.get("name"),
            "slug": artifact["org_slug"],
            "version": artifact.get("version"),
            "mission": content.get("mission"),
            "vision": content.get("vision"),
            "scope": content.get("scope"),
            "governance_model": content.get("governance_model"),
            "org_location": content.get("x.org.org_location"),
        },
        "role_definition": position_data.get("role_definition"),
        "job_definition": _resolve_job_definition_payload(
            content, position_data
        ),
        "incumbent": {
            "active_sessions": 0,
            "claimable": False,
            "diagnostic": (
                "Artifact-backed positions in Phase E1-cutover are read-only. "
                "The incumbents table (mapping artifact positions to openbraid "
                "auth identities) lands in a future PR; until then, claim_role "
                "against this URL will fail. The position metadata, org context, "
                "and role/job references are fully exposed for fresh-agent "
                "instantiation contexts that read but don't yet claim."
            ),
        },
        "inbox_summary": {
            "inbox_unread": 0,
            "notes_count": 0,
            "diagnostic": (
                "Per-position memo storage for artifact-backed positions "
                "lands when the incumbents table maps to memo stores."
            ),
        },
        "claim_instruction": None,
        "_backed_by": "artifact",
    }


def _canonical_position_url(
    request: Request, handle: str, org_name: str, position_name: str
) -> str:
    """Build the canonical position URL from the current request's host.

    Self-hosted instances (mcp.firstchurch.org, etc.) get their own host
    in the URL; openbraid.app gets mcp.openbraid.app. The scheme follows
    the request scheme (https in production, http in dev).
    """
    return f"{request.url.scheme}://{request.url.netloc}/{handle}/{org_name}/{position_name}"


def _positions_for_org(org_id: str) -> list[dict]:
    """Return positions (roles) within an org.

    Phase C C3 (full implementation) calls for depth-first walk via
    `reports_to` / `directs` / `validates_for` edges drawn from the
    orgdef artifact's relationships. openbraid v0/v1 doesn't store
    those relationships — orgs and positions are stored, edges are
    not. So this falls back to the ordering rule the orgdef memo
    specifies as the documented fallback for the ambiguous-relationships
    case: the `positions` array order, which we approximate by
    `created_at` asc (the order they were added to the table).

    When openbraid eventually grows relationship storage (a separate
    `position_relationships` table or a JSONB field on orgs), this
    function should be replaced with a real DFS over the edges,
    falling back to created_at when a position has no edges or the
    walk is ambiguous.
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


def _build_boot_payload(
    account: dict, org: dict, position: dict, canonical_url: str | None = None
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
            "org_location": org.get("org_location"),
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
            f"position_url=\"{canonical_url}\". You will receive a challenge_id; "
            f"the human gatekeeper delivers a 9-digit PIN out-of-band (via the "
            f"openbraid panel); call `auth_with_pin` with the challenge_id and "
            f"PIN to complete the claim. Subsequent tool calls use the returned "
            f"session_token."
        ),
    }


# --- Route handlers ---------------------------------------------------------


async def account_orgs_endpoint(request: Request) -> JSONResponse:
    """GET /{account} — list of orgs the account hosts.

    Phase E1-cutover: unions artifact-backed and legacy orgs. When a
    legacy org's name overlaps with an artifact's `org_slug` (e.g.,
    Director's `personal` legacy org also has an artifact uploaded
    later), the artifact wins — its canonical content is the source
    of truth per the orgdef-strategist principle.
    """
    handle = request.path_params["account"]
    account = account_by_handle(handle)
    if not account:
        return JSONResponse({"error": "account not found"}, status_code=404)

    artifacts = artifacts_for_account(account["id"])
    legacy_orgs = orgs_for_account(account["id"])

    artifact_slugs = {a["org_slug"] for a in artifacts}
    items: list[dict] = []
    for a in artifacts:
        c = a["content"]
        items.append(
            {
                "id": a["id"],
                "slug": a["org_slug"],
                "name": c.get("name"),
                "version": a.get("version"),
                "mission": c.get("mission"),
                "_backed_by": "artifact",
            }
        )
    for o in legacy_orgs:
        if o["name"] in artifact_slugs:
            continue
        items.append(
            {
                "id": o["id"],
                "slug": o["name"],
                "name": o["name"],
                "mission": o.get("mission"),
                "_backed_by": "legacy",
            }
        )

    return JSONResponse(
        {
            "account": {
                "id": account["id"],
                "handle": handle,
                "email": account["email"],
            },
            "orgs": items,
        }
    )


async def account_seg2_endpoint(request: Request) -> JSONResponse:
    """GET /{account}/{seg2} — two-segment URL sugar OR org-list.

    Phase E1-cutover: tries (in order):
      1. Artifact match — seg2 is an artifact's org_slug → return that
         artifact's positions list (an "org URL" response).
      2. Legacy single-org sugar — if the account has exactly one
         legacy org (no artifacts), seg2 is a position name.
      3. Legacy multi-org — seg2 is the org name; return positions list.

    Strict spec interpretation of 2-seg sugar requires "exactly one org"
    (artifact + legacy combined). For backward compatibility with v0
    URLs (e.g. /scott/personal-strategist), the legacy single-org-sugar
    path still triggers when the account has no artifacts yet AND
    exactly one legacy org. Adopters who upload artifacts and want
    2-seg-position-shape URLs should use 3-seg URLs going forward.
    """
    handle = request.path_params["account"]
    seg2 = request.path_params["seg2"]
    account = account_by_handle(handle)
    if not account:
        return JSONResponse({"error": "account not found"}, status_code=404)

    # 1. Artifact match — seg2 is an org_slug.
    artifact = artifact_by_account_and_slug(account["id"], seg2)
    if artifact:
        content = artifact["content"]
        items = content.get("items") or []
        position_items = [
            it for it in items
            if isinstance(it, dict) and it.get("type") == "orgdef:Position"
        ]
        return JSONResponse(
            {
                "account": {
                    "id": account["id"],
                    "handle": handle,
                    "email": account["email"],
                },
                "org": {
                    "id": artifact["id"],
                    "slug": artifact["org_slug"],
                    "name": content.get("name"),
                    "version": artifact.get("version"),
                    "mission": content.get("mission"),
                    "vision": content.get("vision"),
                    "scope": content.get("scope"),
                    "governance_model": content.get("governance_model"),
                    "org_location": content.get("x.org.org_location"),
                    "_backed_by": "artifact",
                },
                "positions": [
                    {
                        "id": p.get("id"),
                        "name": p.get("name", p.get("id")),
                        "status": p.get("status"),
                        "role_definition": p.get("role_definition"),
                    }
                    for p in position_items
                ],
            }
        )

    # 2. Legacy single-org sugar (only fires when account has no artifacts
    # AND exactly one legacy org — preserves v0 URLs).
    artifacts = artifacts_for_account(account["id"])
    orgs = orgs_for_account(account["id"])
    if not artifacts and len(orgs) == 1:
        org = orgs[0]
        position = position_by_name(org["id"], seg2)
        if not position:
            return JSONResponse(
                {"error": "position not found in account's only org"},
                status_code=404,
            )
        canonical_url = _canonical_position_url(
            request, handle, org["name"], position["name"]
        )
        return JSONResponse(
            _build_boot_payload(account, org, position, canonical_url)
        )

    # 3. Legacy multi-org — seg2 is an org name.
    org = org_by_name(account["id"], seg2)
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
                "_backed_by": "legacy",
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
    """GET /{account}/{org}/{position} — fresh-agent boot payload.

    Phase E1-cutover: artifact-first read, legacy fallback. When an
    org_artifact exists for (account, org_slug), the boot payload
    derives from the artifact's canonical content. When none exists,
    falls back to the legacy `orgs`/`roles` read path used in Phase C.
    """
    handle = request.path_params["account"]
    org_name = request.path_params["org"]
    position_name = request.path_params["position"]

    account = account_by_handle(handle)
    if not account:
        return JSONResponse({"error": "account not found"}, status_code=404)

    # 1. Artifact-first.
    artifact = artifact_by_account_and_slug(account["id"], org_name)
    if artifact:
        position_data = find_position_in_artifact(
            artifact["content"], position_name
        )
        if not position_data:
            return JSONResponse(
                {"error": "position not found in artifact"},
                status_code=404,
            )
        canonical_url = _canonical_position_url(
            request, handle, org_name, position_name
        )
        return JSONResponse(
            _build_artifact_boot_payload(
                account, artifact, position_data, canonical_url
            )
        )

    # 2. Legacy fallback.
    org = org_by_name(account["id"], org_name)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)

    position = position_by_name(org["id"], position_name)
    if not position:
        return JSONResponse({"error": "position not found"}, status_code=404)

    canonical_url = _canonical_position_url(
        request, handle, org_name, position_name
    )
    return JSONResponse(
        _build_boot_payload(account, org, position, canonical_url)
    )


boot_url_routes = [
    Route("/{account}", account_orgs_endpoint, methods=["GET"]),
    Route("/{account}/{seg2}", account_seg2_endpoint, methods=["GET"]),
    Route(
        "/{account}/{org}/{position}",
        position_boot_endpoint,
        methods=["GET"],
    ),
]
