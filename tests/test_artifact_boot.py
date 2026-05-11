"""Tests for Phase E1-cutover artifact-backed boot URL handlers.

Verifies the artifact-first read path with mocked Supabase. The
production smoke (E0-prep upload + live curl of the boot URL) is the
end-to-end check; these tests cover the routing decisions and
payload-shape construction.

Three integration points:
  - account_orgs_endpoint unions artifact + legacy
  - position_boot_endpoint reads from artifact when present
  - account_seg2_endpoint resolves artifact slug to positions list
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.requests import Request
from starlette.responses import JSONResponse

import server.boot_url as boot_url

ARTIFACT_CONTENT = {
    "catdef": "1.4",
    "orgdef": "0.2.0",
    "type": "orgdef:Organization",
    "id": "thingalog",
    "name": "Thingalog",
    "version": "1.3.2",
    "mission": "test mission",
    "vision": "test vision",
    "scope": "test scope",
    "governance_model": "test governance",
    "positions": [
        {
            "id": "implementer",
            "name": "Implementer",
            "status": "staffed",
            "role_definition": {
                "id": "senior-project-oriented-software-engineer",
                "version": "1.0.0",
                "url": "https://roledef.org/roledefs/senior-project-oriented-software-engineer.openthing",
            },
            "description": "test impl",
        },
        {
            "id": "product-owner",
            "name": "Product Owner",
            "status": "staffed",
            "incumbent": "Scott Edsby",
        },
    ],
}

ARTIFACT_ROW = {
    "id": "artifact-uuid-thingalog",
    "account_id": "acct-uuid",
    "org_slug": "thingalog",
    "content": ARTIFACT_CONTENT,
    "version": "1.3.2",
    "created_at": "2026-05-10T00:00:00Z",
    "updated_at": "2026-05-10T00:00:00Z",
}


def _make_request(path_params: dict, scheme="https", netloc="mcp.openbraid.app") -> Request:
    """Build a minimal Starlette Request for handler testing."""
    scope = {
        "type": "http",
        "method": "GET",
        "path_params": path_params,
        "scheme": scheme,
        "server": (netloc, 443 if scheme == "https" else 80),
        "headers": [(b"host", netloc.encode())],
        "query_string": b"",
        "path": "/",
        "raw_path": b"/",
    }
    return Request(scope)


async def test_position_boot_endpoint_returns_artifact_payload_when_artifact_exists():
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW):
        request = _make_request(
            {"account": "scott", "org": "thingalog", "position": "implementer"}
        )
        response = await boot_url.position_boot_endpoint(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    import json
    body = json.loads(response.body)

    # Shape checks: artifact-backed payload has all 7 SHOULD fields
    assert body["_backed_by"] == "artifact"
    assert body["position"]["id"] == "implementer"
    assert body["position"]["name"] == "Implementer"
    assert body["org_summary"]["slug"] == "thingalog"
    assert body["org_summary"]["name"] == "Thingalog"
    assert body["org_summary"]["mission"] == "test mission"
    assert body["role_definition"] is not None  # passes through the dict
    assert body["job_definition"] is None  # not present in this position
    assert body["incumbent"]["claimable"] is False  # E1 read-only
    assert "diagnostic" in body["incumbent"]
    assert body["claim_instruction"] is None  # E1 read-only


async def test_position_boot_endpoint_falls_back_to_legacy_when_no_artifact():
    """When no artifact exists for the slug, falls back to legacy path
    via org_by_name → position_by_name → _build_boot_payload."""
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    fake_org = {
        "id": "org-uuid-personal",
        "name": "personal",
        "mission": None,
        "vision": None,
        "scope": None,
        "governance_model": None,
        "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    fake_position = {
        "id": "role-uuid-strategist",
        "name": "personal-strategist",
        "roledef_url": None,
        "created_at": "2026-05-09T00:00:00Z",
        "org_id": "org-uuid-personal",
        "account_id": "acct-uuid",
    }

    # Mock the _build_boot_payload helper so we don't have to mock all
    # of supabase for the inbox-count queries it makes.
    sentinel_legacy_payload = {"_backed_by": "legacy", "marker": True}

    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=None), \
         patch.object(boot_url, "org_by_name", return_value=fake_org), \
         patch.object(boot_url, "position_by_name", return_value=fake_position), \
         patch.object(boot_url, "_build_boot_payload", return_value=sentinel_legacy_payload):
        request = _make_request(
            {"account": "scott", "org": "personal", "position": "personal-strategist"}
        )
        response = await boot_url.position_boot_endpoint(request)

    assert response.status_code == 200
    import json
    body = json.loads(response.body)
    assert body == sentinel_legacy_payload


async def test_position_boot_endpoint_404_when_artifact_exists_but_position_missing():
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW):
        request = _make_request(
            {
                "account": "scott",
                "org": "thingalog",
                "position": "does-not-exist",
            }
        )
        response = await boot_url.position_boot_endpoint(request)

    assert response.status_code == 404
    import json
    assert json.loads(response.body) == {"error": "position not found in artifact"}


async def test_account_orgs_endpoint_unions_artifact_and_legacy():
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    legacy_org = {
        "id": "org-uuid-personal",
        "name": "personal",
        "mission": None,
        "vision": None,
        "scope": None,
        "governance_model": None,
        "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifacts_for_account", return_value=[ARTIFACT_ROW]), \
         patch.object(boot_url, "orgs_for_account", return_value=[legacy_org]):
        request = _make_request({"account": "scott"})
        response = await boot_url.account_orgs_endpoint(request)

    import json
    body = json.loads(response.body)
    assert len(body["orgs"]) == 2
    backings = {o["slug"]: o["_backed_by"] for o in body["orgs"]}
    assert backings == {"thingalog": "artifact", "personal": "legacy"}


async def test_account_orgs_endpoint_artifact_wins_when_slug_matches_legacy_name():
    """When a legacy org's name overlaps with an artifact's org_slug,
    the artifact wins (per the canonical-store principle)."""
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    # Both have name='personal' / slug='personal'
    personal_artifact = {**ARTIFACT_ROW, "org_slug": "personal"}
    legacy_personal = {
        "id": "org-uuid-personal",
        "name": "personal",
        "mission": None,
        "vision": None,
        "scope": None,
        "governance_model": None,
        "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifacts_for_account", return_value=[personal_artifact]), \
         patch.object(boot_url, "orgs_for_account", return_value=[legacy_personal]):
        request = _make_request({"account": "scott"})
        response = await boot_url.account_orgs_endpoint(request)

    import json
    body = json.loads(response.body)
    assert len(body["orgs"]) == 1
    assert body["orgs"][0]["_backed_by"] == "artifact"


async def test_account_seg2_endpoint_resolves_artifact_slug_to_positions_list():
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW):
        request = _make_request({"account": "scott", "seg2": "thingalog"})
        response = await boot_url.account_seg2_endpoint(request)

    import json
    body = json.loads(response.body)
    assert body["org"]["_backed_by"] == "artifact"
    assert body["org"]["slug"] == "thingalog"
    assert body["org"]["name"] == "Thingalog"
    assert len(body["positions"]) == 2
    position_ids = {p["id"] for p in body["positions"]}
    assert position_ids == {"implementer", "product-owner"}


async def test_account_seg2_endpoint_falls_back_to_legacy_sugar_when_no_artifacts():
    """If account has no artifacts AND exactly one legacy org, seg2 is
    a position name in that org — preserves v0 URL behavior."""
    fake_account = {
        "id": "acct-uuid",
        "email": "scott@confusedgorilla.com",
        "auth_user_id": "x",
        "created_at": "2026-05-08T00:00:00Z",
    }
    fake_org = {
        "id": "org-uuid-personal",
        "name": "personal",
        "mission": None,
        "vision": None,
        "scope": None,
        "governance_model": None,
        "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    fake_position = {
        "id": "role-uuid-strategist",
        "name": "personal-strategist",
        "roledef_url": None,
        "created_at": "2026-05-09T00:00:00Z",
        "org_id": "org-uuid-personal",
        "account_id": "acct-uuid",
    }
    sentinel = {"_backed_by": "legacy", "marker": True}
    with patch.object(boot_url, "account_by_handle", return_value=fake_account), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=None), \
         patch.object(boot_url, "artifacts_for_account", return_value=[]), \
         patch.object(boot_url, "orgs_for_account", return_value=[fake_org]), \
         patch.object(boot_url, "position_by_name", return_value=fake_position), \
         patch.object(boot_url, "_build_boot_payload", return_value=sentinel):
        request = _make_request(
            {"account": "scott", "seg2": "personal-strategist"}
        )
        response = await boot_url.account_seg2_endpoint(request)

    import json
    body = json.loads(response.body)
    assert body == sentinel
