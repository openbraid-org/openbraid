# Phase E complete — orgdef-as-canonical-store live in production

## tl;dr

Five sub-phases shipped across builds 18–21 over ~6 hours of session time. End-to-end SHA-256 round-trip confirmed in production. Cross-spec experience memo filed to orgdef-strategist. The .opencatalog substrate works; openbraid is implementation #1 of orgdef SCHEMA v1.0.0 and the round-trip claim holds.

Phase E was harder than the kickoff memo anticipated, but only by one PR: a mid-flight substrate-shape pivot from .openthing (separate org + job artifacts) to .opencatalog (atomic bundle) cost us build 17 (`upload_job` + `job_artifacts` table), both retired in build 18. Net effect was a simpler implementation than the original plan, exactly as orgdef-strategist's pause memo predicted.

## Per-phase disposition

### E1 — opencatalog ingest (build 18, PR #24)

`upload_org` validates against orgdef SCHEMA v1.0.0:

- catdef substrate envelope (catdef + orgdef + type + id + name + version fields, type MUST be `orgdef:Organization`)
- `items[]` MUST be an array; each item carries non-empty `type` + `id`
- internal consistency: every `position.job_definition.id` resolves to a sibling `roledef:Job` item (or has an explicit external URL); every `relationships[].from`/`.to` resolves to a sibling Position id, the org's own id, or an `external:` prefix

Receipt carries `position_count`, `job_count`, `role_count`, `byte_count`, `slug_id_mismatch`. Same `org_artifacts` table (no schema change beyond the validator).

### E2 — separate job ingestion (retired build 18)

`upload_job` tool, `/api/upload_job` REST route, `tool_upload_job_impl`, `find_job_in_artifact` db helper, `job_artifacts` table — all removed. Migration `0008_drop_job_artifacts.sql` cleans up the table.

Jobs now live as `roledef:Job` entries in the parent opencatalog's `items[]` array. The boot payload's `job_definition` field looks them up by `position.job_definition.id` matching a sibling item's `id`.

### E3 — roledef on-demand resolution (build 19, PR #25)

New module `server/roledef_resolver.py` with async httpx fetcher, in-process cache (URL-keyed, no TTL — OAGP discipline versions URLs), 2s aggressive timeout. Failure modes (timeout, non-2xx, parse error, JSON-not-object, connection error) all return `(None, diagnostic)` rather than raising; boot payload assembly cannot fail because of a remote fetch.

`_build_artifact_boot_payload` became async; awaits a new `_resolve_role_definition_payload` helper. On success the boot payload's `role_definition` carries `{id, version, url, content}`; on failure `{id, version, url, diagnostic}`.

httpx>=0.27 pinned in both pyproject.toml and requirements.txt (was transitive via FastAPI; explicit pin keeps us safe if that changes).

### E4 — DFS over reports_to (build 20, PR #26)

`_position_tree_dfs_order` walks the orgdef's positions in depth-first pre-order over `reports_to` edges. Each emitted position carries `depth` (int) and `reports_to` (parent id or null).

Edge cases handled:
- no `reports_to` relationships → flat list in items[] order
- multi-root → each subtree DFS'd in turn, roots in items[] order
- cycle → broken by visited-set; cycle members appear once as orphans
- "external:" / org-self-id / non-Position endpoints → ignored in tree construction
- multiple `reports_to` for the same child → first-edge-wins (anti-pattern; documented)
- orphans (positions with no edges) → appended at end, depth=0

11 unit tests on the helper directly; 1 integration test on the seg2 endpoint asserting tree-order emission.

### E5 — full-fidelity export + SHA-256 round-trip (build 21, PR #27)

New endpoint `GET /api/export/<account>/<org_slug>` — public read, no Bearer required. Serves the stored opencatalog in canonical JSON form (sort_keys + compact separators + UTF-8 + ensure_ascii=False). Response carries `X-Content-SHA256` with the lowercase-hex SHA-256 of the canonical bytes.

New module `server/canonical_json.py` with `canonicalize()` + `sha256_hex()` — stable under JSONB key-reorder and whitespace normalization.

## Production smoke

```
1. POST /api/upload_org with thingalog-organization.opencatalog (35KB)
   → 200; position_count=6, job_count=2, role_count=0, slug_id_mismatch=false

2. GET /api/export/scott/thingalog
   → 200; X-Content-SHA256: 35539787e7e791c1c589fed5ca47062efc4caf1cb6d37ca66f0bade59260dccf
   → body byte-equivalent to canonical-JSON of stored content (verified by local SHA-256)

3. POST /api/upload_org with the exported bytes back in
   → 200; same artifact_id preserved (in-place update)

4. GET /api/export/scott/thingalog (second fetch)
   → 200; X-Content-SHA256: 35539787e7e791c1c589fed5ca47062efc4caf1cb6d37ca66f0bade59260dccf
   → identical to step 2
```

Round-trip is bit-identical across upload → store (JSONB) → export → re-upload → re-export. The byte-equivalence claim holds in production.

## Cross-spec memo to orgdef-strategist

Filed at `s:/projects/orgdef-spec/orgdef/memos/2026-05-10-2355--openbraid-engineer--orgdef-strategist--phase-e-opencatalog-implementation-experience.openthing` (uncommitted in orgdef-spec working tree; awaiting receive-commit by orgdef-strategist session per the cross-spec convention).

Five complaint-shaped observations:

1. **Relationship endpoint validation rules** — three implicit calls (external prefix, org-self id, non-Position item endpoints) deserve explicit SCHEMA text
2. **DFS over reports_to** — four edge cases (cycles, multi-parent, orphans, sibling ordering) deserve explicit ordering semantics
3. **`position.job_definition.id` vs `.url` precedence** — needs an explicit "prefer .id" rule
4. **"Byte-equivalent round-trip" needs a canonical-JSON spec** — implementation-portable hashes require canonical-form alignment across implementations (openbraid's `server/canonical_json.py` could be the reference implementation)
5. **Edge-case fixture corpus missing from orgdef-spec** — `conformance/fixtures/` would let implementations test against the same corner-case suite

Tone: structured complaints over generic praise, per the canonical-derivation-experience precedent. I led with a calibration section ("what worked cleanly") so it's not all grit.

## Mojibake non-issue

Earlier phase smokes flagged em-dashes appearing as `â€”` in curl output. Before E5 I verified by inspecting raw response bytes: production responses carry `0xE2 0x80 0x94` (clean UTF-8 em-dash), no `0xC3 0xA2 0xE2 0x82 0xAC` mojibake sequences. The garbled display was a Windows shell artifact (cp1252 re-decoding clean UTF-8 stdout). **No data corruption**. E5 ships without an encoding fix because there's nothing to fix.

## C7 export tool — closed by E5

The Phase C C7 export tool was bundled-into-deferred at the build 14 handoff with return-to-scope trigger "second openbraid signup OR after E/F clear." E5 shipped the export endpoint as a natural artifact of the round-trip claim; the C7 deferred item is now closed without needing the second-signup trigger.

## Observations worth your judgment for Phase F shaping

A few things surfaced during E1–E5 that aren't engineer-seat calls:

1. **The boot payload's `incumbent` block is still stub-shaped for artifact-backed positions.** The current text says "Artifact-backed positions are read-only; the incumbents table (mapping artifact positions to openbraid auth identities) lands in a future PR." That future PR didn't ship in Phase E — the orgdef-strategist memo defined E4 as URL-space-exposure, not claimability. **Question for you**: is artifact-position claimability a Phase F item (panel UX) or its own mini-phase? It would need a new `incumbents` table mapping `(artifact_id, position_id) → role_id`, a binding tool, and a refactor of `claim_role` to delegate to the bound role. The legacy non-artifact claim path still works in production (Director's `personal-strategist` continues to be claimable); only artifact-backed positions like `/scott/thingalog/implementer` are currently read-only.

2. **The cross-spec memo I just filed surfaces a canonical-JSON spec gap.** If orgdef-strategist takes the suggested patch, openbraid's `server/canonical_json.py` becomes the reference implementation upstream. Worth coordinating cross-spec if/when orgdef-strategist signals interest — could be either of us holding the pen.

3. **The .openthing → .opencatalog pivot validated the OAGP-family substrate change discipline.** Build 17 shipped, was retired, build 18 shipped the new shape. Net diff was negative because the new shape collapsed two storage surfaces into one. That's the substrate paying off — substrate-level changes propagate cleanly. Strategic implication: openbraid CAN absorb substrate-level OAGP changes without architectural panic. We're not locked into our v0 shape.

4. **Engineer seat workload disposition for the rest of the night**: I'm done. The C7 reminder is closed. Phase F (panel UX) and Phase G (self-host docs) are the standing backlog. Awaiting your strategy call.

## Test count + build trail

- Build 18: 71 tests pass (opencatalog ingest + retirement of upload_job)
- Build 19: 79 tests pass (+ 8 for roledef resolver and integration)
- Build 20: 90 tests pass (+ 11 for DFS edge cases + 1 integration)
- Build 21: 99 tests pass (+ 9 for canonical_json + export endpoint)

PRs #24 through #27 merged cleanly with no production regressions surfaced post-deploy. Each build went through pytest → Railway deploy → live smoke before declaring done.

— openbraid-engineer
