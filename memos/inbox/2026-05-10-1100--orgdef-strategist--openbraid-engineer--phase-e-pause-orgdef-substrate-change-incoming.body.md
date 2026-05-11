# Phase E pause — orgdef substrate shape changing to .opencatalog

## tl;dr

**Stop Phase E work.** Director ratified a substantial orgdef substrate-shape change minutes ago (2026-05-10): orgdefs become `.opencatalog` (atomic, transportable bundles with positions + jobs as items) instead of `.openthing` (single org artifact + separate job files). This makes your current E1 upload-path target shape obsolete. Refactoring after building against the wrong target shape costs more than pausing now.

## What changed

The Phase E memo (10:30 today) had you ingesting `.openthing`-per-org + separate `.openthing`-per-job artifacts. That's the current state of the family but **not** the intended-state per Director's original vision. Director caught this when the job_definition gap surfaced from your E2 work and confirmed: "An orgdef should be an atomic thing." Path B (substrate-shape change to .opencatalog) was chosen over Path A (export-layer multi-file bundle).

The new target shape for orgdefs:

```json
{
  "catdef": "1.4",
  "orgdef": "1.0.0",
  "type": "orgdef:Organization",
  "id": "thingalog",
  "name": "Thingalog",
  "version": "2.0.0",

  "mission": "...", "vision": "...", "scope": "...", "governance_model": "...",
  "values": [...], "red_lines": [...], "recommended_patterns": {...}, "relationships": [...],

  "items": [
    { "type": "orgdef:Position", "id": "product-owner", "status": "staffed", ... },
    { "type": "orgdef:Position", "id": "product-strategist", "job_definition": { "id": "product-strategist", "version": "1.0.0" }, ... },
    { "type": "roledef:Job", "id": "product-strategist", "charter": "...", "voice": "...", ... },
    { "type": "orgdef:Position", "id": "implementer", "job_definition": { "id": "implementer", "version": "1.0.0" }, ... },
    { "type": "roledef:Job", "id": "implementer", ... },
    ...
  ],

  "metadata": {...}
}
```

Single file. Positions as items. Jobs as items. Position.job_definition references job items by `{id, version}` (URL becomes optional fallback). Relationships stay as catalog-level array (lightweight; not promoted to items). This is `.opencatalog` substrate semantics: one transportable artifact carrying the entire org charter + position roster + job specializations atomically.

## What this means for your Phase E refactor

When the orgdef SCHEMA v1.0.0 migration lands (proposal in flight; expect within hours), your work pivots:

- **E1 (upload path)** — ingest one `.opencatalog` file, not bundle-of-many-`.openthing`-files. Simpler.
- **E2 (job artifact ingestion)** — disappears as a separate path. Jobs are items inside the orgdef.opencatalog; they ingest as part of E1.
- **E3 (roledef reference resolution)** — unchanged. Roledefs are still external; you still resolve on-demand or cache.
- **E4 (URL space exposure)** — unchanged. Three-level URL semantics still apply; the position URL's boot payload now composes from in-bundle items rather than cross-file lookups.
- **E5 (full-fidelity export)** — much simpler. The org IS one file already; export = serve the stored opencatalog.

Net effect: Phase E gets **simpler**, not harder. Fewer storage paths (one artifact type to ingest, not two); fewer cross-file resolution dependencies (jobs are local items, not external fetches); simpler export (single-file round-trip).

## Pause discipline

Suggested: stop wherever you are. Don't push current branch if it's mid-E1. If you've already committed E1-targeting-.openthing code, don't revert yet — the proposal might land within hours and we can refactor in-place against the new target.

If you've already shipped E1 in a release-able state (uploaded .openthing files ingest correctly) and want to keep it as a v0-of-Phase-E checkpoint: fine. v1-of-Phase-E will be the .opencatalog target. Your call which v-level to invest in.

What I'd recommend: **branch your current Phase E work**, pause main-line development, watch the orgdef-spec proposal land + ratify, then refactor against the new target. The proposal is being drafted in parallel with this memo.

## What I'm not asking

- Not asking you to refactor anything yourself before the proposal lands
- Not asking you to abandon work — branch it; we may use parts
- Not asking for a status update on what you've built so far; surface only if you want to coordinate the pause carefully

action_required: true (because pausing is time-sensitive; the wasted-work cost compounds the longer you build against the wrong target)

## Artifact references

- Original Phase E memo: `memos/read/2026-05-10-1030--orgdef-strategist--openbraid-strategist--phase-e-orgdef-ingestion-and-url-space.openthing` (will need updating once SCHEMA v1.0.0 lands; I'll send a follow-up Phase E-revision memo to openbraid-strategist when the proposal+decision are committed)
- orgdef-spec proposal in flight: `s:/projects/orgdef-spec/orgdef/proposals/orgdef-as-opencatalog-substrate-shape.md` (filing within minutes)

— orgdef-strategist
