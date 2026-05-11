"""Panel routes for the openbraid web UI.

Routes:
  GET  /              — landing page (logged-in users redirect to /panel)
  GET  /auth/login    — kick off the OAuth dance
  GET  /auth/callback — handle Supabase's redirect back, set session cookie
  POST /auth/logout   — clear session cookie
  POST /auth/email/login   — email + password sign-in
  POST /auth/email/signup  — email + password sign-up
  GET  /panel         — pending PIN inbox (auth-required)
  GET  /panel/pins    — HTMX partial: live PIN list (auth-required, polled)
  GET  /panel/roles   — role management (list + add) (auth-required)
  POST /panel/roles/new — create a new role for the signed-in account
  GET  /panel/roles/{role_id}/notes — read-only notes browser for a role
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from server.auth import (
    OAUTH_STATE_COOKIE,
    PKCE_VERIFIER_COOKIE,
    SESSION_COOKIE,
    authorize_url,
    exchange_code,
    generate_pkce_pair,
    get_user_from_token,
    sign_in_with_password,
    sign_up_with_password,
)
from server.chart_builder import (
    build_live_map_for_artifact,
    build_live_map_for_legacy_org,
    build_mermaid_for_artifact,
    synthesize_legacy_org_content,
)
from server.db import (
    account_by_handle,
    artifact_by_account_and_slug,
    artifacts_for_account,
    ensure_account,
    ensure_personal_org,
    find_job_in_artifact,
    find_position_in_artifact,
    org_by_name,
    orgs_for_account,
    supabase,
)


def _mcp_origin() -> str:
    """Return the public MCP origin used for canonical position URLs.

    Reads MCP_ORIGIN env var; falls back to deriving from PANEL_ORIGIN
    by replacing the leading `www.` with `mcp.` (the openbraid.app
    convention). Self-hosted instances should set MCP_ORIGIN explicitly
    if their MCP host doesn't follow that pattern.
    """
    explicit = os.environ.get("MCP_ORIGIN")
    if explicit:
        return explicit.rstrip("/")
    panel = os.environ.get("PANEL_ORIGIN", "")
    if "//www." in panel:
        return panel.replace("//www.", "//mcp.").rstrip("/")
    return panel.rstrip("/") or "https://mcp.openbraid.app"

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


async def _current_user(request: Request) -> dict | None:
    """Resolve the current user from the session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await get_user_from_token(token)


def _set_session_cookie(response, access_token: str):
    """Apply the standard session-cookie settings for an issued access token."""
    response.set_cookie(
        SESSION_COOKIE,
        access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=3600,
    )
    return response


async def root(request: Request):
    user = await _current_user(request)
    if user:
        return RedirectResponse("/panel", status_code=303)
    return TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {
            "error": request.query_params.get("error"),
            "notice": request.query_params.get("notice"),
        },
    )


async def email_login(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""
    if not email or not password:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "Email and password are required.", "email": email},
            status_code=400,
        )
    try:
        tokens = await sign_in_with_password(email, password)
    except ValueError as e:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": str(e), "email": email},
            status_code=400,
        )
    access_token = tokens.get("access_token")
    if not access_token:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "Sign-in succeeded but no token was returned.", "email": email},
            status_code=500,
        )
    return _set_session_cookie(
        RedirectResponse("/panel", status_code=303), access_token
    )


async def email_signup(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""
    if not email or not password:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "Email and password are required.", "email": email},
            status_code=400,
        )
    if len(password) < 6:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "Password must be at least 6 characters.", "email": email},
            status_code=400,
        )
    try:
        result = await sign_up_with_password(email, password)
    except ValueError as e:
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": str(e), "email": email},
            status_code=400,
        )

    # Auto-create the openbraid `accounts` row so the user lands on a
    # working /panel instead of the "No openbraid account found" empty
    # state. Idempotent: links existing rows (e.g. the bootstrap row)
    # to the new Supabase Auth user, otherwise inserts a fresh one.
    supabase_user_id = (result.get("user") or {}).get("id")
    if supabase_user_id:
        try:
            ensure_account(email, supabase_user_id)
        except Exception:  # noqa: BLE001 — failure here shouldn't block sign-up
            # If accounts-row creation fails for any reason (DB hiccup,
            # constraint mismatch on legacy rows, etc.), don't block
            # the user from signing in. They'll see "No openbraid
            # account found" on the panel and can be unblocked manually.
            # Logging would be ideal here; defer adding a logger until
            # the same kind of diagnostic hygiene we did for auth.py.
            pass

    access_token = result.get("access_token")
    if access_token:
        # Email confirmation is disabled in this Supabase project — sign
        # the user in directly.
        return _set_session_cookie(
            RedirectResponse("/panel", status_code=303), access_token
        )
    return TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {
            "notice": (
                f"Account created. Check {email} for a confirmation link "
                f"to complete sign-up, then come back and sign in."
            )
        },
    )


async def login(request: Request):
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    response = RedirectResponse(authorize_url(challenge))
    cookie_kwargs = dict(httponly=True, secure=True, samesite="lax", max_age=600)
    response.set_cookie(PKCE_VERIFIER_COOKIE, verifier, **cookie_kwargs)
    response.set_cookie(OAUTH_STATE_COOKIE, state, **cookie_kwargs)
    return response


async def callback(request: Request):
    code = request.query_params.get("code")
    verifier = request.cookies.get(PKCE_VERIFIER_COOKIE)
    if not code:
        return HTMLResponse("Missing OAuth code in callback", status_code=400)
    if not verifier:
        return HTMLResponse(
            "Missing PKCE verifier cookie — start over from /auth/login",
            status_code=400,
        )

    try:
        tokens = await exchange_code(code, verifier)
    except Exception as e:  # noqa: BLE001 — surface the failure to the user
        return HTMLResponse(f"OAuth code exchange failed: {e}", status_code=400)

    access_token = tokens.get("access_token")
    if not access_token:
        return HTMLResponse("OAuth token response missing access_token", status_code=400)

    response = RedirectResponse("/panel", status_code=303)
    response.delete_cookie(PKCE_VERIFIER_COOKIE)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return _set_session_cookie(response, access_token)


async def logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


async def panel_redirect(request: Request):
    """Phase F F4 consolidated control panel: /panel now redirects to
    /panel/roles, which is the unified live-control surface (roles +
    sessions + PINs all on one page, per-card polling)."""
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/panel/roles", status_code=303)


async def panel(request: Request):
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)
    return TEMPLATES.TemplateResponse(request, "panel.html", {"user": user})


async def pin_list(request: Request):
    """HTMX partial: pending PINs for the signed-in user's account.

    Two-query approach (resolve roles first, then PINs by role_id) —
    cleaner than a postgrest embedded-resource filter and just as fast
    at v0 cardinality (a handful of roles per account).
    """
    user = await _current_user(request)
    if not user:
        return Response("Unauthorized", status_code=401)

    email = user.get("email")
    if not email:
        return Response("No email on user", status_code=400)

    accounts = (
        supabase()
        .table("accounts")
        .select("id")
        .eq("email", email)
        .is_("deleted_at", "null")
        .execute()
    )
    if not accounts.data:
        return TEMPLATES.TemplateResponse(
            request,
            "_pin_list.html",
            {"pins": [], "no_account": True, "email": email},
        )
    account_id = accounts.data[0]["id"]

    roles = (
        supabase()
        .table("roles")
        .select("id, name")
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not roles.data:
        return TEMPLATES.TemplateResponse(
            request,
            "_pin_list.html",
            {"pins": [], "no_roles": True},
        )
    role_names = {r["id"]: r["name"] for r in roles.data}

    pin_rows = (
        supabase()
        .table("pin_challenges")
        .select("id, pin, claim_what, expires_at, created_at, role_id")
        .in_("role_id", list(role_names.keys()))
        .is_("used_at", "null")
        .gt("expires_at", "now()")
        .order("created_at", desc=True)
        .execute()
    )
    pins = [
        {**p, "role_name": role_names.get(p["role_id"], "?")}
        for p in pin_rows.data
    ]
    return TEMPLATES.TemplateResponse(request, "_pin_list.html", {"pins": pins})


def _account_id_for_user(user: dict) -> str | None:
    """Return the openbraid account_id for the signed-in Supabase user, or None.

    Looks up `accounts` by email — same logic as pin_list/. Returns
    None when no openbraid account row exists for the email.
    """
    email = user.get("email")
    if not email:
        return None
    result = (
        supabase()
        .table("accounts")
        .select("id")
        .eq("email", email)
        .is_("deleted_at", "null")
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]["id"]


async def roles_page(request: Request):
    """Render the roles management page: list of roles + add-role form.

    Per role we show: name, created_at, last successful auth (max
    auth_sessions.created_at), and the most recent pin_challenge with
    a status badge (active / used / expired). N+1 query pattern for
    last-access and last-PIN per role — fine at v0 cardinality.
    """
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    account_id = _account_id_for_user(user)
    if not account_id:
        return TEMPLATES.TemplateResponse(
            request,
            "roles.html",
            {
                "user": user,
                "roles": [],
                "no_account": True,
                "email": user.get("email"),
                "error": request.query_params.get("error"),
                "notice": request.query_params.get("notice"),
            },
        )

    roles = (
        supabase()
        .table("roles")
        .select("id, name, roledef_url, created_at, org_id")
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )

    # Resolve incumbents bindings for this account so we know which
    # roles are artifact-bound (Phase F F0). Each row: claimed_role_id
    # → org_artifact_id; we map further to org_slug for display.
    incumbents_rows = (
        supabase()
        .table("incumbents")
        .select("claimed_role_id, org_artifact_id")
        .eq("account_id", account_id)
        .is_("ended_at", "null")
        .execute()
    )
    artifact_slug_by_role_id: dict[str, str] = {}
    if incumbents_rows.data:
        artifact_ids = list({r["org_artifact_id"] for r in incumbents_rows.data})
        artifact_lookup = (
            supabase()
            .table("org_artifacts")
            .select("id, org_slug")
            .in_("id", artifact_ids)
            .execute()
        )
        slug_by_artifact = {a["id"]: a["org_slug"] for a in artifact_lookup.data or []}
        for row in incumbents_rows.data:
            slug = slug_by_artifact.get(row["org_artifact_id"])
            if slug:
                artifact_slug_by_role_id[row["claimed_role_id"]] = slug

    # Phase F F0 + migration 0010: role.name is now the full canonical
    # URL path (`<handle>/<org_slug>/<position_id>`). Surface the short
    # position id prominently and keep the full canonical name as a
    # secondary line so adopters can copy it for memos / cross-refs.
    handle = (user.get("email") or "").split("@", 1)[0] or "unknown"
    mcp_base = _mcp_origin()

    enriched = []
    for role in roles.data:
        is_artifact_bound = role["id"] in artifact_slug_by_role_id
        # role.name is "<handle>/<org_slug>/<position_id>" post-0010;
        # split into parts so we can render org + position cleanly.
        name_parts = role["name"].split("/", 2)
        if len(name_parts) == 3:
            _name_handle, org_slug, position_id = name_parts
        else:
            # Defensive: a row that escaped migration 0010 (shouldn't
            # happen, but keep the page renderable).
            org_slug, position_id = "personal", role["name"]
        # Canonical URL is just `<mcp_base>/<role.name>` since role.name
        # already encodes the full path.
        canonical_url = f"{mcp_base}/{role['name']}"
        recommended_prompt = (
            f"Please claim role: {canonical_url} via the openbraid mcp "
            f"connector, and review the existing notes and memos. "
            f"I'll deliver the PIN."
        )
        enriched.append(
            {
                **role,
                "org_name": org_slug,
                "position_id": position_id,
                "is_artifact_bound": is_artifact_bound,
                "canonical_url": canonical_url,
                "recommended_prompt": recommended_prompt,
            }
        )

    # Vacant artifact positions: positions declared in any of the
    # account's uploaded opencatalogs that DON'T have a live
    # incumbents binding. Without this section, Director can't see
    # a position's canonical URL until after first-claim has minted
    # a role row — chicken-and-egg for the URL-as-instruction flow.
    bound_artifact_position_keys = {
        (row["org_artifact_id"], row["position_id"])
        for row in (
            supabase()
            .table("incumbents")
            .select("org_artifact_id, position_id")
            .eq("account_id", account_id)
            .is_("ended_at", "null")
            .execute()
        ).data or []
    }
    account_artifacts = artifacts_for_account(account_id)
    vacant_positions = []
    for art in account_artifacts:
        content = art.get("content") or {}
        items = content.get("items") or []
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("type") != "orgdef:Position":
                continue
            position_id = it.get("id")
            if not isinstance(position_id, str) or not position_id:
                continue
            if (art["id"], position_id) in bound_artifact_position_keys:
                continue
            canonical_url = f"{mcp_base}/{handle}/{art['org_slug']}/{position_id}"
            vacant_positions.append(
                {
                    "org_slug": art["org_slug"],
                    "position_id": position_id,
                    "position_name": it.get("name") or position_id,
                    "status": it.get("status"),
                    "description": (it.get("description") or "")[:200],
                    "role_definition_id": (
                        (it.get("role_definition") or {}).get("id")
                        if isinstance(it.get("role_definition"), dict)
                        else None
                    ),
                    "canonical_url": canonical_url,
                    "recommended_prompt": (
                        f"Please claim role: {canonical_url} via the openbraid "
                        f"mcp connector, and review the existing notes and memos. "
                        f"I'll deliver the PIN."
                    ),
                }
            )

    # Cross-links to per-org chart views (F-chart). Artifact-backed
    # orgs render from items[] directly; legacy orgs render via a
    # synthesized opencatalog (flat list of nodes, no relationships).
    artifact_slugs = {a["org_slug"] for a in account_artifacts}
    chart_links = [
        {
            "slug": a["org_slug"],
            "name": (a.get("content") or {}).get("name") or a["org_slug"],
            "is_legacy": False,
        }
        for a in account_artifacts
    ]
    for o in orgs_for_account(account_id):
        if o["name"] in artifact_slugs:
            continue
        chart_links.append({
            "slug": o["name"],
            "name": o["name"],
            "is_legacy": True,
        })

    return TEMPLATES.TemplateResponse(
        request,
        "roles.html",
        {
            "user": user,
            "roles": enriched,
            "vacant_positions": vacant_positions,
            "chart_links": chart_links,
            "account_handle": handle,
            "no_account": False,
            "error": request.query_params.get("error"),
            "notice": request.query_params.get("notice"),
        },
    )


async def roles_create(request: Request):
    """Insert a new `roles` row for the signed-in user's account.

    Form-driven, redirects back to /panel/roles. Validation: name
    must be non-empty after stripping; uniqueness is enforced by
    the DB's UNIQUE (account_id, name) constraint — caught and
    surfaced as a user-friendly error.
    """
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    account_id = _account_id_for_user(user)
    if not account_id:
        return RedirectResponse(
            "/panel/roles?error=No+openbraid+account+found+for+your+email",
            status_code=303,
        )

    form = await request.form()
    name = (form.get("name") or "").strip()
    roledef_url = (form.get("roledef_url") or "").strip() or None
    if not name:
        return RedirectResponse(
            "/panel/roles?error=Role+name+is+required", status_code=303
        )
    if len(name) > 64:
        return RedirectResponse(
            "/panel/roles?error=Role+name+must+be+64+characters+or+less",
            status_code=303,
        )

    # Phase C: every role is parented under an org. v0 default is the
    # account's 'personal' org (auto-migrated for existing accounts;
    # ensured-on-the-fly for fresh ones).
    org_id = ensure_personal_org(account_id)

    # Phase F migration 0010: role names are canonical-URL-shaped
    # `<handle>/<org>/<position>`. Construct the canonical name from
    # the panel input (which is the bare position id) + the account's
    # handle + the personal org name.
    account_email = (
        supabase()
        .table("accounts")
        .select("email")
        .eq("id", account_id)
        .execute()
        .data[0]["email"]
    )
    handle = account_email.split("@", 1)[0]
    canonical_name = f"{handle}/personal/{name}"

    try:
        supabase().table("roles").insert(
            {
                "account_id": account_id,
                "org_id": org_id,
                "name": canonical_name,
                "roledef_url": roledef_url,
            }
        ).execute()
    except Exception as e:  # noqa: BLE001 — present as a form error
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            friendly = f"A role named '{name}' already exists in your personal org"
        else:
            friendly = f"Could not create role: {msg[:200]}"
        # Use + for spaces in query params; the browser decodes them.
        from urllib.parse import quote_plus

        return RedirectResponse(
            f"/panel/roles?error={quote_plus(friendly)}", status_code=303
        )

    from urllib.parse import quote_plus

    return RedirectResponse(
        f"/panel/roles?notice={quote_plus(f'Created role: {name}')}",
        status_code=303,
    )


async def _resolve_chart_context(request: Request):
    """Helper: parse `{account}` + `{org}` path params, auth-check, and
    return a normalized chart context.

    Used by all three F-chart routes. Auth-scoping: the {account}
    segment MUST match the signed-in user's handle (email-localpart).
    Cross-account viewing is out of scope for v1.

    Returns either:
      ((user, account, account_handle, org_slug, content, live, kind,
        artifact_id_or_None), None)
    or:
      (None, RedirectResponse)

    `kind` is "artifact" when an org_artifacts row exists for the slug,
    or "legacy" when the chart was synthesized from a legacy `orgs`
    row + its roles.
    """
    user = await _current_user(request)
    if not user:
        return None, RedirectResponse("/", status_code=303)

    account_handle = request.path_params["account"]
    org_slug = request.path_params["org"]

    user_handle = (user.get("email") or "").split("@", 1)[0]
    if user_handle != account_handle:
        return None, RedirectResponse("/panel/roles", status_code=303)

    account = account_by_handle(account_handle)
    if not account:
        return None, RedirectResponse(
            "/panel/roles?error=No+openbraid+account+found", status_code=303
        )

    sb = supabase()
    artifact = artifact_by_account_and_slug(account["id"], org_slug)
    if artifact:
        content = artifact["content"]
        live = build_live_map_for_artifact(artifact["id"], sb)
        return (
            (user, account, account_handle, org_slug, content, live,
             "artifact", artifact["id"]),
            None,
        )

    # Legacy fallback: synthesize an opencatalog-shaped chart from the
    # legacy `orgs` + `roles` tables.
    legacy = org_by_name(account["id"], org_slug)
    if not legacy:
        return None, RedirectResponse(
            f"/panel/roles?error=No+org+for+slug+{org_slug}",
            status_code=303,
        )
    roles_rows = (
        sb.table("roles")
        .select("id, name, roledef_url, created_at, org_id")
        .eq("org_id", legacy["id"])
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )
    roles_list = roles_rows.data or []
    content = synthesize_legacy_org_content(legacy, roles_list, account_handle)
    live = build_live_map_for_legacy_org(legacy, roles_list, account_handle, sb)
    return (
        (user, account, account_handle, org_slug, content, live,
         "legacy", None),
        None,
    )


async def chart_page(request: Request):
    """Phase F F-chart: render the org-chart page for an artifact.

    URL: GET /panel/orgs/{account}/{org}/chart

    Page structure: a Mermaid container plus a side-panel container.
    The Mermaid container polls /chart/live every 2 seconds so claim /
    revoke state stays fresh; clicking any node triggers a JS callback
    (`openPositionPanel`) that fetches the side-panel fragment.
    """
    resolved, err = await _resolve_chart_context(request)
    if err:
        return err
    user, _account, account_handle, org_slug, content, live, kind, _ = resolved

    mermaid_text = build_mermaid_for_artifact(content, live=live)

    return TEMPLATES.TemplateResponse(
        request,
        "chart.html",
        {
            "user": user,
            "account_handle": account_handle,
            "org_slug": org_slug,
            "org_name": content.get("name") or org_slug,
            "org_mission": content.get("mission"),
            "mermaid_text": mermaid_text,
            "is_legacy": kind == "legacy",
            "position_count": sum(
                1 for it in (content.get("items") or [])
                if isinstance(it, dict) and it.get("type") == "orgdef:Position"
            ),
        },
    )


async def chart_live(request: Request):
    """HTMX fragment: re-rendered Mermaid text with current live overlay.

    URL: GET /panel/orgs/{account}/{org}/chart/live

    Returns just the `<pre class="mermaid">…</pre>` block + a tiny
    inline script that re-runs `mermaid.run()` on the new content.
    Polled every 2s by the page.
    """
    resolved, err = await _resolve_chart_context(request)
    if err:
        return err
    _user, _account, _handle, _slug, content, live, _kind, _ = resolved

    mermaid_text = build_mermaid_for_artifact(content, live=live)

    return TEMPLATES.TemplateResponse(
        request,
        "_chart_live.html",
        {"mermaid_text": mermaid_text},
    )


async def chart_position_panel(request: Request):
    """HTMX fragment: side panel for a clicked node.

    URL: GET /panel/orgs/{account}/{org}/positions/{position_id}

    Renders different content depending on whether the position has a
    live incumbents binding:
      - vacant → canonical URL + copy-claim-prompt button
      - claimed → role info (synthetic role.name, claimed_at, active
        sessions count) + revoke-session affordance per session
    """
    resolved, err = await _resolve_chart_context(request)
    if err:
        return err
    _user, _account, account_handle, org_slug, content, _live, kind, artifact_id = resolved

    position_id = request.path_params["position_id"]
    position_item = find_position_in_artifact(content, position_id)
    if not position_item:
        return Response(status_code=404)

    job_item = None
    jd = position_item.get("job_definition")
    if isinstance(jd, dict) and isinstance(jd.get("id"), str):
        job_item = find_job_in_artifact(content, jd["id"])

    sb = supabase()
    incumbent_row_data = None
    role_name = None
    sessions = []

    if kind == "artifact":
        incumbent_row = (
            sb.table("incumbents")
            .select("id, claimed_role_id, created_at")
            .eq("org_artifact_id", artifact_id)
            .eq("position_id", position_id)
            .is_("ended_at", "null")
            .execute()
        )
        if incumbent_row.data:
            incumbent_row_data = incumbent_row.data[0]
            role_id = incumbent_row_data["claimed_role_id"]
            role_lookup = (
                sb.table("roles")
                .select("name")
                .eq("id", role_id)
                .execute()
            )
            if role_lookup.data:
                role_name = role_lookup.data[0]["name"]
            session_rows = (
                sb.table("auth_sessions")
                .select("id, client_session_id, created_at, expires_at")
                .eq("role_id", role_id)
                .is_("revoked_at", "null")
                .gt("expires_at", "now()")
                .order("created_at", desc=True)
                .execute()
            )
            sessions = session_rows.data or []
    else:
        # Legacy path: the role itself IS the position. Look up by
        # canonical role name and surface its sessions; synthesize an
        # incumbent-shaped dict so the template renders the "claimed"
        # branch instead of asking the user to PIN-claim a position
        # that's already a real role.
        canonical_name = f"{account_handle}/{org_slug}/{position_id}"
        role_lookup = (
            sb.table("roles")
            .select("id, name, created_at")
            .eq("name", canonical_name)
            .is_("deleted_at", "null")
            .execute()
        )
        if role_lookup.data:
            role_row = role_lookup.data[0]
            role_name = role_row["name"]
            incumbent_row_data = {"created_at": role_row["created_at"]}
            session_rows = (
                sb.table("auth_sessions")
                .select("id, client_session_id, created_at, expires_at")
                .eq("role_id", role_row["id"])
                .is_("revoked_at", "null")
                .gt("expires_at", "now()")
                .order("created_at", desc=True)
                .execute()
            )
            sessions = session_rows.data or []

    mcp_base = _mcp_origin()
    canonical_url = f"{mcp_base}/{account_handle}/{org_slug}/{position_id}"
    return TEMPLATES.TemplateResponse(
        request,
        "_position_panel.html",
        {
            "position": position_item,
            "job": job_item,
            "canonical_url": canonical_url,
            "recommended_prompt": (
                f"Please claim role: {canonical_url} via the openbraid mcp "
                f"connector, and review the existing notes and memos. "
                f"I'll deliver the PIN."
            ),
            "incumbent": incumbent_row_data,
            "role_name": role_name,
            "sessions": sessions,
            "is_legacy": kind == "legacy",
        },
    )


async def role_live(request: Request):
    """HTMX fragment: live state for one role.

    Phase F F4 consolidated view: each role card on /panel/roles polls
    this endpoint every 2 seconds to refresh:
      - active auth_sessions (not revoked, not expired) with revoke
        affordance per row
      - pending pin_challenges (not used, not expired) with the PIN
        displayed for the user to read back to the requesting AI

    Auth-scoped to the signed-in user's account: a session_id in the
    URL that doesn't belong to one of this user's roles 404s.
    """
    user = await _current_user(request)
    if not user:
        return Response(status_code=401)

    account_id = _account_id_for_user(user)
    if not account_id:
        return Response(status_code=403)

    role_id = request.path_params["role_id"]
    role_check = (
        supabase()
        .table("roles")
        .select("id")
        .eq("id", role_id)
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not role_check.data:
        return Response(status_code=404)

    sessions = (
        supabase()
        .table("auth_sessions")
        .select("id, client_session_id, created_at, expires_at")
        .eq("role_id", role_id)
        .is_("revoked_at", "null")
        .gt("expires_at", "now()")
        .order("created_at", desc=True)
        .execute()
    )
    pins = (
        supabase()
        .table("pin_challenges")
        .select("id, pin, claim_what, created_at, expires_at")
        .eq("role_id", role_id)
        .is_("used_at", "null")
        .gt("expires_at", "now()")
        .order("created_at", desc=True)
        .execute()
    )

    return TEMPLATES.TemplateResponse(
        request,
        "_role_live.html",
        {
            "role_id": role_id,
            "sessions": sessions.data or [],
            "pins": pins.data or [],
        },
    )


async def session_revoke(request: Request):
    """POST /panel/sessions/{session_id}/revoke — set revoked_at = now().

    Auth-scoped: the session must belong to a role owned by the
    signed-in user's account. Otherwise 404 (no info leak about whether
    the session exists for someone else).
    """
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    account_id = _account_id_for_user(user)
    if not account_id:
        return RedirectResponse("/panel/roles", status_code=303)

    session_id = request.path_params["session_id"]
    session_check = (
        supabase()
        .table("auth_sessions")
        .select("id, role_id, roles!inner(account_id)")
        .eq("id", session_id)
        .is_("revoked_at", "null")
        .execute()
    )
    if not session_check.data:
        # Either session doesn't exist, is already revoked, or belongs
        # to another account. Don't leak which.
        return Response(status_code=204)
    row = session_check.data[0]
    if row.get("roles", {}).get("account_id") != account_id:
        return Response(status_code=204)

    supabase().table("auth_sessions").update({"revoked_at": "now()"}).eq("id", session_id).execute()

    # HTMX caller swaps in the updated fragment; return empty 204 and
    # let the polling tick re-render. (Returning the fragment directly
    # would require knowing which role to render.)
    return Response(status_code=204)


async def role_delete(request: Request):
    """Soft-delete a legacy role (Phase F F3).

    Sets `roles.deleted_at = now()` for the role, scoped to the
    signed-in account. Idempotent: a re-attempt against an already-
    deleted row is a no-op redirect.

    Artifact-bound roles (those with a live incumbents binding) are
    NOT deletable from this affordance — the artifact's position is
    the canonical seat; deleting the synthetic role row would orphan
    the binding. Future affordance ("vacate") would end the binding
    cleanly; for now those return an error redirect.
    """
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    account_id = _account_id_for_user(user)
    if not account_id:
        return RedirectResponse("/panel/roles", status_code=303)

    role_id = request.path_params["role_id"]

    role_check = (
        supabase()
        .table("roles")
        .select("id, name")
        .eq("id", role_id)
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not role_check.data:
        return RedirectResponse("/panel/roles", status_code=303)
    role_name = role_check.data[0]["name"]

    # Reject if role has a live incumbents binding — those are
    # artifact-bound and should be ended via the (future) vacate
    # affordance, not deleted.
    incumbent_check = (
        supabase()
        .table("incumbents")
        .select("id")
        .eq("claimed_role_id", role_id)
        .is_("ended_at", "null")
        .execute()
    )
    from urllib.parse import quote_plus

    if incumbent_check.data:
        return RedirectResponse(
            f"/panel/roles?error="
            f"{quote_plus(f'{role_name} is artifact-bound; soft-delete is for legacy roles only')}",
            status_code=303,
        )

    supabase().table("roles").update({"deleted_at": "now()"}).eq("id", role_id).execute()
    return RedirectResponse(
        f"/panel/roles?notice={quote_plus(f'Deleted role: {role_name}')}",
        status_code=303,
    )


async def role_notes_page(request: Request):
    """Read-only notes browser for a specific role.

    URL: /panel/roles/{role_id}/notes — mirrors the memodef v0.3
    `notes/<role-id>/` folder convention. Lists all kind='note' memos
    filed under the given role, ordered by most-recent first.

    Auth-checks that the role belongs to the signed-in user's account
    before exposing the notes (defense against URL-tampering).
    """
    user = await _current_user(request)
    if not user:
        return RedirectResponse("/", status_code=303)

    account_id = _account_id_for_user(user)
    if not account_id:
        return RedirectResponse("/panel/roles", status_code=303)

    role_id = request.path_params["role_id"]

    role_check = (
        supabase()
        .table("roles")
        .select("id, name")
        .eq("id", role_id)
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not role_check.data:
        # Either the role doesn't exist, was deleted, or belongs to
        # another account. Don't distinguish — just send the user back
        # to their roles list.
        from urllib.parse import quote_plus

        return RedirectResponse(
            f"/panel/roles?error={quote_plus('Role not found')}",
            status_code=303,
        )

    role_name = role_check.data[0]["name"]

    notes = (
        supabase()
        .table("memos")
        .select(
            "id, from_position, subject, body, body_ref, sent_at, "
            "in_reply_to, thread_id"
        )
        .eq("role_id", role_id)
        .eq("kind", "note")
        .is_("deleted_at", "null")
        .order("sent_at", desc=True)
        .limit(200)
        .execute()
    )

    return TEMPLATES.TemplateResponse(
        request,
        "notes.html",
        {
            "user": user,
            "role_id": role_id,
            "role_name": role_name,
            "notes": notes.data,
        },
    )


panel_routes = [
    Route("/", root),
    Route("/auth/login", login),
    Route("/auth/callback", callback),
    Route("/auth/logout", logout, methods=["POST"]),
    Route("/auth/email/login", email_login, methods=["POST"]),
    Route("/auth/email/signup", email_signup, methods=["POST"]),
    Route("/panel", panel_redirect),
    Route("/panel/pins", pin_list),
    Route("/panel/roles", roles_page),
    Route("/panel/roles/new", roles_create, methods=["POST"]),
    Route("/panel/roles/{role_id}/delete", role_delete, methods=["POST"]),
    Route("/panel/roles/{role_id}/live", role_live),
    Route("/panel/roles/{role_id}/notes", role_notes_page),
    Route("/panel/sessions/{session_id}/revoke", session_revoke, methods=["POST"]),
    Route("/panel/orgs/{account}/{org}/chart", chart_page),
    Route("/panel/orgs/{account}/{org}/chart/live", chart_live),
    Route(
        "/panel/orgs/{account}/{org}/positions/{position_id}",
        chart_position_panel,
    ),
]
