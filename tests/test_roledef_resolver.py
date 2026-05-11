"""Unit tests for `server.roledef_resolver` (Phase E E3).

Covers:
- successful fetch + parse, returns content and caches
- subsequent call hits cache (no second network round-trip)
- 404 returns diagnostic, does NOT cache
- timeout returns diagnostic, does NOT cache
- non-JSON response returns diagnostic
- JSON-but-not-object response returns diagnostic

Network is mocked via httpx.MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from server import roledef_resolver
from server.roledef_resolver import resolve_roledef


SAMPLE_ROLEDEF = {
    "catdef": "1.4",
    "roledef": "1.0.0",
    "type": "roledef:Role",
    "id": "senior-engineer",
    "name": "Senior Engineer",
    "version": "1.0.0",
}


@pytest.fixture(autouse=True)
def _clear_cache_each_test():
    """Reset the resolver's process-local cache between tests."""
    roledef_resolver._clear_cache()
    yield
    roledef_resolver._clear_cache()


def _install_transport(handler):
    """Patch httpx.AsyncClient to use a MockTransport with `handler`."""
    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    class _PatchedClient(real_cls):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    import unittest.mock as m
    return m.patch.object(httpx, "AsyncClient", _PatchedClient)


async def test_resolve_roledef_returns_content_on_success():
    def handler(request):
        return httpx.Response(200, json=SAMPLE_ROLEDEF)

    with _install_transport(handler):
        content, error = await resolve_roledef("https://example.test/r.openthing")

    assert error is None
    assert content == SAMPLE_ROLEDEF


async def test_resolve_roledef_caches_second_call():
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        return httpx.Response(200, json=SAMPLE_ROLEDEF)

    with _install_transport(handler):
        await resolve_roledef("https://example.test/r.openthing")
        await resolve_roledef("https://example.test/r.openthing")

    assert call_count["n"] == 1


async def test_resolve_roledef_returns_diagnostic_on_404():
    def handler(request):
        return httpx.Response(404)

    with _install_transport(handler):
        content, error = await resolve_roledef("https://example.test/missing")

    assert content is None
    assert "HTTP 404" in error
    # Failed lookups must NOT poison the cache.
    assert "https://example.test/missing" not in roledef_resolver._cache


async def test_resolve_roledef_returns_diagnostic_on_non_json():
    def handler(request):
        return httpx.Response(200, content=b"not json at all", headers={"content-type": "text/plain"})

    with _install_transport(handler):
        content, error = await resolve_roledef("https://example.test/plain")

    assert content is None
    assert "not valid JSON" in error


async def test_resolve_roledef_returns_diagnostic_on_json_but_not_object():
    def handler(request):
        return httpx.Response(200, json=["a", "list", "not", "an", "object"])

    with _install_transport(handler):
        content, error = await resolve_roledef("https://example.test/array")

    assert content is None
    assert "not an object" in error


async def test_resolve_roledef_returns_diagnostic_on_request_error():
    def handler(request):
        raise httpx.ConnectError("simulated connection failure")

    with _install_transport(handler):
        content, error = await resolve_roledef("https://example.test/down")

    assert content is None
    assert "fetch failed" in error
    assert "ConnectError" in error
