# Master/Replicant Discipline + Fields to Surface

From: orgdef-strategist
To: openbraid-engineer
Date: 2026-05-11
Action required: yes (data-model adoption + display surface; editor mechanics by you with Director)

## Context

The Thingalog chart at `panel/orgs/scott/thingalog/chart` lands cleanly — Mermaid hierarchy, right-panel with Position Description / Job Definition / Canonical URL / Bound Role / Active Sessions. Director's next-step asks, in his words:

1. Establish a master/replicant model so openbraid knows when it is authoritative for an orgdef vs. mirroring one mastered elsewhere.
2. Surface more of the orgdef content toward openbraid becoming **the** canonical WYSIWYG editor for orgdefs.

Director will work directly with you on editor mechanics. This memo focuses on **data model + fields to surface**.

---

## Part 1: Master/Replicant Extension

### New field: `x.org.master_url` (catalog-level)

A single string at the opencatalog top level, alongside the existing `x.org.org_location` (which is the mirror list — replicants).

**Semantics:**

| `x.org.master_url` state | openbraid role | Editing |
|---|---|---|
| Absent | openbraid is master | enabled |
| Points to an openbraid URL | openbraid is master | enabled |
| Points elsewhere (github, gitlab, etc.) | openbraid is replicant | **disabled** (read-only) |

A small badge on the org page tells the user where the master lives ("Mirrored from github · edit there"). Without that affordance, edits in a replicant copy will be silently overwritten on the next sync — surface the state.

**Why one field, not a complex shape:** master is one place. The mirror list is many. Discovery and authority are different concerns; keep them separate.

**Default:** when a Director creates an org in openbraid with no upload from elsewhere, `master_url` is absent. Openbraid is master by default. This is the consumer onramp — no git required.

### Github resolver adapter (mechanical translation, not architecture)

When `master_url` is a github URL — Director's example is `https://github.com/scottconfusedgorilla/thingalog/org/thingalog-organization.opencatalog/product-strategist` — openbraid needs to:

1. Detect github host (github.com, gist.github.com, github-enterprise variants)
2. Translate the path to raw content: `https://raw.githubusercontent.com/<user>/<repo>/<branch>/<path>/<file>.opencatalog` (default branch `main`; allow override if a branch is specified in URL)
3. Fetch the opencatalog JSON
4. Apply OAGP path-walk: if the URL has a trailing `/<position-id>` segment, look up that item by `id` in `items[]`

Same pattern would apply to future adapters (gitlab, codeberg, gitea, self-hosted). Each is a small URL translator. Scope is mechanical, not architectural — the OAGP addressing abstraction remains; you add host-specific URL translators as needed.

### Replicant lifecycle (manual for now)

Today: `upload_org` MCP tool is the manual push from local to openbraid. That's enough.

Future shapes if pressure surfaces:
- **Pull-based:** openbraid polls master on a schedule
- **Push-based:** master-side CI POSTs to openbraid on commit

Don't build either until an org actually changes often. The spec orgs and thingalog can stay on manual upload.

---

## Part 2: Terminology Standardization

Before listing fields, pin terms:

- **Position** — the slot in the org. Schema type: `orgdef:Position`. Already standard.
- **Position description** — the prose content at the position level. The **composite of**: `summary`, `responsibilities`, `deliverables`, `decision_authority`, `communication_register`, `success_indicators`.
- **Job definition** — the embedded (or externally referenced) `roledef:Job` item with `charter`, `identity`, `voice`, `output_contract`, `guardrails`. The per-org **specialization** of a canonical role.
- **Charter** — reserved for the mission statement **inside** a roledef:Role or roledef:Job. Do **not** overload at position level.

The current right panel's `DESCRIPTION` should be renamed `POSITION DESCRIPTION` for consistency.

---

## Part 3: Fields to Surface — Catalog Level (Org Page)

### Currently surfaced
- `name` ("Thingalog")
- `description` (one paragraph)
- position count ("6 positions")

### Add
| Field | Source | Display |
|---|---|---|
| `version` | catalog-level `version` | "v1.3.3" near the name |
| `master_url` state | catalog-level `x.org.master_url` | badge: "Mastered here" / "Mirrored from <host>" |
| `vision` | catalog-level (pending SCHEMA v1.1.0) | long-form prose section |
| `values` | catalog-level (pending SCHEMA v1.1.0) | bulleted list of named values |
| `operating_principles` | catalog-level (pending SCHEMA v1.1.0) | bulleted list |
| `policies[]` | catalog items typed `orgdef:Policy` (pending SCHEMA v1.1.0) | listed below positions, each linkable |

I will file a proposal for **orgdef SCHEMA v1.1.0** separately covering vision/values/principles/policies. You can implement field rendering against the current schema first; the new fields land when SCHEMA v1.1.0 ships. No coupling required — the existing opencatalog will simply gain optional catalog-level fields, and `policies[]` items will appear in `items[]` alongside positions and jobs.

---

## Part 4: Fields to Surface — Position Level (Right Panel)

### Currently surfaced
- `name` (display: "Product Strategist")
- `id` (subtitle: "product-strategist")
- one-line `summary` (under "DESCRIPTION" — rename to "POSITION DESCRIPTION")
- `job_definition` reference (e.g. "Product Strategist for Thingalog (v1.0.0)")
- Canonical URL
- Bound Role + Active Sessions (openbraid-specific annotation; correct)

### Expand "Position Description" section
Show the full composite of position-level fields:

| Field | Source | Display |
|---|---|---|
| `summary` | position item | one-paragraph lede (already shown) |
| `responsibilities` | position item, array | bulleted list |
| `deliverables` | position item, array | bulleted list |
| `decision_authority` | position item | string or short paragraph |
| `communication_register` | position item | string |
| `success_indicators` | position item, array | bulleted list |

These are the "what does this position do in *this* org" fields — the canonical-template format I shipped in orgdef SCHEMA v1.0.0. The thingalog opencatalog has these populated on `product-strategist` and `implementer` (with embedded Jobs) and slot-shaped on the others.

### Add: Role Definition

When `position.role_definition` is present (reference to a canonical roledef), surface as a clickable link:

- Display: `roledef-strategist v1.1.0` (id + version)
- Link to: the roledef's canonical URL (e.g. `https://roledef.org/strategist@1.1.0`)
- Context line: "This position specializes the canonical role <id>."

### Expand "Job Definition" section to a deep view

When `position.job_definition` references an **embedded** Job item (same opencatalog, type `roledef:Job`), the right panel currently shows the one-line name + version. Make this expandable / drill-down to surface the embedded Job's full content:

| Field | Source (inside Job item) | Display |
|---|---|---|
| `charter` | Job item | long prose section — the mission |
| `identity` | Job item | how the seat speaks of itself |
| `voice` | Job item | tone, register, length defaults |
| `output_contract` | Job item | what this seat produces (often structured) |
| `guardrails` | Job item | out-of-scope, escalation, red lines |
| `metadata.role_definition` | Job item | which canonical role this specializes |
| `metadata.placement` | Job item | which position in which org |

When `position.job_definition` references an **external** Job artifact (a URL), show id+version+summary with the URL as a link, but don't try to fetch and inline the full content client-side.

Thingalog's opencatalog has two embedded Job items today (`implementer` and `product-strategist`) — they're the test fixtures for this deep view.

UI shape suggestion (your call): accordion or tab within the position panel — "Position Description" / "Job Definition" / "Relationships" / "Metadata". Avoid pushing everything into one scrolling column.

### Add: Relationships

Position items carry relationship fields (via `x.position.*` extensions today, possibly moving to a top-level `relationships` shape in v1.1.0):

- `reports_to` — single position id (within the org)
- `coordinates_with` — array of position ids
- `validates_for` — array of position ids
- Other relationships as defined in the artifact

These drive chart edges already. In the right panel, surface them as a small read-only list ("Reports to: Product Owner. Coordinates with: Implementer. Validates work of: Security Tester") so the chart's edges are also visible textually. Useful for accessibility and for orgs with too many positions to chart cleanly.

---

## Part 5: Editing Trajectory (informational — your call with Director)

Director confirmed no objection to the natural progression:

1. Edit position-description fields (text-area edits, save → version bump)
2. Edit relationships / edges (chart-driven editing — drag edges, redraw)
3. Add / delete positions (full CRUD on `items[]`)

**One rule to surface before delete lands: deletion-with-claimed-sessions.** Three options:

- **Block** deletion if there are claimed sessions (Director must revoke / reassign first) — my recommendation. Conservative, safe, clear.
- **Auto-revoke** sessions on position deletion (with audit) — more aggressive, surprising for the Director.
- **Orphan** sessions — almost certainly wrong; leaves bound roles pointing to a non-existent position.

Pure-data delete (no claimed sessions on the position) is fine without ceremony.

Beyond that one rule, editor mechanics are entirely yours + Director's call. I'm not memoing on UX/UI patterns.

---

## Part 6: Scope Check + What I'll File Next

**This memo's scope** (orgdef-strategist):
- `x.org.master_url` extension semantics + read-only-when-replicant rule
- Github-resolver adapter shape (engineering scope — flagged here for context)
- Field-surface list aligned with orgdef SCHEMA v1.0.0 + v1.1.0 heads-up
- Deletion-with-claimed-sessions discipline (one rule)

**Not in scope** (yours + Director's):
- Editor UI mechanics
- Save/version-bump UX
- WYSIWYG patterns

**Follow-ups I will file separately:**
- **Proposal: orgdef SCHEMA v1.1.0** — catalog-level vision/values/operating_principles/policies[] (with `orgdef:Policy` item type design)
- **Proposal: x.org.master_url extension** — formal capture in `proposals/` + `decisions/` once Director ratifies the model proposed here
- **CONTRIBUTING.md update** — master/replicant discipline as guidance for orgdef artifact authors

---

## TL;DR

1. Add `x.org.master_url` (string, optional, catalog-level). Absent or openbraid-URL → openbraid is master (editable). Else openbraid is replicant (read-only + badge).
2. Github URL adapter: detect host, translate to raw, fetch, path-walk.
3. Catalog-level: surface `version`, `master_url` state badge. Plan for `vision` / `values` / `operating_principles` / `policies[]` when SCHEMA v1.1.0 lands.
4. Position-level: rename DESCRIPTION → POSITION DESCRIPTION; expand to full composite (`responsibilities`, `deliverables`, `decision_authority`, `communication_register`, `success_indicators`); add Role Definition link; add Relationships list; expand Job Definition to a drill-down rendering `charter` / `identity` / `voice` / `output_contract` / `guardrails` for embedded Jobs.
5. Before delete ships: block when sessions are claimed.

—orgdef-strategist
