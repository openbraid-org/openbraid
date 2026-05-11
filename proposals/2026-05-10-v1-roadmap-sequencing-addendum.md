# Addendum to v1 roadmap sequencing — Phase E shape evolution

**Disposition:** Director-ratified in design conversation 2026-05-10 evening.
**Filed:** 2026-05-10 by openbraid-strategist
**Supersedes:** Phase E + Phase F + C7 sections of the original [v1 roadmap proposal](2026-05-10-v1-roadmap-sequencing.md). Phases A, B, C, D dispositions in the original remain accurate.

## Summary of changes

The original v1 roadmap put self-host docs at Phase E and panel UX at Phase F. After the cross-vendor demo (2026-05-10 evening) and the orgdef-strategist's 10:30 memo introducing the missing canonical-store principle, the phase ordering and Phase E content both changed:

| Phase | Original (2026-05-10 morning) | Revised (2026-05-10 evening) |
|---|---|---|
| E | Self-host + open-source readiness | **Orgdef ingestion as canonical store (refactor)** |
| F | Panel UX maturation | Panel UX maturation (unchanged) |
| G | (n/a) | Self-host + open-source readiness (was original E) |
| C7 | Deferred-in-scope behind C/D/E/F | **Collapsed into new Phase E as E5** |
| D2 | Deferred until empirical demand | Unchanged |

## Why Phase E became "orgdef ingestion"

The orgdef-strategist's [10:00 memo](../memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing) established the canonical OAGP position addressing scheme. The companion [10:30 memo](../memos/inbox/2026-05-10-1030--orgdef-strategist--openbraid-strategist--phase-e-orgdef-ingestion-and-url-space.openthing) made an implicit principle explicit:

> openbraid is the HOSTING layer; orgdef.openthing artifacts are the CONTENT layer. openbraid INGESTS catdef-substrate orgdef.openthing artifacts as the source of truth, stores them in canonical JSON form, exposes them via the MCP URL space, and provides full-fidelity export to round-trip the same artifact back out.

Phases A–D shipped with an openbraid-native data model (positions/roles as native Postgres rows; no orgdef.openthing artifact in the database). The 10:30 memo's principle requires inverting that — making the orgdef.openthing JSON the canonical store. This is a refactor, not an additive scope.

Five deliverables, all per the 10:30 memo:
- **E1** — orgdef.openthing ingestion (upload path; fetch-from-git deferred)
- **E2** — job artifact ingestion (part of the org bundle)
- **E3** — roledef reference resolution (external; on-demand for v1)
- **E4** — URL space exposure (per the 10:00 memo's three-level semantics)
- **E5** — full-fidelity export (was C7)

## Why C7 collapsed into E5

The 10:30 memo frames full-fidelity export as MUST: *"Without portable export, openbraid would be lock-in."* The 2026-05-10 morning deferral of C7 (lower priority until second openbraid signup) was an interim posture; the orgdef-strategist memo dissolves the empirical-trigger and makes export part of getting Phase E architecturally correct. C7-as-deferred-item no longer exists; C7-functionality returns as E5-mandatory.

## Storage architecture choice — Postgres JSONB over graph DB

Director-ratified Postgres JSONB over Neo4j 2026-05-10 evening. Rationale:

- The canonical store IS the JSON artifact. Relationships live inside the artifact as fields. Wherever we store, we store JSON.
- Boot payload DFS over <20-position artifacts is sub-millisecond in code (BFI wins).
- Adding Neo4j doubles operational complexity (especially for self-host story in Phase G) without addressing any actual query bottleneck.
- JSONB indexing in Postgres handles the "query INTO artifacts" cases that might otherwise tempt graph DB adoption (e.g., "find all positions of type strategist across all orgs in account X").

Where Neo4j would change the calculus: 100K+ orgs with cross-org analytics workloads doing recursive pattern-matching queries. Not openbraid's current shape.

## Phase E sequencing (per 10:30 memo's recommendation, sound)

Critical path: E1 → E2 → E4 → E5. E3 in parallel; lower priority for first ship.

Suggested PR shape:
1. E0-prep: introduce `org_artifacts` JSONB table + dual-code-path
2. E1 cutover: switch read path to artifacts-first
3. E2: job artifact ingestion
4. E3: roledef on-demand resolution
5. E4: URL space cleanup + DFS implementation
6. E5: full-fidelity export tool + SHA-256 round-trip test
7. E-cleanup: drop legacy openbraid-native position columns

## Phase F unchanged; Phase G is the new self-host phase

Phase F (panel UX maturation) keeps its scope from the original v1 roadmap: F1 memo browser, F2 notes browser create/edit, F3 role management UI, F4 auth-session list+revoke, F5 mirror-list visualization. Fragmentable; can run alongside or after Phase E.

Phase G (self-host + open-source readiness) is what was originally Phase E. Three items unchanged:
- G1 docker-compose + env-var inventory + migration bootstrap + OAuth provider walkthrough
- G2 audit for openbraid.app-specific assumptions (engineer flagged `MCP_ORIGIN` auto-derivation in panel.py)
- G3 reference use cases in docs (`mcp.firstchurch.org`, `org.acmecorp.com`)

The original sub-sequencing (G2 audit before G1 docs) still applies.

## Director decisions (revised)

| # | Decision | Disposition |
|---|---|---|
| 1 | Phase E becomes orgdef-ingestion refactor | Ratified 2026-05-10 evening |
| 2 | C7 collapses into E5 | Ratified 2026-05-10 evening |
| 3 | Postgres JSONB over Neo4j for canonical artifact storage | Ratified 2026-05-10 evening |
| 4 | Refactor framing in engineer kickoff (not "additive") | Ratified 2026-05-10 evening |
| 5 | Phase F unchanged; Phase G = original Phase E | Ratified 2026-05-10 evening |

## Cross-spec follow-up unchanged

Engineer files complaint-shaped experience memo to orgdef-strategist when Phase E ships, capturing what slot was hardest to ingest, what's missing/extraneous from the orgdef SCHEMA, and any departures from Phase E scope.

## Cross-references

- Original v1 roadmap: [`proposals/2026-05-10-v1-roadmap-sequencing.md`](2026-05-10-v1-roadmap-sequencing.md)
- orgdef-strategist 10:00 memo: [`memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing`](../memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing)
- orgdef-strategist 10:30 memo: [`memos/inbox/2026-05-10-1030--orgdef-strategist--openbraid-strategist--phase-e-orgdef-ingestion-and-url-space.openthing`](../memos/inbox/2026-05-10-1030--orgdef-strategist--openbraid-strategist--phase-e-orgdef-ingestion-and-url-space.openthing)
- Phase E kickoff memo: [`memos/inbox/2026-05-10-2100--openbraid-strategist--openbraid-engineer--phase-e-kickoff-orgdef-as-source-of-truth.openthing`](../memos/inbox/2026-05-10-2100--openbraid-strategist--openbraid-engineer--phase-e-kickoff-orgdef-as-source-of-truth.openthing)
