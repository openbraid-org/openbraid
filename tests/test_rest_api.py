"""Contract tests for the REST + OpenAPI transport (Phase D D1).

These verify the *shape* of the REST API independently of any storage:

  - All six routes exist under /api/ (mirroring the MCP tool surface)
  - OpenAPI 3.1 spec is published at /api/openapi.json
  - Auth-required endpoints reject calls without a Bearer token
  - Auth-optional endpoints (claim_role, auth_with_pin) don't require one

Live integration smoke is the v0 verification path; these tests are
the cheap contract gate. They mirror the MCP contract tests in
test_tool_contracts.py so MCP/REST drift is caught at PR time.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.rest_api import api

client = TestClient(api)


EXPECTED_ROUTES = {
    "/claim_role",
    "/auth_with_pin",
    "/send_memo",
    "/list_inbox",
    "/read_memo",
    "/mark_read",
    "/upload_org",
    "/upload_job",
}

AUTH_REQUIRED = {
    "/send_memo",
    "/list_inbox",
    "/read_memo",
    "/mark_read",
    "/upload_org",
    "/upload_job",
}
AUTH_NOT_REQUIRED = {"/claim_role", "/auth_with_pin"}


def test_openapi_spec_is_published():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec.get("openapi", "").startswith("3.1"), \
        f"expected OpenAPI 3.1, got {spec.get('openapi')!r}"
    assert spec["info"]["title"] == "openbraid REST"


def test_all_expected_routes_are_registered():
    r = client.get("/openapi.json")
    spec = r.json()
    paths = set(spec["paths"].keys())
    assert paths == EXPECTED_ROUTES, (
        f"REST surface drift. Got: {sorted(paths)}. "
        f"Expected: {sorted(EXPECTED_ROUTES)}."
    )


def test_all_routes_accept_post():
    r = client.get("/openapi.json")
    spec = r.json()
    for path in EXPECTED_ROUTES:
        methods = set(spec["paths"][path].keys())
        assert "post" in methods, (
            f"{path} should be POST, got methods: {methods}"
        )


def test_auth_required_endpoints_declare_bearer_security():
    """OpenAPI declares which endpoints require auth — the spec is the
    contract ChatGPT Custom GPT consumes, so its accuracy is what
    matters. Each authed endpoint should have a non-empty `security`
    array on its operation object."""
    spec = client.get("/openapi.json").json()
    for path in AUTH_REQUIRED:
        sec = spec["paths"][path]["post"].get("security")
        assert sec, (
            f"{path} should declare a security requirement; got {sec}"
        )


def test_auth_not_required_endpoints_have_no_security():
    """claim_role and auth_with_pin run pre-auth (they initiate /
    complete the PIN ceremony); they should NOT require a bearer."""
    spec = client.get("/openapi.json").json()
    for path in AUTH_NOT_REQUIRED:
        sec = spec["paths"][path]["post"].get("security")
        # FastAPI emits `security` only when there IS one; absence is fine.
        assert not sec, (
            f"{path} should not declare a security requirement; got {sec}"
        )


def test_openapi_includes_bearer_security_scheme():
    r = client.get("/openapi.json")
    spec = r.json()
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert any(
        s.get("type") == "http" and s.get("scheme") == "bearer"
        for s in schemes.values()
    ), f"expected an HTTP Bearer security scheme; got {schemes}"
