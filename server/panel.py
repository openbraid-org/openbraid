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
from server.db import ensure_account, supabase

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
        .select("id, name, roledef_url, created_at")
        .eq("account_id", account_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )

    enriched = []
    for role in roles.data:
        last_session = (
            supabase()
            .table("auth_sessions")
            .select("created_at")
            .eq("role_id", role["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        last_pin = (
            supabase()
            .table("pin_challenges")
            .select("pin, created_at, expires_at, used_at, claim_what")
            .eq("role_id", role["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        enriched.append(
            {
                **role,
                "last_access": last_session.data[0]["created_at"]
                if last_session.data
                else None,
                "last_pin": last_pin.data[0] if last_pin.data else None,
            }
        )

    return TEMPLATES.TemplateResponse(
        request,
        "roles.html",
        {
            "user": user,
            "roles": enriched,
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

    try:
        supabase().table("roles").insert(
            {
                "account_id": account_id,
                "name": name,
                "roledef_url": roledef_url,
            }
        ).execute()
    except Exception as e:  # noqa: BLE001 — present as a form error
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            friendly = f"A role named '{name}' already exists in your account"
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
    Route("/panel", panel),
    Route("/panel/pins", pin_list),
    Route("/panel/roles", roles_page),
    Route("/panel/roles/new", roles_create, methods=["POST"]),
    Route("/panel/roles/{role_id}/notes", role_notes_page),
]
