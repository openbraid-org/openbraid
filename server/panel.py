"""Panel routes for the openbraid web UI.

v0 scope: sign in with Google, see live list of pending PIN challenges
for your account. Memo browser and role management land in follow-on
strands.

Routes:
  GET  /              — landing page (logged-in users redirect to /panel)
  GET  /auth/login    — kick off the OAuth dance
  GET  /auth/callback — handle Supabase's redirect back, set session cookie
  POST /auth/logout   — clear session cookie
  GET  /panel         — main panel UI (auth-required)
  GET  /panel/pins    — HTMX partial: live PIN list (auth-required, polled)
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
from server.db import supabase

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


panel_routes = [
    Route("/", root),
    Route("/auth/login", login),
    Route("/auth/callback", callback),
    Route("/auth/logout", logout, methods=["POST"]),
    Route("/auth/email/login", email_login, methods=["POST"]),
    Route("/auth/email/signup", email_signup, methods=["POST"]),
    Route("/panel", panel),
    Route("/panel/pins", pin_list),
]
