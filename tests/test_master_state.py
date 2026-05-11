"""Unit tests for master/replicant detection (Phase F F-chart-2).

Per orgdef-strategist's 2026-05-11 17:30 memo:
- Absent `x.org.master_url` → openbraid is master (editable)
- `x.org.master_url` points at openbraid URL → still master
- `x.org.master_url` points elsewhere → replicant (read-only)

The host_label categorization drives the chart's "Mirrored from X" badge.
"""

from __future__ import annotations

from server.master_state import detect_master_state


def test_absent_master_url_means_master():
    state = detect_master_state({})
    assert state["kind"] == "master"
    assert state["is_editable"] is True
    assert state["master_url"] is None
    assert state["host_label"] == "openbraid"


def test_empty_string_master_url_means_master():
    state = detect_master_state({"x.org.master_url": ""})
    assert state["kind"] == "master"
    assert state["is_editable"] is True


def test_non_string_master_url_means_master():
    """Defensive: malformed master_url shouldn't crash detection."""
    state = detect_master_state({"x.org.master_url": 42})
    assert state["kind"] == "master"


def test_openbraid_url_is_still_master():
    state = detect_master_state({
        "x.org.master_url": "https://mcp.openbraid.app/scott/thingalog",
    })
    assert state["kind"] == "master"
    assert state["is_editable"] is True
    assert state["host_label"] == "openbraid"


def test_www_openbraid_url_is_master():
    state = detect_master_state({
        "x.org.master_url": "https://www.openbraid.app/scott/thingalog",
    })
    assert state["kind"] == "master"


def test_github_url_is_replicant():
    state = detect_master_state({
        "x.org.master_url": "https://github.com/scottconfusedgorilla/thingalog/org/thingalog-organization.opencatalog",
    })
    assert state["kind"] == "replicant"
    assert state["is_editable"] is False
    assert state["host"] == "github.com"
    assert state["host_label"] == "github"
    assert state["master_url"].startswith("https://github.com/")


def test_gitlab_url_is_replicant():
    state = detect_master_state({
        "x.org.master_url": "https://gitlab.com/group/repo/-/blob/main/org.opencatalog",
    })
    assert state["kind"] == "replicant"
    assert state["host_label"] == "gitlab"


def test_codeberg_url_is_replicant():
    state = detect_master_state({
        "x.org.master_url": "https://codeberg.org/user/repo/raw/branch/main/org.opencatalog",
    })
    assert state["kind"] == "replicant"
    assert state["host_label"] == "codeberg"


def test_unknown_host_replicant_uses_raw_hostname_label():
    state = detect_master_state({
        "x.org.master_url": "https://example.org/some/path",
    })
    assert state["kind"] == "replicant"
    assert state["host_label"] == "example.org"


def test_gist_url_categorized_as_github_gist():
    state = detect_master_state({
        "x.org.master_url": "https://gist.github.com/user/abc123",
    })
    assert state["kind"] == "replicant"
    assert state["host_label"] == "github gist"
