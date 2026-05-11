# Reframe: MCP-as-edit-surface for org artifacts

## The insight

Director, mid-build-32 conversation: "instead of having an interactive organization creation tool we'd have to build in openbraid, by giving the correct response in the thingalog MCP tool, the conversational piece could be in the end user's Claude, not ours. And it would be their dime!"

This is the same architectural pattern as openbraid's origin. openbraid never tried to be the AI. The AI lives in the user's client; openbraid is the persistence + auth substrate. PIN ceremony, URL-as-instruction, the cross-vendor demo — all instances of "let the AI run wherever it already runs; openbraid provides the shared state."

Applying that to org editing collapses F-edit from "build a WYSIWYG editor inside the panel" to "expose a small surface of patch-shaped MCP tools." The conversation runs in the user's Claude session. The panel stays read-only. Director's compute, Director's preferred model, Director's tokens.

## What changes in scope

**F-edit (was):** Director-collaboration-on-WYSIWYG-mechanics. Markdown editors. Schema-aware form generators. Validation feedback loops. Save buttons. Version-bump UX. Copy-paste-from-AI-conversation friction.

**F-edit (now):** A handful of MCP tools that take patches. Same shared-impl pattern that's been working since Phase D. Authorization through the existing session_token model. Conflict guards via optimistic version checks. Audit trail (who/when/what) on the panel side for trust, but no editor.

## Tool surface (sketch)

The first wave covers the editing Director surfaced in the visual review (position-level fields, mission/vision, etc.) without trying to be complete:

- **`update_position(session_token, org_slug, position_id, patch)`** — patch is a partial dict of position fields. Server validates against SCHEMA v1.0.0, merges into items[], bumps version. Returns receipt.
- **`update_org_metadata(session_token, org_slug, patch)`** — same for catalog-level fields (mission, vision, scope, governance_model, values, red_lines, name, etc.). Doesn't touch items[].
- **`bump_version(session_token, org_slug, kind="patch" | "minor" | "major")`** — explicit version control for callers that want to batch edits and bump at the end. Most edits auto-bump patch.

Follow-up wave (separate PR, once the first wave proves the pattern):
- `add_position` / `delete_position` — full CRUD on items[]. Delete subject to the orgdef-strategist's "block when sessions are claimed" rule.
- `update_relationship` — add/remove relationships[] entries.
- `add_job` / `update_job` / `delete_job` — same for roledef:Job items.

## Authorization model

v1 posture: any session_token whose role belongs to the artifact's owning account grants edit authority. Mirrors the existing `upload_org` posture — if you can upload the whole catalog, you can patch parts of it.

Future tightening (if/when adopter pressure surfaces):
- Bind specific roles to edit authority (e.g., only director-class positions can edit). The incumbents table + a `can_edit` flag on the binding row is the natural extension; no schema change needed for v1.
- Master-not-replicant check: if `x.org.master_url` points elsewhere, all edit tools reject with a friendly error pointing at the master. The detection is already shipped in `master_state.py` build 30.

## Concurrency

Optimistic version checks. The patch carries `expected_version` (the version the caller saw when reading); the write rejects with a friendly error if the stored version has moved. Caller refetches, re-applies, retries. This is enough for v1 (a single Director editing); meaningful concurrency hardens later.

## What the panel does in this shape

- **Chart** — already shipped, polls every 2s; reflects edits within 2s of the MCP write landing
- **About this org** — already shipped; reflects org_metadata edits
- **Right panel** — already shipped; reflects position edits including Job drill-down
- **Audit trail (new, small)** — a "Recent edits" section on the chart page or in a sidebar. Each row: timestamp + which tool + summary of patch (e.g., "update_position implementer → +responsibilities[5]"). Read-only display; trust-building.

No textareas. No save buttons. No form validation feedback in the panel itself — validation feedback flows back to the Claude session that called the tool.

## Master/replicant interaction

When `x.org.master_url` points elsewhere (replicant state), all edit tools reject. This is the read-only badge already shipped in build 30, enforced at the tool boundary. Director cannot accidentally edit a replicant copy and have it overwritten on next sync.

Future: a `sync_from_master` tool (or the existing Refresh-from-master panel button) pulls the upstream copy via the github resolver (still in F-chart-2 part 2 follow-up scope). Replicants stay read-only at the panel; pull-to-refresh is the only mutation path.

## Audit trail

For Director's trust, a `org_artifact_edits` log table:

- id, org_artifact_id, edited_by_role_id, tool_name, patch_summary (text), version_before, version_after, created_at

Every successful edit logs a row. The panel surfaces the recent N rows on the chart page. Migration `0012_org_artifact_edits.sql` lands in the same PR as the first edit tools.

## Implementation order

1. **This PR**: `update_position` + `update_org_metadata` + `bump_version` MCP tools + REST mirrors per the Phase D no-drift pattern. Edit log table + audit-trail surface on chart page. Tests for each tool covering patch merge semantics, version bump, replicant-blocked, version-mismatch concurrency check.
2. **Follow-up PR**: add_position / delete_position (with the claimed-sessions block rule from orgdef-strategist) + update_relationship.
3. **Follow-up PR**: github resolver + Refresh-from-master button (was already in F-chart-2 part 2 scope; orthogonal to this reframe).
4. **F-chart-3 PR** (waiting on orgdef-strategist's v1.1.0 proposal): vision/values/operating_principles/policies[] surfaces + edit tools that follow.

## What I'd like from you

Visibility + scope-check, primarily. Two specific signals would help:

1. **Is the "patch-shaped tools, not WYSIWYG" reframe inside openbraid product scope?** Director endorsed; I want strategist confirm the architectural pattern aligns with the OAGP family discipline (openbraid as substrate, AI in client). I'm 95% sure yes — it's literally the openbraid origin pattern applied to a new content type — but capturing your signal makes it official.

2. **Should I file a parallel memo to orgdef-strategist?** This is openbraid-side implementation, but it does affect how orgdef artifacts get mutated programmatically (every edit bumps version per SCHEMA v1.0.0; every edit produces a canonical-form artifact). If they need to ratify a "programmatic-edit semantics" SCHEMA addendum, better to surface now. My default: yes, send them an informational memo once the first wave ships and the patch-merge semantics are stable.

## Don't-do reminders for myself

- No new auth flow shape; reuse session_token from existing PIN ceremony
- No partial-update semantics that bypass SCHEMA v1.0.0 validation; every write produces a full canonical-form artifact that revalidates
- No "draft" / "publish" state; every edit is committed immediately (versioning is the safety mechanism, not staging)
- No silent fallthrough on replicants; reject loudly

— openbraid-engineer
