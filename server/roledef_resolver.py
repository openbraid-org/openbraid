"""On-demand roledef resolution for artifact-backed boot payloads.

Phase E E3. An orgdef position carries `role_definition: {id, version, url}`
pointing at an external roledef artifact (canonical at roledef.org).
At boot-payload-assembly time we fetch the URL, parse the JSON, and
embed the content inline so the fresh agent gets the full role spec
without making the roundtrip itself.

Design choices:
- **In-process cache, keyed by URL.** No TTL on positive hits: the
  OAGP family's discipline says roledef URLs are versioned, so a
  content change implies a URL change. Stale cache risk is low and
  bounded by process lifetime (Railway recycles dynos frequently).
- **Aggressive timeout (2s).** A fresh-agent boot must be snappy;
  better to ship a reference + diagnostic than to wait on a slow CDN.
- **Diagnostic on failure, not exception.** Boot payload assembly
  cannot fail because of a remote fetch — the position metadata
  itself is local and authoritative. The fresh agent sees a
  reference shape (`{id, version, url, diagnostic}`) and can decide
  whether to fetch itself.

The cache is process-local and unsynchronized. The race on simultaneous
fetches for the same URL is benign: both fetches return the same
content; the last write wins; subsequent reads hit cache.
"""

from __future__ import annotations

import httpx

_TIMEOUT_SECONDS = 2.0
_cache: dict[str, dict] = {}


async def resolve_roledef(url: str) -> tuple[dict | None, str | None]:
    """Fetch and parse a roledef artifact at `url`.

    Returns:
        (content, None) on success. Content is the parsed JSON dict.
        (None, diagnostic) on any failure (timeout, non-2xx, parse error).
        Diagnostic is a short string suitable for inclusion in the
        boot payload's role_definition.diagnostic field.
    """
    if url in _cache:
        return _cache[url], None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url, follow_redirects=True)
    except httpx.TimeoutException:
        return None, f"roledef fetch timed out after {_TIMEOUT_SECONDS}s"
    except httpx.RequestError as e:
        return None, f"roledef fetch failed: {type(e).__name__}: {e}"

    if response.status_code != 200:
        return None, (
            f"roledef fetch returned HTTP {response.status_code}"
        )

    try:
        content = response.json()
    except ValueError:
        return None, "roledef response was not valid JSON"

    if not isinstance(content, dict):
        return None, (
            f"roledef response was JSON but not an object "
            f"(got {type(content).__name__})"
        )

    _cache[url] = content
    return content, None


def _clear_cache() -> None:
    """Reset the in-process cache. Test-only — production has no use case
    for explicit invalidation (URL changes drive cache turnover)."""
    _cache.clear()
