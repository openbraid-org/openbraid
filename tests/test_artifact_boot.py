"""Tests for artifact-backed boot URL handlers (Phase E opencatalog).

Verifies the artifact-first read path with mocked Supabase. The
production smoke (upload + live curl) is the end-to-end check; these
tests cover routing decisions and payload-shape construction against
the orgdef SCHEMA v1.0.0 (.opencatalog) substrate.

Three integration points:
  - account_orgs_endpoint unions artifact + legacy
  - position_boot_endpoint reads from artifact, embeds Job items inline
  - account_seg2_endpoint resolves artifact slug to positions list
"""

from __future__ import annotations

from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import JSONResponse

import server.boot_url as boot_url

JOB_ITEM = {
    "type": "roledef:Job",
    "id": "implementer",
    "name": "Implementer for Thingalog",
    "version": "1.0.0",
    "charter": "test charter",
}

ARTIFACT_CONTENT = {
    "catdef": "1.4",
    "orgdef": "1.0.0",
    "type": "orgdef:Organization",
    "id": "thingalog",
    "name": "Thingalog",
    "version": "2.0.0",
    "mission": "test mission",
    "vision": "test vision",
    "scope": "test scope",
    "governance_model": "test governance",
    "items": [
        {
            "type": "orgdef:Position",
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
            "type": "orgdef:Position",
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
    "version": "2.0.0",
    "created_at": "2026-05-10T00:00:00Z",
    "updated_at": "2026-05-10T00:00:00Z",
}

FAKE_ACCOUNT = {
    "id": "acct-uuid",
    "email": "scott@confusedgorilla.com",
    "auth_user_id": "x",
    "created_at": "2026-05-08T00:00:00Z",
}


def _make_request(path_params: dict, scheme="https", netloc="mcp.openbraid.app") -> Request:
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
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW):
        request = _make_request(
            {"account": "scott", "org": "thingalog", "position": "implementer"}
        )
        response = await boot_url.position_boot_endpoint(request)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    import json
    body = json.loads(response.body)

    assert body["_backed_by"] == "artifact"
    assert body["position"]["id"] == "implementer"
    assert body["position"]["name"] == "Implementer"
    assert body["org_summary"]["slug"] == "thingalog"
    assert body["org_summary"]["name"] == "Thingalog"
    assert body["org_summary"]["mission"] == "test mission"
    assert body["role_definition"] is not None
    assert body["job_definition"] is None  # no job_definition on this position
    assert body["incumbent"]["claimable"] is False
    assert "diagnostic" in body["incumbent"]
    assert body["claim_instruction"] is None


async def test_position_boot_endpoint_embeds_job_when_sibling_item_exists():
    """Position has job_definition.id pointing at a sibling Job item
    in the same opencatalog → boot payload embeds it inline."""
    content_with_job = {
        **ARTIFACT_CONTENT,
        "items": [
            {
                "type": "orgdef:Position",
                "id": "implementer",
                "name": "Implementer",
                "status": "staffed",
                "job_definition": {"id": "implementer", "version": "1.0.0"},
            },
            JOB_ITEM,
        ],
    }
    artifact_with_job = {**ARTIFACT_ROW, "content": content_with_job}
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=artifact_with_job):
        request = _make_request(
            {"account": "scott", "org": "thingalog", "position": "implementer"}
        )
        response = await boot_url.position_boot_endpoint(request)

    import json
    body = json.loads(response.body)
    assert body["job_definition"]["id"] == "implementer"
    assert body["job_definition"]["content"] == JOB_ITEM
    assert "diagnostic" not in body["job_definition"]


async def test_position_boot_endpoint_diagnostic_when_job_referenced_but_no_sibling():
    """Position references job_definition.id but no sibling Job exists
    and no external URL declared → diagnostic in payload."""
    content_with_dangling = {
        **ARTIFACT_CONTENT,
        "items": [
            {
                "type": "orgdef:Position",
                "id": "implementer",
                "name": "Implementer",
                "job_definition": {"id": "implementer", "version": "1.0.0"},
            },
        ],
    }
    artifact_dangling = {**ARTIFACT_ROW, "content": content_with_dangling}
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=artifact_dangling):
        request = _make_request(
            {"account": "scott", "org": "thingalog", "position": "implementer"}
        )
        response = await boot_url.position_boot_endpoint(request)

    import json
    body = json.loads(response.body)
    assert body["job_definition"]["id"] == "implementer"
    assert "content" not in body["job_definition"]
    assert "no sibling" in body["job_definition"]["diagnostic"]


async def test_position_boot_endpoint_external_url_diagnostic():
    """Position references a job_definition.url (external) → diagnostic
    notes deferred external resolution."""
    content_external = {
        **ARTIFACT_CONTENT,
        "items": [
            {
                "type": "orgdef:Position",
                "id": "implementer",
                "name": "Implementer",
                "job_definition": {
                    "id": "external-job",
                    "url": "https://other.example/jobs/external-job",
                },
            },
        ],
    }
    artifact_external = {**ARTIFACT_ROW, "content": content_external}
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=artifact_external):
        request = _make_request(
            {"account": "scott", "org": "thingalog", "position": "implementer"}
        )
        response = await boot_url.position_boot_endpoint(request)

    import json
    body = json.loads(response.body)
    assert body["job_definition"]["url"].startswith("https://other.example")
    assert "external URL" in body["job_definition"]["diagnostic"]


async def test_position_boot_endpoint_falls_back_to_legacy_when_no_artifact():
    fake_org = {
        "id": "org-uuid-personal", "name": "personal",
        "mission": None, "vision": None, "scope": None,
        "governance_model": None, "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    fake_position = {
        "id": "role-uuid-strategist", "name": "personal-strategist",
        "roledef_url": None, "created_at": "2026-05-09T00:00:00Z",
        "org_id": "org-uuid-personal", "account_id": "acct-uuid",
    }
    sentinel_legacy_payload = {"_backed_by": "legacy", "marker": True}
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
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
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=ARTIFACT_ROW):
        request = _make_request(
            {"account": "scott", "org": "thingalog", "position": "does-not-exist"}
        )
        response = await boot_url.position_boot_endpoint(request)

    assert response.status_code == 404
    import json
    assert json.loads(response.body) == {"error": "position not found in artifact"}


async def test_account_orgs_endpoint_unions_artifact_and_legacy():
    legacy_org = {
        "id": "org-uuid-personal", "name": "personal",
        "mission": None, "vision": None, "scope": None,
        "governance_model": None, "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
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
    personal_artifact = {**ARTIFACT_ROW, "org_slug": "personal"}
    legacy_personal = {
        "id": "org-uuid-personal", "name": "personal",
        "mission": None, "vision": None, "scope": None,
        "governance_model": None, "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifacts_for_account", return_value=[personal_artifact]), \
         patch.object(boot_url, "orgs_for_account", return_value=[legacy_personal]):
        request = _make_request({"account": "scott"})
        response = await boot_url.account_orgs_endpoint(request)

    import json
    body = json.loads(response.body)
    assert len(body["orgs"]) == 1
    assert body["orgs"][0]["_backed_by"] == "artifact"


async def test_account_seg2_endpoint_resolves_artifact_slug_to_positions_list():
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
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


async def test_account_seg2_endpoint_filters_non_position_items():
    """An opencatalog with mixed items[] (Positions + Jobs + Roles) must
    only return Position items in the positions list response."""
    mixed_content = {
        **ARTIFACT_CONTENT,
        "items": ARTIFACT_CONTENT["items"] + [
            JOB_ITEM,
            {"type": "roledef:Role", "id": "thingalog-director", "name": "Director"},
        ],
    }
    mixed_artifact = {**ARTIFACT_ROW, "content": mixed_content}
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
         patch.object(boot_url, "artifact_by_account_and_slug", return_value=mixed_artifact):
        request = _make_request({"account": "scott", "seg2": "thingalog"})
        response = await boot_url.account_seg2_endpoint(request)

    import json
    body = json.loads(response.body)
    assert len(body["positions"]) == 2  # Job and Role items excluded


async def test_account_seg2_endpoint_falls_back_to_legacy_sugar_when_no_artifacts():
    fake_org = {
        "id": "org-uuid-personal", "name": "personal",
        "mission": None, "vision": None, "scope": None,
        "governance_model": None, "org_location": None,
        "created_at": "2026-05-08T00:00:00Z",
    }
    fake_position = {
        "id": "role-uuid-strategist", "name": "personal-strategist",
        "roledef_url": None, "created_at": "2026-05-09T00:00:00Z",
        "org_id": "org-uuid-personal", "account_id": "acct-uuid",
    }
    sentinel = {"_backed_by": "legacy", "marker": True}
    with patch.object(boot_url, "account_by_handle", return_value=FAKE_ACCOUNT), \
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
