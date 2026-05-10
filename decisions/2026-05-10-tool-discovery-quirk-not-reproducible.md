# A1 — Tool-discovery quirk on Anthropic Connectors: not reproducible

**Closed:** 2026-05-10 by openbraid-engineer
**Source:** [`proposals/2026-05-10-v1-roadmap-sequencing.md`](../proposals/2026-05-10-v1-roadmap-sequencing.md) Phase A item A1
**Related thread:** previously tracked in [`memos/read/2026-05-09-0015--openbraid-engineer--openbraid-engineer--v0-shipped-and-cross-runtime-proved.body.md`](../memos/read/2026-05-09-0015--openbraid-engineer--openbraid-engineer--v0-shipped-and-cross-runtime-proved.body.md) ("§Outstanding threads — Tool-discovery quirk on Anthropic Connectors").

## What we were investigating

In session 1 (2026-05-08, ~midnight Director-time), Brother-Desktop-Claude's first `tool_search` for openbraid surfaced 5 of 6 tools — `send_memo` was missing on first search; a second search returned all 6. The contract tests passed on all six locally, so the gap appeared client-side.

Phase A item A1 asked the engineer seat to reproduce: open a fresh Claude Desktop session pointed at `mcp.openbraid.app/mcp`, ask it to search available tools, count what comes back. If first-search returns all 6 reliably across 2-3 reproductions: close as one-off. If consistently misses one: file a proposal.

## Reproduction result

**3 of 3 reproductions returned all 6 tools on first search**, in fresh Claude Desktop sessions on 2026-05-10. Tools surfaced reliably: `claim_role`, `auth_with_pin`, `list_inbox`, `read_memo`, `mark_read`, `send_memo`. No second search needed.

## Closure

The original 5-of-6 observation was a one-off, almost certainly a transient state during initial Connector registration or MCP-session bootstrap that has since stabilized. **No code change.** No follow-up issue. Future-engineer-self may safely ignore this thread unless the symptom recurs across multiple sessions.

If the quirk recurs and is reproducible: re-open by filing a proposal in `proposals/` and investigate whether it's our FastMCP `tools/list` registration shape (e.g., `listChanged: true` advertised but no notification sent on first connect) or Claude Desktop's tool-discovery sequencing. Don't pre-emptively work around it without empirical signal.

## Why this is here at all

A "we investigated and found nothing wrong" record is small but non-zero value: it prevents a future engineer-session from spending another half-day chasing the same ghost. The standing rule for solo-merging tiny diagnostic / log-only PRs (Director's auto-memory `feedback_openbraid_solo_merges.md`) covers this kind of artifact, and the Phase A kickoff memo explicitly authorized solo-merge for the not-reproducible case.

— openbraid-engineer (2026-05-10)
