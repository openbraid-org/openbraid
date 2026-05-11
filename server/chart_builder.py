"""Mermaid graph text generation for org-chart visualization.

Phase F F-chart. Transforms an opencatalog's `items[]` + `relationships[]`
into Mermaid `graph TD` text that the browser renders client-side via
the Mermaid.js library.

Edge semantics:
- `reports_to` (and the inverse `directs`) → primary tree edges, solid
  arrows, render with the hierarchical layout Mermaid picks for top-down
  graphs.
- `peer_of`, `validates_for`, `implements_for`, `coordinates_with`,
  `derives_from` → secondary edges, dashed arrows with edge labels.
- Endpoints starting with `external:` or matching the org's own id are
  ignored — we only render Position-to-Position structure within the
  bundle. Cross-org / org-level relationships belong to a future view.

Live state semantics (per node):
- `vacant`: no live incumbents binding (status from openbraid, not the
  orgdef-declared `status` field — orgdef status is informational only)
- `claimed_idle`: incumbents binding exists but zero active auth_sessions
- `claimed_active`: incumbents binding exists with one or more active
  auth_sessions (count rendered inline on the node label)

Mermaid quirks worked around here:
- Node IDs with hyphens are fine in v10+ but quoted labels are safer
  when names contain spaces or punctuation.
- The HTML <br/> tag works inside quoted labels for multi-line text.
"""

from __future__ import annotations

PRIMARY_EDGE_TYPES = {"reports_to", "directs"}
SECONDARY_EDGE_TYPES = (
    "peer_of",
    "validates_for",
    "implements_for",
    "coordinates_with",
    "derives_from",
)


def _node_state(live: dict[str, dict] | None, position_id: str) -> tuple[str, int]:
    """Return (state, active_session_count) for a position id.

    `live` maps position_id → {"bound": bool, "active_session_count": int}.
    Defaults to vacant (no entry).
    """
    if not live or position_id not in live:
        return "vacant", 0
    row = live[position_id]
    if not row.get("bound"):
        return "vacant", 0
    count = int(row.get("active_session_count") or 0)
    return ("claimed_active" if count > 0 else "claimed_idle"), count


def _safe_label(name: str) -> str:
    """Mermaid label text inside double-quoted brackets.

    Escape backslashes and double quotes; turn embedded double quotes
    into HTML entities so Mermaid's lexer doesn't get confused.
    """
    return name.replace("\\", "\\\\").replace('"', "&quot;")


def build_mermaid_for_artifact(
    content: dict,
    live: dict[str, dict] | None = None,
) -> str:
    """Build the Mermaid `graph TD` text for an opencatalog.

    Args:
        content: parsed opencatalog dict (.opencatalog file content).
        live: optional per-position live state for the overlay. Keys
            are position ids; values are {"bound": bool,
            "active_session_count": int}. None or missing entries
            default to vacant.

    Returns:
        Mermaid text, ready for `<pre class="mermaid">…</pre>` on the
        client side. Empty string if the artifact has no Position items.
    """
    items = content.get("items") or []
    positions = [
        it for it in items
        if isinstance(it, dict) and it.get("type") == "orgdef:Position"
    ]
    if not positions:
        return ""

    position_ids = {p["id"] for p in positions if isinstance(p.get("id"), str)}
    org_self_id = content.get("id")

    lines: list[str] = ["graph TD"]

    # Node declarations with state-tied class assignments.
    for p in positions:
        pid = p["id"]
        name = p.get("name") or pid
        state, count = _node_state(live, pid)
        label = _safe_label(name)
        if state == "claimed_active":
            label = f"{label}<br/>{count} active"
        lines.append(f'    {pid}["{label}"]:::{state}')

    # Primary tree edges. `directs` is the inverse of `reports_to`;
    # rewrite to canonical child→parent direction.
    relationships = content.get("relationships") or []
    if not isinstance(relationships, list):
        relationships = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        rtype = rel.get("type")
        rfrom = rel.get("from")
        rto = rel.get("to")
        if rtype not in PRIMARY_EDGE_TYPES:
            continue
        if not (isinstance(rfrom, str) and isinstance(rto, str)):
            continue
        if rfrom not in position_ids or rto not in position_ids:
            continue
        if rtype == "reports_to":
            lines.append(f"    {rfrom} --> {rto}")
        else:  # directs
            lines.append(f"    {rto} --> {rfrom}")

    # Secondary edges (dashed, labeled).
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        rtype = rel.get("type")
        rfrom = rel.get("from")
        rto = rel.get("to")
        if rtype not in SECONDARY_EDGE_TYPES:
            continue
        if not (isinstance(rfrom, str) and isinstance(rto, str)):
            continue
        if rfrom not in position_ids or rto not in position_ids:
            continue
        # Skip self-loops and org-level relationships (handled elsewhere).
        if rfrom == org_self_id or rto == org_self_id:
            continue
        lines.append(f"    {rfrom} -. {rtype} .-> {rto}")

    # Click handlers — every Position is clickable.
    for p in positions:
        pid = p["id"]
        lines.append(f'    click {pid} call openPositionPanel("{pid}")')

    # ClassDefs for the three live states.
    lines.append(
        "    classDef vacant fill:#16161a,stroke:#c8a96a,"
        "stroke-width:2px,color:#e8e8ec"
    )
    lines.append(
        "    classDef claimed_idle fill:#1a1a1f,stroke:#555,color:#888"
    )
    lines.append(
        "    classDef claimed_active fill:#16161a,stroke:#7bc3e0,"
        "stroke-width:2px,color:#e8e8ec"
    )

    return "\n".join(lines)


def build_live_map_for_artifact(
    org_artifact_id: str,
    sb,
) -> dict[str, dict]:
    """Compute the per-position live state map for an artifact.

    Reads `incumbents` for the artifact (where ended_at is null) and
    aggregates `auth_sessions` live-count per bound role. The result
    feeds `build_mermaid_for_artifact`'s `live` argument.

    `sb` is the supabase client (passed in so callers can mock for
    tests; avoids a stale-singleton risk).
    """
    incumbents = (
        sb.table("incumbents")
        .select("position_id, claimed_role_id")
        .eq("org_artifact_id", org_artifact_id)
        .is_("ended_at", "null")
        .execute()
    )
    out: dict[str, dict] = {}
    for row in (incumbents.data or []):
        position_id = row["position_id"]
        role_id = row["claimed_role_id"]
        sessions = (
            sb.table("auth_sessions")
            .select("id")
            .eq("role_id", role_id)
            .is_("revoked_at", "null")
            .gt("expires_at", "now()")
            .execute()
        )
        out[position_id] = {
            "bound": True,
            "active_session_count": len(sessions.data or []),
            "role_id": role_id,
        }
    return out
