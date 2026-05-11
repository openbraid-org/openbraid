"""Minimal smoke test for the panel module.

The unit tests don't render the panel routes (those are browser-side
SSR templates), so missing-import / NameError bugs land in production.
This file exercises the route handlers with mocked dependencies just
enough to surface obvious wiring issues:

- module imports cleanly
- ruff finds no undefined names (executed by the import phase)
- the roles_page handler body runs to completion when its dependencies
  are mocked

Not a behavior test — just a smoke gate.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest


def test_panel_module_imports_cleanly():
    """A failed import here means the panel module body has a syntax
    error or a missing top-level import. Cheap and catches a real
    class of regressions."""
    module = importlib.import_module("server.panel")
    assert hasattr(module, "roles_page")
    assert hasattr(module, "role_delete")


def test_panel_module_has_no_undefined_names_per_ruff():
    """Run ruff in a subprocess and assert it finds no F821
    (undefined-name) issues in server/panel.py. F401 (unused-import)
    is non-blocking."""
    import subprocess
    import sys
    import pathlib

    panel_path = pathlib.Path(__file__).parent.parent / "server" / "panel.py"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "F821", str(panel_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("ruff not available in this environment")
    if "No module named ruff" in (result.stderr or ""):
        pytest.skip("ruff not installed in this environment")
    assert result.returncode == 0, (
        f"ruff found undefined-name issues in server/panel.py:\n"
        f"{result.stdout}\n{result.stderr}"
    )


async def test_chart_page_handler_redirects_on_handle_mismatch():
    """Phase F F-chart auth-scoping: chart routes redirect when the
    {account} segment doesn't match the signed-in user's handle. This
    test exercises the resolver path through the handler body so a
    future NameError lands here, not in production.
    """
    from server import panel
    from starlette.requests import Request

    fake_user = {"email": "scott@example.com"}
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/panel/orgs/alice/personal/chart",
        "raw_path": b"/panel/orgs/alice/personal/chart",
        "path_params": {"account": "alice", "org": "personal"},
        "query_string": b"",
        "scheme": "https",
        "server": ("www.openbraid.app", 443),
        "headers": [(b"host", b"www.openbraid.app")],
    }
    request = Request(scope)

    with patch.object(panel, "_current_user", return_value=fake_user):
        response = await panel.chart_page(request)

    assert response.status_code == 303
    assert "/panel/roles" in response.headers["location"]


async def test_roles_page_handler_runs_with_mocked_dependencies():
    """Exercise the roles_page handler end-to-end with mocks so
    function-body NameErrors (like the artifacts_for_account miss
    that surfaced in production for build 25) get caught here next
    time. We don't validate the rendered HTML — we just confirm the
    handler returns a response."""
    from server import panel

    fake_user = {"email": "scott@example.com"}
    fake_account_id = "acct-uuid"

    # Sub-mocks for the supabase chains the handler walks.
    from unittest.mock import MagicMock
    fake_sb = MagicMock()
    # roles list
    fake_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.execute.return_value.data = []
    # incumbents list (different chain depth; cover with same MagicMock semantics)
    fake_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value.data = []

    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/panel/roles",
        "raw_path": b"/panel/roles",
        "path_params": {},
        "query_string": b"",
        "scheme": "https",
        "server": ("www.openbraid.app", 443),
        "headers": [(b"host", b"www.openbraid.app")],
    }
    request = Request(scope)

    with patch.object(panel, "_current_user", return_value=fake_user), \
         patch.object(panel, "_account_id_for_user", return_value=fake_account_id), \
         patch.object(panel, "supabase", return_value=fake_sb), \
         patch.object(panel, "artifacts_for_account", return_value=[]):
        response = await panel.roles_page(request)

    # The handler returns either a TemplateResponse (200) or a
    # RedirectResponse depending on user/account state. Either way,
    # reaching this point without raising NameError is the goal.
    assert response.status_code in (200, 303)
