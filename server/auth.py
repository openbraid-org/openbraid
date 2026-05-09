"""Supabase OAuth (PKCE) flow for the panel.

The MCP server already holds the Supabase service-role key; the panel
needs the *anon* key to drive the user-facing OAuth ceremony. Token
validation goes through Supabase's `/auth/v1/user` endpoint — slow but
simple for v0; switch to local JWT verification when load justifies it.

Token persistence is via an HttpOnly cookie set on the panel origin.
v0 access tokens have a 1-hour TTL; refresh tokens are intentionally
not handled — re-auth is one click.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

import httpx

SESSION_COOKIE = "ob_session"
PKCE_VERIFIER_COOKIE = "ob_pkce"
OAUTH_STATE_COOKIE = "ob_state"


def supabase_url() -> str:
    return os.environ["SUPABASE_URL"]


def supabase_anon_key() -> str:
    return os.environ["SUPABASE_ANON_KEY"]


def panel_origin() -> str:
    """Public origin for the panel (e.g. https://web-production-ca02d.up.railway.app).

    Required so the Supabase OAuth `redirect_to` and the cookies we set
    use the same origin. Set via env so we don't hard-code a Railway URL.
    """
    return os.environ["PANEL_ORIGIN"]


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for the PKCE flow.

    code_verifier is opaque random; code_challenge is SHA-256(verifier)
    base64url-encoded without padding (per RFC 7636).
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize_url(code_challenge: str) -> str:
    """Build the Supabase OAuth-authorize URL for Google + PKCE."""
    redirect_to = f"{panel_origin()}/auth/callback"
    return (
        f"{supabase_url()}/auth/v1/authorize"
        f"?provider=google"
        f"&redirect_to={redirect_to}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )


async def exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange an authorization code for a session (access + refresh tokens).

    Hits Supabase's PKCE token endpoint. Raises httpx.HTTPStatusError on
    non-2xx — caller handles user-facing error.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{supabase_url()}/auth/v1/token?grant_type=pkce",
            headers={
                "apikey": supabase_anon_key(),
                "Content-Type": "application/json",
            },
            json={"auth_code": code, "code_verifier": code_verifier},
        )
        r.raise_for_status()
        return r.json()


async def get_user_from_token(access_token: str) -> dict | None:
    """Validate an access token and return the user dict, or None if invalid.

    Uses Supabase's /auth/v1/user — one HTTP roundtrip per request. Fine
    for v0 traffic; replace with local JWT-signature verification when
    the panel sees more than a few requests per second.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{supabase_url()}/auth/v1/user",
            headers={
                "apikey": supabase_anon_key(),
                "Authorization": f"Bearer {access_token}",
            },
        )
        if r.status_code != 200:
            return None
        return r.json()


def _surface_supabase_error(response: httpx.Response, default: str) -> str:
    """Pull a human message out of a Supabase Auth error response."""
    try:
        body = response.json()
    except ValueError:
        return default
    return (
        body.get("error_description")
        or body.get("msg")
        or body.get("error")
        or default
    )


async def sign_in_with_password(email: str, password: str) -> dict:
    """Sign in via email + password. Returns the Supabase token response.

    Raises ValueError with a user-presentable message on auth failure.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{supabase_url()}/auth/v1/token?grant_type=password",
            headers={
                "apikey": supabase_anon_key(),
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
        )
        if r.status_code != 200:
            raise ValueError(
                _surface_supabase_error(r, "Invalid email or password.")
            )
        return r.json()


async def sign_up_with_password(email: str, password: str) -> dict:
    """Create a new Supabase Auth user via email + password.

    If the project has email-confirmations enabled, the response will
    contain a `user` but no `access_token` — the user must click the
    confirmation link before signing in. If confirmations are disabled,
    tokens are returned and the caller can set the session cookie
    immediately.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{supabase_url()}/auth/v1/signup",
            headers={
                "apikey": supabase_anon_key(),
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
        )
        if r.status_code not in (200, 201):
            raise ValueError(
                _surface_supabase_error(r, "Sign-up failed.")
            )
        return r.json()
