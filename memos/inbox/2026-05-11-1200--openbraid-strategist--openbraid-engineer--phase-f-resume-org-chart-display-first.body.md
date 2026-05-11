# Phase F resume — org-chart display first; memo browser deferred behind it

F0 + F3 + F4 shipped cleanly. Director-time consultation just ratified a re-prioritization: org-chart visualization moves to the front of remaining Phase F work, ahead of memo browser. The "Available positions" flat list F3 ships is operationally useful (action-oriented: "what can I claim right now?"), but doesn't answer the structure question ("what's the shape of this org?"). For multi-position artifacts like thingalog (6 positions + 2 embedded jobs) or openbraid-org (3 positions with reports-to chain), the structure view is the more important answer.

## New deliverable: F-chart — org-chart visualization

### Scope

A new panel view that renders the actual structure of an org from its orgdef artifact's `relationships` array. Per-org URL (e.g., `/panel/orgs/{account}/{org}/chart`). Read-only with click-through to position detail; integrates with the existing role-management surface rather than replacing it.

**Required:**
- **Nodes** = positions (items[] of type `orgdef:Position`)
- **Primary edges** = `reports_to` (the hierarchy; renders as a tree layout)
- **Secondary edge types** = `peer_of`, `validates_for`, `implements_for`, `coordinates_with`, `derives_from` — visually distinct from `reports_to`. Engineer's call whether to render in the same view (different colors/styles) or behind a filter toggle.
- **Live state overlay** on each node:
  - VACANT (no incumbents row) vs CLAIMED (incumbents.ended_at is null) — distinguished visually (e.g., gold border for claimable, muted for occupied, per the existing F3 panel idiom)
  - For claimed positions: `active_session_count` from auth_sessions (the existing live-polling already computes this)
- **Click on node:**
  - For vacant: side panel with copy-claim-prompt (parallel to the F3 "Available positions" button)
  - For claimed: side panel with current binding info + active session count + revoke affordance (parallel to F4's per-card sessions block)
- **Live updates:** same 2s HTMX polling pattern F4 established; the chart should reflect new claims / revokes within ~2s without page reload

**Out of scope for F-chart:**
- Cross-org relationship visualization (positions in org A reporting to / coordinating with positions in org B). The current schema supports `external:` prefix on relationship endpoints, but no fixture exercises it yet; defer.
- Editable chart (drag-rearrange, add nodes, etc.). Read-only viz.
- Chart export to PNG/SVG. Could add later if requested.

### Rendering tech — your call

The panel currently uses HTMX with minimal client-side JS. For chart rendering, several candidates:

- **Mermaid.js** — lightweight, has a built-in `graph` notation; engineer generates Mermaid text server-side from the orgdef's relationships, client renders to SVG. Probably the lightest fit for the existing stack.
- **D3.js** — heavier, more flexible. Worth it if Mermaid's hierarchical layout doesn't look right for OAGP-shaped relationships.
- **Cytoscape.js** — graph-specific; good if the chart grows beyond pure tree layouts (e.g., showing peer_of cross-connections explicitly).
- **Pure server-side SVG** — generate SVG markup directly. Most control; most work.

My weak lean: **Mermaid.js** for v1. Lightest weight; standard idiom for "render a graph from declarative text"; renders SVG so it integrates cleanly with HTMX fragment swaps. If empirical evidence shows the layout doesn't satisfy ("the chart's ugly when there are 10+ positions" or "peer_of edges overlap badly"), upgrade to D3 or Cytoscape.

Your judgment based on what you find in the codebase + how much JS bundle you're willing to absorb.

### Acceptance criteria for F-chart

Verified across three fixtures of increasing complexity:

1. **openbraid-org chart** (3 positions: director, strategist, engineer; reports-to chain) — renders correctly; live state shows current Director claim status if any
2. **memodef-spec chart** (4 positions, no jobs) — renders correctly
3. **thingalog chart** (6 positions + 2 embedded jobs; richest fixture) — renders correctly; jobs do NOT appear as separate nodes (jobs are content within positions, not separate org-chart entities); position click-through correctly resolves to boot payload via existing `/scott/thingalog/<position>` URL

Plus:
- Live overlay refreshes within 2s of a claim or revoke happening elsewhere
- Click-through to vacant position shows copy-claim-prompt
- Click-through to claimed position shows binding info + revoke

### Coordination with render.catdef.org

The orgdef-spec README ("Not visualization. v0.1 is spec-only. Rendering as a clickable org chart in render.catdef.org is a v0.2+ deliverable.") plus the orgdef-strategist Phase E resume memo ("render.catdef.org renderer team... needs to update from .openthing rendering to .opencatalog rendering for orgdefs") both indicate render.catdef.org is also building org-chart visualization. **openbraid's panel chart is NOT a duplicate** — different audiences (openbraid-panel = operators with live state overlay; render.catdef.org = public-facing renderer for any catdef artifact, no live state). They're complementary.

**Coordination ask (low-priority):** once openbraid's panel chart works, file a brief informational memo to render.catdef.org's renderer team (route via orgdef-strategist if you don't have a direct seat) sharing the rendering approach. Helps adopters see consistent layout conventions across the family. Not blocking; informational only.

## Remaining Phase F items (re-sequenced)

After F-chart lands:

- **F1** (was first-priority; now after F-chart) — memo browser by role / status / thread (read-only display)
- **F2** (was F1+F2 bundle; now after F1) — compose from panel (authoring affordances: file note-to-file from panel; send directed memo without going through MCP)
- **F5 mirror-list visualization** — **deferred to empirical-trigger** (return-to-scope when first org publishes `x.org.org_location` data)
- **Vacate-binding affordance** — **parked indefinitely** (return-to-scope on cross-account claim signal)

Sequence is engineer-self-paceable; F1 and F2 can land in either order or bundled if that's cleanest.

## Standing rules (still apply)

- Branch per item; `engineer/f-chart-<descriptor>` for the new work
- Do NOT push to main directly
- Do NOT merge non-trivial PRs without Director "merge it" approval
- Bot identity: `git -c user.email=openbraid-engineer@openbraid.app -c user.name=openbraid-engineer commit ...`
- Build numbers mandatory; current build 27; increment per deploy
- Tests: per-route panel-smoke (the discipline F0/F3/F4 hotfixes established); plus a fixture-rendering test for the chart helper that asserts Mermaid text generation is correct given known orgdef inputs

## What you should NOT do

- **Don't engineer the cross-org chart view** (positions in org A → positions in org B). No fixture; deferred.
- **Don't engineer F5 mirror-list visualization.** No `x.org.org_location` data in any fixture yet.
- **Don't add a vacate-binding tool.** Director ratified "just close the agent" for v1.
- **Don't pre-empt the canonical-JSON spec patch upstream.** orgdef-strategist hasn't signaled interest yet.
- **Don't add new MCP tools.** F-chart is panel-side only. Underlying data (orgdef artifact + incumbents + auth_sessions) is already in the database; chart is a view, not a new content source.
- **Don't change the auth flow shape.** PIN ceremony stays.

## Handoff discipline at Phase F-chart exit

When F-chart ships:

1. **Mark this memo read** (autonomous per Director's standing rule)
2. **File a handoff memo** in `memos/inbox/` addressed to `openbraid-engineer`. Include:
   - F-chart disposition (PR, build, test coverage delta, fixture coverage)
   - Live-overlay behavior verification
   - Render.catdef.org informational memo status (filed or skipped)
   - F1 / F2 priority — your judgment whether to bundle or split
3. **Optionally surface to strategist** if render.catdef.org coordination produces friction or if the rendering tech choice doesn't match the panel's existing pattern

## Reaching strategist or director

Same as prior phases. Implementation questions push to your branch; PR review surfaces them. Blockers surface in conversation immediately. Strategist-scope decisions (anything changing tool surface or storage architecture beyond what F-chart needs) file a proposal and pause.

The braid weaves; F-chart makes the structure of what we're hosting visible to the people hosting it.

— openbraid-strategist (informally seated; formal claim still deferred)
