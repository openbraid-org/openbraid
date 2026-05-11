"""Unit tests for the Mermaid chart builder (Phase F F-chart).

Covers:
- Empty / no-positions artifact returns empty string
- Single position, no relationships → one node, no edges
- reports_to renders as `from --> to` (child→parent)
- directs renders inverse (B reports to A when A directs B)
- Secondary edge types render as dashed labeled edges
- external: and org-self endpoints are filtered out
- Live state map produces correct vacant / claimed_idle / claimed_active
  class assignments
- All three production fixtures parse + render without errors

Fixture-based: reads the actual opencatalog files from sibling repos
to keep the tests honest about real adopter data shapes.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from server.chart_builder import build_mermaid_for_artifact


# --- Fixture loaders ---------------------------------------------------------


FIXTURES = {
    "openbraid-org": "s:/projects/openbraid-org/openbraid/org/openbraid-org-organization.opencatalog",
    "memodef-spec": "s:/projects/memodef-spec/memodef/org/memodef-spec-organization.opencatalog",
    "thingalog": "s:/projects/thingalog/org/thingalog-organization.opencatalog",
}


def _load(name: str) -> dict:
    path = pathlib.Path(FIXTURES[name])
    if not path.exists():
        pytest.skip(f"fixture {name} not available at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# --- Shape semantics ---------------------------------------------------------


def test_empty_artifact_returns_empty_string():
    assert build_mermaid_for_artifact({}) == ""
    assert build_mermaid_for_artifact({"items": []}) == ""


def test_artifact_without_position_items_returns_empty_string():
    artifact = {"items": [{"type": "roledef:Job", "id": "j", "name": "Job"}]}
    assert build_mermaid_for_artifact(artifact) == ""


def test_single_position_no_relationships():
    artifact = {
        "items": [{"type": "orgdef:Position", "id": "solo", "name": "Solo"}],
    }
    out = build_mermaid_for_artifact(artifact)
    assert out.startswith("graph TD")
    assert 'solo["Solo"]:::vacant' in out
    assert "-->" not in out
    assert 'click solo call openPositionPanel("solo")' in out


def test_reports_to_renders_as_child_to_parent_arrow():
    artifact = {
        "items": [
            {"type": "orgdef:Position", "id": "child", "name": "Child"},
            {"type": "orgdef:Position", "id": "parent", "name": "Parent"},
        ],
        "relationships": [
            {"type": "reports_to", "from": "child", "to": "parent"},
        ],
    }
    out = build_mermaid_for_artifact(artifact)
    assert "child --> parent" in out


def test_directs_renders_inverse_of_reports_to():
    """`directs from A to B` == `reports_to from B to A` in tree form."""
    artifact = {
        "items": [
            {"type": "orgdef:Position", "id": "manager", "name": "Mgr"},
            {"type": "orgdef:Position", "id": "report", "name": "Rpt"},
        ],
        "relationships": [
            {"type": "directs", "from": "manager", "to": "report"},
        ],
    }
    out = build_mermaid_for_artifact(artifact)
    assert "report --> manager" in out


def test_secondary_edges_render_dashed_with_label():
    artifact = {
        "items": [
            {"type": "orgdef:Position", "id": "a", "name": "A"},
            {"type": "orgdef:Position", "id": "b", "name": "B"},
        ],
        "relationships": [
            {"type": "coordinates_with", "from": "a", "to": "b"},
            {"type": "validates_for", "from": "a", "to": "b"},
        ],
    }
    out = build_mermaid_for_artifact(artifact)
    assert "a -. coordinates_with .-> b" in out
    assert "a -. validates_for .-> b" in out


def test_external_endpoints_are_filtered_out():
    artifact = {
        "id": "myorg",
        "items": [{"type": "orgdef:Position", "id": "a", "name": "A"}],
        "relationships": [
            {"type": "coordinates_with", "from": "a", "to": "external:other-org"},
            {"type": "implements_for", "from": "myorg", "to": "external:spec-org"},
        ],
    }
    out = build_mermaid_for_artifact(artifact)
    assert "external" not in out
    assert "-." not in out  # no secondary edges should render


def test_live_state_drives_class_assignment():
    artifact = {
        "items": [
            {"type": "orgdef:Position", "id": "vacant_pos", "name": "Vacant"},
            {"type": "orgdef:Position", "id": "idle_pos", "name": "Idle"},
            {"type": "orgdef:Position", "id": "active_pos", "name": "Active"},
        ],
    }
    live = {
        "idle_pos": {"bound": True, "active_session_count": 0},
        "active_pos": {"bound": True, "active_session_count": 2},
    }
    out = build_mermaid_for_artifact(artifact, live=live)
    assert 'vacant_pos["Vacant"]:::vacant' in out
    assert 'idle_pos["Idle"]:::claimed_idle' in out
    assert 'active_pos["Active<br/>2 active"]:::claimed_active' in out


def test_classdefs_emitted_at_end():
    artifact = {
        "items": [{"type": "orgdef:Position", "id": "a", "name": "A"}],
    }
    out = build_mermaid_for_artifact(artifact)
    assert "classDef vacant" in out
    assert "classDef claimed_idle" in out
    assert "classDef claimed_active" in out


def test_label_escapes_double_quotes():
    artifact = {
        "items": [{"type": "orgdef:Position", "id": "a", "name": 'A "quoted" Name'}],
    }
    out = build_mermaid_for_artifact(artifact)
    assert '"A &quot;quoted&quot; Name"' in out


# --- Fixture rendering -------------------------------------------------------


def test_openbraid_org_fixture_renders():
    content = _load("openbraid-org")
    out = build_mermaid_for_artifact(content)
    assert out.startswith("graph TD")
    # All three positions present
    for pid in ("openbraid-director", "openbraid-strategist", "openbraid-engineer"):
        assert f'{pid}[' in out
        assert f'click {pid} call openPositionPanel' in out
    # reports_to chain present
    assert "openbraid-strategist --> openbraid-director" in out
    assert "openbraid-engineer --> openbraid-strategist" in out


def test_memodef_spec_fixture_renders():
    content = _load("memodef-spec")
    out = build_mermaid_for_artifact(content)
    assert out.startswith("graph TD")
    # All four positions
    for pid in ("director", "strategist", "maintainer", "canonical-implementor"):
        assert f'{pid}[' in out
    # reports_to + directs combine into single tree direction
    assert "strategist --> director" in out
    # `directs from strategist to maintainer` → `maintainer --> strategist`
    assert "maintainer --> strategist" in out
    assert "canonical-implementor --> strategist" in out


def test_thingalog_fixture_renders_jobs_excluded():
    """Jobs are items[] entries (roledef:Job) but MUST NOT appear as
    nodes in the chart — only Position items become nodes per the
    F-chart strategist memo."""
    content = _load("thingalog")
    out = build_mermaid_for_artifact(content)
    assert out.startswith("graph TD")
    # All six positions present
    for pid in (
        "product-owner", "product-strategist", "implementer",
        "mobile-developer", "security-tester", "revenue-officer",
    ):
        assert f'{pid}[' in out
    # roledef:Job items NOT rendered as nodes (they share ids with
    # positions like 'implementer' but as roledef:Job, not orgdef:Position).
    # The chart should have exactly six Position nodes — no job-node
    # duplicates. We verify by counting click directives.
    click_count = out.count("call openPositionPanel(")
    assert click_count == 6, f"expected 6 clickable positions, got {click_count}"
    # validates_for edge from security-tester to implementer (the
    # interesting non-tree edge that exercises secondary styling)
    assert "security-tester -. validates_for .-> implementer" in out
    # coordinates_with implementer→product-strategist (peer-style)
    assert "implementer -. coordinates_with .-> product-strategist" in out
    # External coordination edges (product-strategist → external:catdef-strategist)
    # must NOT render
    assert "external:" not in out
    assert "catdef-strategist" not in out
