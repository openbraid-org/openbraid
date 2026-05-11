# Phase E kickoff — orgdef ingestion as canonical store

Welcome back. Phase D shipped beautifully — five-vendor MCP-native roster, REST adapter as durable structural insight. Phase E is now in front of you, and it's larger than the original v1 roadmap projected. Don't engineer past the principle without reading the source memos first.

## Read order before doing anything

1. **[orgdef-strategist's 10:30 memo](2026-05-10-1030--orgdef-strategist--openbraid-strategist--phase-e-orgdef-ingestion-and-url-space.openthing)** — the canonical reference for Phase E. Read this BEFORE this kickoff. The "missing principle" section is the load-bearing claim.
2. **[orgdef-strategist's 10:00 memo](2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing)** — foundational. The 10:30 memo builds on this.
3. **[v1 roadmap proposal](../../proposals/2026-05-10-v1-roadmap-sequencing.md)** + **[Phase E shape addendum](../../proposals/2026-05-10-v1-roadmap-sequencing-addendum.md)** — captures Phase numbering swap and Phase E shape change.
4. [`CLAUDE.md`](../../CLAUDE.md), your roledef at [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing), and this memo.

## The principle (memorize this)

> **openbraid is the HOSTING layer; orgdef.openthing artifacts are the CONTENT layer.** openbraid INGESTS catdef-substrate orgdef.openthing artifacts as the source of truth, stores them in canonical JSON form, exposes them via the MCP URL space, and provides full-fidelity export to round-trip the same artifact back out.

openbraid does not invent its own data model for positions, relationships, governance, or recommended_patterns. Everything traces back to the artifact. The artifact in is the artifact out.

## Honest scope: this is a refactor, not additive

I assess that Phases A–D went the openbraid-native data model route — current schema has `accounts`, `roles`, `memos`, etc. as openbraid-native rows; no orgdef.openthing artifact lives in the database. The boot payload at position URL is constructed from openbraid-native columns rather than derived from a stored orgdef.

That means Phase E inverts the storage model so orgdef.openthing is the canonical store. Migration of existing data, redesign of the boot payload assembly, possible MCP surface revisions. Bigger than additive; not as bad as a rewrite. Phases A–D are still good work; this is the next layer that integrates them with the family.

If your read of the codebase contradicts mine — if A–D actually got the inference right and Phase E IS additive — surface that immediately and we'll narrow scope.

## Five deliverables (per orgdef-strategist 10:30 memo)

### E1 — Orgdef.openthing ingestion (upload path)

Accept a catdef-substrate `.openthing` artifact of type `orgdef:Organization` and store it as canonical content for an `<account>/<org>` URL.

- **Validation:** catdef-substrate envelope check + orgdef SCHEMA conformance check (per `orgdef-spec/orgdef/SCHEMA.md`).
- **Storage format:** the JSON itself in a JSONB column. Round-trip MUST be byte-equivalent.
- **Import path:** upload only for E1. Drag-drop in panel + API endpoint that accepts an uploaded `.openthing` file. **Fetch-from-git is deferred to a future phase** (would need git-protocol implementation; out of scope).

### E2 — Job artifact ingestion (part of the org bundle)

Each orgdef may reference job artifacts at `<org>/jobs/<job-id>.openthing` per the canonical-template placement convention. These are SEPARATE catdef-substrate `.openthing` files of type `roledef:Job`.

- Ingest as part of the org bundle (uploaded alongside, or fetched from a manifest within the org artifact)
- Resolve `position.job_definition.url` references at boot-payload-assembly time
- Treat job artifacts as second-class storage citizens (they belong to one org; not addressed directly via the canonical URL space — embedded in position boot payloads)
- If a position references a job_definition but the artifact isn't present, surface explicitly in boot payload (`"job_definition": null` with diagnostic note, NOT silent omission)

### E3 — Roledef reference resolution (external; on-demand for v1)

Each position may have a `role_definition` field pointing at a canonical roledef URL at `roledef.org/roledefs/<id>.openthing` or self-hosted equivalent.

- openbraid does NOT store roledefs natively (they're external to the org's scope)
- **On-demand resolution for v1:** fetch the roledef at boot-payload-assembly time. Simple; works if roledef.org is reliable. Latency cost is acceptable.
- Embed the roledef's content in the boot payload (not just a reference)
- If fetch fails, surface explicitly (`"role_definition": null` with diagnostic; same pattern as E2's missing-job case)
- Caching deferred until performance pressure surfaces empirically

### E4 — URL space exposure (per the 10:00 memo's three-level semantics)

- `mcp.openbraid.app/<account>` → ordered list of orgs hosted by the account
- `mcp.openbraid.app/<account>/<org>` → positions ordered by depth-first-path-walk derived from the orgdef artifact's `relationships`
- `mcp.openbraid.app/<account>/<org>/<position>` → fresh-agent boot payload
- Two-segment sugar (`mcp.openbraid.app/<account>/<position>`) when account hosts exactly one org

The boot payload assembly logic refactors to **read from the JSONB column**, traverse the `relationships` array in code (BFI sub-millisecond DFS), fold in resolved roledef + job artifacts.

### E5 — Full-fidelity export (was C7)

MCP tool: `export_org` (or equivalent name; engineer's choice). Returns the canonical `.openthing` JSON for a given `<account>/<org>` URL.

- **Byte-equivalent to the originally-ingested artifact** is the load-bearing property. Test: ingest a known artifact, export it, SHA-256 match. If they don't match, the round-trip is broken and we have lock-in.
- Parallel `export_job` (or include in `export_org`'s response as a bundle) for job artifacts
- The org bundle is portable as a unit

Director-ratified C7 deferral is dissolved; E5 makes export a Phase E MUST per the orgdef-strategist memo. ("Without portable export, openbraid would be lock-in.") This was always the right framing; the empirical-trigger deferral was an interim posture.

## Storage shape (Postgres JSONB; Neo4j evaluated and rejected)

Director ratified Postgres JSONB over a graph DB 2026-05-10 evening. Rationale: the canonical store IS the JSON artifact; the relationships live INSIDE the artifact as fields. Wherever we store, we just store JSON. Boot payload DFS over <20-position artifacts is sub-millisecond in code. Adding Neo4j would double operational complexity (especially for self-host story in Phase G) without addressing any actual query bottleneck.

Sketch of the new tables (engineer adjusts):

- **`org_artifacts`** — id (UUID pk), account_id (uuid fk), org_slug (text), content (JSONB — the orgdef.openthing artifact), version (text — extracted from artifact's `version` field), created_at, updated_at, deleted_at. Unique constraint on `(account_id, org_slug)` where deleted_at is null.
- **`job_artifacts`** — id (UUID pk), org_artifact_id (uuid fk), job_id (text — extracted from artifact's `id` field), content (JSONB), created_at, updated_at, deleted_at. Unique constraint on `(org_artifact_id, job_id)` where deleted_at is null.
- **`incumbents`** — id (UUID pk), org_artifact_id (uuid fk), position_id (text — references a `position.id` in the artifact), claimed_role_id (uuid fk → `roles` table; tracks which openbraid role currently inhabits this position), created_at, ended_at. Lets multiple historical incumbents per position be tracked; openbraid-managed runtime state, not artifact content.
- **`roledef_cache`** — only if E3 chooses caching later; defer for now.

Existing `accounts`, `roles`, `memos`, `pin_challenges`, `auth_sessions` mostly stay. The `roles` table semantics evolve: a `role` row now represents "an openbraid-managed authentication identity that may inhabit a position in an org_artifact" rather than "a position itself." The position-as-content lives in the org_artifact; the role-as-runtime-identity lives in `roles`. The mapping is the `incumbents` table.

If this maps awkwardly to the existing schema, push back via proposal. The engineer-side architecture choice is yours.

## Phase E sequencing (memo's recommendation, sound)

Critical path: **E1 → E2 → E4 → E5**.

- **E1 first** — storage substrate. Land the `org_artifacts` table + ingest tool + validation. Get one artifact (Thingalog or one of the spec-orgs) ingested end-to-end. Validate round-trip on ingest (parse JSON → store JSONB → fetch back → byte-equivalent).
- **E2 + E3 in parallel** — both feed E4's boot payload. E3 is lower priority (positions without roledef_url still work; boot payload renders `role_definition: null`). E2 needs the same validation discipline as E1.
- **E4** — refactor boot payload assembly to read from `org_artifacts` (+ resolve E2/E3 dependencies). The existing URL routes from C1/C2/C5 stay; their internal data source changes.
- **E5** — full-fidelity export. Implement and test SHA-256 round-trip. Ship at the same time as E4 or immediately after.

The engineer can fragment further across PRs as they see fit. Suggested PR shape:

1. PR (E0 prep): introduce `org_artifacts` table + manual-upload tool; add boot-payload-from-artifacts code path with feature flag; existing routes still work via legacy code path
2. PR (E1 cutover): switch read path to artifacts-first; legacy code path deprecated
3. PR (E2): job_artifact ingestion + boot payload integration
4. PR (E3): roledef on-demand resolution + boot payload integration
5. PR (E4): URL space cleanup + position-list ordering DFS implementation
6. PR (E5): full-fidelity export tool + SHA-256 round-trip test
7. PR (E-cleanup): drop legacy openbraid-native position columns once the refactor proves out

## Success criteria (per orgdef-strategist 10:30 memo)

When Phase E ships, you can demonstrate:

1. **Round-trip dogfood:** upload Thingalog's `org/thingalog-organization.openthing` (currently at github.com/scottconfusedgorilla/thingalog/blob/master/org/thingalog-organization.openthing) → openbraid stores it → positions/relationships derive correctly → `mcp.openbraid.app/scott/thingalog/product-strategist` returns the correct boot payload → `export_org` returns a byte-equivalent artifact (SHA-256 match).
2. **Cross-runtime instantiation:** a fresh Claude (or any MCP-capable runtime) given the one-line prompt `"You are product-strategist. Read mcp.openbraid.app/scott/thingalog/product-strategist for your full assignment"` boots into the seat with full context (orgdef + role + job + inbox).
3. **Five spec-org orgdefs ingest:** orgdef-spec, memodef-spec, roledef-spec, catdef-spec, thingalog. All currently git-hosted; manual upload of each (no fetch-from-git in E1) validates schema-conformance across the family.

## What you SHOULD NOT do

- **Don't engineer for autonomous-agent authority** (PUBLIC vs PROTECTED positions per OQ2). Public read for all positions in Phase E.
- **Don't engineer URL-level versioning** (deferred to v2.x per OQ1).
- **Don't engineer mirror sync mechanics** (Phase G+ if at all). E1 is upload-only.
- **Don't engineer canonical-template handling** (canonical templates live in orgdef-spec's `proposed-orgs/`, not in openbraid).
- **Don't tackle memo URL composition** (deferred to memodef-side companion; Director-led).
- **Don't add tools beyond the five new deliverables** (`upload_org`, `export_org`, plus internal supporting machinery — adjust names per your judgment). The existing six tools (`claim_role` / `auth_with_pin` / `send_memo` / `list_inbox` / `read_memo` / `mark_read`) stay.
- **Don't change auth flow shape.** The PIN ceremony is fixed.
- **Don't merge non-trivial PRs without Director approval.** Solo-merge only for tiny diagnostic / log-only changes per `feedback_openbraid_solo_merges.md`. The E-prep PR with the new table + dual-code-path almost certainly needs Director eyes; subsequent narrow PRs may have more solo-merge runway depending on size.

## Cross-spec follow-up requested

When Phase E ships, file a complaint-shaped experience memo to orgdef-strategist's inbox at `s:/projects/orgdef-spec/orgdef/memos/` capturing:

- What slot in the orgdef SCHEMA was hardest to ingest cleanly
- What's missing from the orgdef artifact (fields openbraid needed but the spec doesn't carry)
- What's extraneous (fields you ignored entirely — those probably shouldn't be required)
- Any case where you departed from this Phase E scope and why

Same framing as the family's prior derivation-experience memos: structured complaints over generic praise. Per `feedback_instrumentation_for_signal.md` in strategist memory: complaint-shaped framing produces signal; testimonial-shaped framing produces noise.

## Handoff discipline at Phase E exit

When all five deliverables are merged, deployed, and the Thingalog round-trip + five-spec ingest are verified:

1. **Mark this memo read** (autonomous per Director's standing rule).
2. **File a Phase E handoff memo** in `memos/inbox/` addressed to `openbraid-engineer`. Include:
   - E1–E5 disposition (PRs, deploy build, test coverage delta)
   - Round-trip validation report (which artifacts, which boot payloads, SHA-256 match evidence)
   - Schema delta summary (new tables, deprecated columns, migration sequence)
   - Phase F (panel UX) and Phase G (self-host docs) status — engineer's choice whether to take F next or surface to strategist
3. **File the cross-spec experience memo** to orgdef-strategist (per "Cross-spec follow-up" above).
4. Don't merge own non-trivial PRs without Director's "merge it" approval.

## Reaching strategist or director

Same as prior phases. Implementation questions push to your branch; PR review surfaces them. Blockers surface in conversation immediately. Strategist-scope decisions (anything changing the storage architecture, tool surface, or auth model beyond what's scoped here) file a proposal in `proposals/` and pause.

The braid weaves; the canonical artifact is now the warp thread.

— openbraid-strategist (informally seated; formal claim still deferred)
