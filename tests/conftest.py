"""Shared pytest fixtures for the openbraid test suite."""

from __future__ import annotations

import pytest

from server.main import mcp


@pytest.fixture
def server():
    """Return the FastMCP server instance under test."""
    return mcp
