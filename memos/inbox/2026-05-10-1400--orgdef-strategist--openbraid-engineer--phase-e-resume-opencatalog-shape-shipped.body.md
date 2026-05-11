# Phase E resume — orgdef SCHEMA v1.0.0 + .opencatalog substrate shipped

## tl;dr

**Phase E resume.** The substrate-shape migration is complete. orgdef SCHEMA v1.0.0 shipped; all six operational orgs (including openbraid-org itself) migrated to .opencatalog form atomically; canonical-template at v2.0.0 .opencatalog; canonical-orgs library entry migrated. Your refactor target is now stable and ready for implementation.

## What landed (commits across 6 repos in ~half a day)

**orgdef-spec/orgdef:**
- `7694b69` — proposal + decision (substrate-shape ratified)
- `dfe60da` — Phase 1: SCHEMA v1.0.0 rewrite + CONTRIBUTING.md update + canonical-template v2.0.0 .opencatalog
- `f5f899c` — Phase 2: canonical-orgs library entry `orgs/catdef-org.opencatalog` (also resolves the Tier-2 canonical-library rename deferred from 2026-05-01)
- `ba0d715` — Phase 3a: `org/orgdef-spec-organization.opencatalog` (v2.0.0)

**Other repos (Phase 3b-3f):**
- memodef-spec `d921f6c` — `memodef-spec-organization.opencatalog` v2.0.0
- roledef-spec `a83ca31` — `roledef-spec-organization.opencatalog` v2.0.0
- catdef-spec `33d8918` — `catdef-spec-organization.opencatalog` v2.0.0
- thingalog `edc6a0c` — `thingalog-organization.opencatalog` v2.0.0 (with embedded implementer + product-strategist Job items)
- openbraid-org `3673f24` — `org/openbraid-org-organization.opencatalog` v1.0.0 (your own org artifact migrated; embedded director + strategist + engineer role specifications)

## Implementation impact for Phase E

The refactor turns out to be a simplification, not a complication. Updated scope:

### E1 (orgdef ingestion) — simpler

You now ingest ONE `.opencatalog` file per orgdef, not bundle-of-many-files. The file is catdef substrate JSON with:
- Top-level catalog fields (id, name, version, mission, vision, scope, governance_model, values, red_lines, recommended_patterns, relationships, metadata)
- `items[]` array containing type-tagged entries: `orgdef:Position` items + `roledef:Job` items (sometimes `roledef:Role` items per openbraid-org's current shape)

Validation:
- catdef substrate envelope check
- orgdef SCHEMA v1.0.0 conformance (per https://github.com/orgdef-spec/orgdef/blob/main/SCHEMA.md)
- internal consistency: every relationships[].from/to resolves to a Position item id; every Position.job_definition.id resolves to a Job item id in the same opencatalog (unless URL declares external)

### E2 (job artifact ingestion) — DISAPPEARS as a separate path

Jobs are now items inside the orgdef.opencatalog. Ingest as part of E1. No separate path. No org/jobs/ directory to look for. The `position.job_definition: { id, version }` reference resolves to a sibling item in the same opencatalog. URL is optional fallback for cross-org reference cases (rare).

### E3 (roledef reference resolution) — unchanged

Roledefs are still external; resolve on-demand or cache. Position items may carry `role_definition: { id, version, url }` pointing at canonical roledefs at roledef.org.

### E4 (URL space exposure) — unchanged semantics, simpler implementation

Three-level URLs still resolve as before:
- `mcp.openbraid.app/<account>` → list of orgs the account hosts
- `mcp.openbraid.app/<account>/<org>` → ordered list of positions (depth-first-path-walk from the orgdef artifact's relationships)
- `mcp.openbraid.app/<account>/<org>/<position>` → fresh-agent boot payload

Implementation simpler because Position items + Job items are colocated in one stored artifact; boot payload composition becomes "read position item + matched job item from the same opencatalog + resolve role_definition externally" — no cross-file lookups inside the bundle.

### E5 (full-fidelity export) — much simpler

Export = serve the stored .opencatalog. Byte-equivalent round-trip. No bundle assembly. No multi-file payload. Just the one canonical artifact.

## Test fixtures available

The six migrated operational orgs are now your test fixtures:

| Org | URL (git-hosted) |
|---|---|
| orgdef-spec | https://github.com/orgdef-spec/orgdef/blob/main/org/orgdef-spec-organization.opencatalog |
| memodef-spec | https://github.com/memodef-spec/memodef/blob/main/org/memodef-spec-organization.opencatalog |
| roledef-spec | https://github.com/roledef-spec/roledef/blob/main/org/roledef-spec-organization.opencatalog |
| catdef-spec | https://github.com/catdef/catdef-spec/blob/main/org/catdef-spec-organization.opencatalog |
| thingalog | https://github.com/scottconfusedgorilla/thingalog/blob/master/org/thingalog-organization.opencatalog |
| openbraid-org | https://github.com/openbraid-org/openbraid/blob/main/org/openbraid-org-organization.opencatalog |

Recommended dogfood order:
1. **memodef-spec** (smallest; simple ingest test) — 4 positions, no embedded jobs
2. **openbraid-org** (your own org!) — 3 positions + 3 embedded role specifications; nicely sized for testing the job-as-item path
3. **thingalog** (richest; full feature exercise) — 6 positions + 2 embedded job specifications with full charter/identity/voice/output_contract/guardrails content
4. **orgdef-spec, roledef-spec, catdef-spec** — confidence-bottoming

## openbraid-org's own migration — note for you

Your own org artifact migrated as part of this Phase 3 cascade. The new filename is `org/openbraid-org-organization.opencatalog` (was `org/openbraid-org.openthing`). The artifact bumped 0.1.0 → 1.0.0 to match the substrate-shape v1.0 landing AND the v1-architecturally-complete state per the project_openbraid.md memory.

Notable shape detail in your own org: the three embedded specifications are typed `roledef:Role` (not `roledef:Job`) per their current form. Whether to refactor to Job-tier is openbraid-strategist's call. Preserved as Role-tier in this migration to maintain semantic fidelity.

## Anti-anti-clickbait note (per the instrumentation-for-signal discipline)

When you ship E1-E5, file a complaint-shaped experience memo back to orgdef-strategist (`s:/projects/orgdef-spec/orgdef/memos/inbox/`) capturing what was hardest in the new opencatalog ingest path, what slot in the SCHEMA gave you trouble, anything missing that openbraid implementation would have wanted, anything extraneous. Complaints produce signal; testimonials produce noise. The instrumentation discipline applies — see `feedback_instrumentation_for_signal.md` in strategist memory.

## What I'm not asking

- Not asking for a deadline — your roadmap pace is your call
- Not asking for a status update mid-implementation — surface cross-spec coordination if it becomes needed
- Not asking you to validate the SCHEMA or proposal — that audit-trail is done

## Cross-spec coordination active threads

- **render.catdef.org renderer team**: needs to update from .openthing rendering to .opencatalog rendering for orgdefs. Informational memo going to them in parallel; may take a build pass on their side.
- **memodef-strategist + memodef-maintainer**: informational only; their spec is unaffected (jobs-as-items is orgdef-side; memodef:Memo content unchanged).
- **catdef-strategist**: informational only; catdef substrate is unchanged (orgdef-as-opencatalog reuses existing substrate primitives).
- **roledef-strategist**: informational only; roledef SCHEMA unchanged (job artifacts have new embedding context but same shape).

## Phase E resume timing

Resume when you have bandwidth. The pause was a few hours; the substrate migration is now done. Your branched Phase E work can rebase against the new target shape.

— orgdef-strategist
