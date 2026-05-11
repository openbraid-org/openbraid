"""Master/replicant detection for opencatalog content.

Phase F F-chart-2. Per orgdef-strategist's 2026-05-11 17:30 memo: an
opencatalog optionally carries `x.org.master_url`, a single string at
the top level pointing at the authoritative copy. Three states:

  - field absent → this openbraid instance is master (editable)
  - field points at an openbraid URL → master (editable)
  - field points elsewhere (github, gitlab, etc.) → replicant (read-only)

This module returns a structured state dict; templates surface a
"Mastered here" / "Mirrored from <host>" badge from it. The actual
fetcher / resolver (github URL translator, replicant sync) lands in
a follow-up PR per openbraid-strategist's note 1 ("fetch via resolver
at setup, manual Refresh from master button, no periodic polling").
"""

from __future__ import annotations

from urllib.parse import urlparse


_OPENBRAID_HOSTS = (
    "openbraid.app",
    "www.openbraid.app",
    "mcp.openbraid.app",
)


def detect_master_state(content: dict) -> dict:
    """Return a structured master-state dict for an opencatalog.

    Output shape:
      {
        "kind": "master" | "replicant",
        "master_url": str | None,
        "host": str | None,
        "host_label": str,         # display-ready: "openbraid" | "github" | hostname
        "is_editable": bool,
      }

    `is_editable` is the rule the templates and edit routes consult:
    true when this instance is master, false when replicant.
    """
    master_url = content.get("x.org.master_url")
    if not isinstance(master_url, str) or not master_url:
        return {
            "kind": "master",
            "master_url": None,
            "host": None,
            "host_label": "openbraid",
            "is_editable": True,
        }

    parsed = urlparse(master_url)
    host = parsed.hostname or ""

    # Openbraid URL → still master from our perspective (this IS the
    # master instance; the field just self-references for clarity).
    if any(host == h or host.endswith("." + h) for h in _OPENBRAID_HOSTS):
        return {
            "kind": "master",
            "master_url": master_url,
            "host": host,
            "host_label": "openbraid",
            "is_editable": True,
        }

    # Replicant. Categorize the host for the badge text. Gist check
    # FIRST because gist.github.com would otherwise match the broader
    # github rule.
    label = host
    if host.startswith("gist."):
        label = "github gist"
    elif host == "github.com" or host.endswith(".github.com"):
        label = "github"
    elif host == "gitlab.com" or host.endswith(".gitlab.com"):
        label = "gitlab"
    elif host == "codeberg.org" or host.endswith(".codeberg.org"):
        label = "codeberg"

    return {
        "kind": "replicant",
        "master_url": master_url,
        "host": host,
        "host_label": label,
        "is_editable": False,
    }
