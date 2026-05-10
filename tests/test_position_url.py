"""Unit tests for `server.db.parse_position_url`.

Phase C C5: claim_role accepts a position URL alongside name-based
inputs. The parser is the load-bearing primitive; live integration
tests cover the full claim flow.
"""

from __future__ import annotations

import pytest

from server.db import parse_position_url


def test_parse_three_segment_with_https_scheme():
    h, o, p = parse_position_url(
        "https://mcp.openbraid.app/scott/personal/personal-strategist"
    )
    assert (h, o, p) == ("scott", "personal", "personal-strategist")


def test_parse_three_segment_without_scheme():
    h, o, p = parse_position_url(
        "mcp.openbraid.app/scott/personal/personal-strategist"
    )
    assert (h, o, p) == ("scott", "personal", "personal-strategist")


def test_parse_two_segment_sugar_with_scheme():
    h, o, p = parse_position_url(
        "https://mcp.openbraid.app/scott/personal-strategist"
    )
    assert (h, o, p) == ("scott", None, "personal-strategist")


def test_parse_two_segment_sugar_without_scheme():
    h, o, p = parse_position_url("mcp.openbraid.app/scott/personal-strategist")
    assert (h, o, p) == ("scott", None, "personal-strategist")


def test_parse_path_only_three_segments():
    h, o, p = parse_position_url("/scott/personal/personal-strategist")
    assert (h, o, p) == ("scott", "personal", "personal-strategist")


def test_parse_path_only_two_segments():
    h, o, p = parse_position_url("/scott/personal-strategist")
    assert (h, o, p) == ("scott", None, "personal-strategist")


def test_parse_path_without_leading_slash():
    h, o, p = parse_position_url("scott/personal/personal-strategist")
    assert (h, o, p) == ("scott", "personal", "personal-strategist")


def test_parse_self_hosted_host():
    """Self-hosted instances live at any host; v0 doesn't validate the
    host — strips it and parses the path."""
    h, o, p = parse_position_url("https://mcp.firstchurch.org/treasurer/finance")
    assert (h, o, p) == ("treasurer", None, "finance")


def test_parse_too_few_segments():
    with pytest.raises(ValueError, match="2 or 3 path segments"):
        parse_position_url("scott")


def test_parse_too_many_segments():
    with pytest.raises(ValueError, match="2 or 3 path segments"):
        parse_position_url("scott/personal/personal-strategist/extra")


def test_parse_empty_url():
    with pytest.raises(ValueError, match="2 or 3 path segments"):
        parse_position_url("")
