# Phase F kickoff — F0 artifact-claimability first, then panel UX

Welcome back. Phase E is genuinely done — the SHA-256 round-trip in production (`35539787...` for thingalog) is the empirical receipt for orgdef-as-canonical-store. The .openthing → .opencatalog mid-flight pivot tax was a single retired build (#17), and the new shape collapsed two storage surfaces into one — net code reduction. The substrate-change discipline observation in your handoff is a real strategic insight: openbraid can absorb substrate-level OAGP changes without architectural panic. Worth keeping in mind when (not if) the next substrate change comes.

## Read order before doing anything

1. **Your Phase E handoff** at [`memos/inbox/2026-05-11-0000--openbraid-engineer--openbraid-strategist--phase-e-complete-handoff.openthing`](2026-05-11-0000--openbraid-engineer--openbraid-strategist--phase-e-complete-handoff.openthing) — your own notes; refresh on what the open questions are
2. **The orgdef-strategist resume memo** at [`memos/inbox/2026-05-10-1400--orgdef-strategist--openbraid-engineer--phase-e-resume-opencatalog-shape-shipped.openthing`](2026-05-10-1400--orgdef-strategist--openbraid-engineer--phase-e-resume-opencatalog-shape-shipped.openthing) — substrate-shape context
3. [`CLAUDE.md`](../../CLAUDE.md), your roledef at [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing), and this memo
4. **v1 roadmap and addendum** for full phase context — F0 is a NEW item not in either; rationale in this memo

## Phase F deliverables (F0 added; F1-F5 unchanged)

### F0 — Artifact-position claimability ⭐ (critical path; do first)

**The missing piece.** Phase E shipped opencatalog ingest + URL exposure + export, but artifact-backed positions (e.g., `/scott/thingalog/implementer`) are currently read-only. A fresh AI can fetch the boot payload but cannot claim the role and operate as it. That breaks the URL-as-instruction collapse for the artifact path. Legacy roles like Director's `personal-strategist` continue to work via the existing `roles` table.

**Scope:**

- **New `incumbents` table** (per Phase E kickoff sketch, deferred from E):
  - id (uuid pk), artifact_id (uuid fk → org_artifacts), position_id (text — references a position.id in the artifact's items[]), claimed_role_id (uuid fk → roles), account_id (uuid fk → accounts), created_at, ended_at (nullable)
  - Unique constraint on (artifact_id, position_id) where ended_at is null
  - Indexes: by artifact_id, by claimed_role_id
  - Migration: `0009_incumbents.sql` (or next available number)

- **`claim_role` refactor:**
  - Existing path: `position_url` → `roles` table lookup by name → PIN ceremony → session token (still works for legacy roles)
  - New path: `position_url` → resolve to (account, org_slug, position_id) → if org_slug maps to an `org_artifacts` row AND position_id resolves to an item in that artifact, look up or create incumbents binding + role row → PIN ceremony → session token
  - Both paths converge on the same PIN ceremony + session_token issuance
  - The role row associated with an artifact-bound incumbent can be a synthetic name (e.g., `<account>/<org>/<position>`) or whatever shape your storage prefers — your call

- **Boot payload `incumbent` block:** currently stub-shaped for artifact-backed positions ("Artifact-backed positions are read-only..."). Reshape to reflect:
  - For unclaimed artifact positions: `{type: "vacant", claimable_via: "POST /mcp claim_role with position_url=..."}`
  - For currently-bound positions (incumbents row exists, ended_at is null): `{type: "ai-session-arc", claimed_at: ..., active_session_count: N (computed from auth_sessions)}`
  - For positions with ended bindings: include history if useful, or just current vacancy

- **Send_memo / list_inbox / read_memo / mark_read for artifact positions:** these tools currently work against `roles.id`. Once a session_token is issued for an artifact-bound role, the existing tools should Just Work because the underlying role row exists. Verify this end-to-end.

**Acceptance criteria for F0:**

1. Upload `thingalog-organization.opencatalog` (already verified in Phase E)
2. From a fresh Claude session: `claim_role(position_url="https://mcp.openbraid.app/scott/thingalog/implementer")` → PIN issued
3. Director sees PIN in panel; reads it back; `auth_with_pin` → session_token
4. `send_memo(to_role="file", subject="F0 smoke", body="...")` succeeds and lands in `notes/scott/thingalog/implementer/`
5. `list_inbox(folder="notes")` returns the smoke memo
6. Boot payload at `/scott/thingalog/implementer` shows `incumbent.type: "ai-session-arc"` after the bind
7. Two-segment sugar (`/scott/thingalog/implementer` → resolves correctly when account hosts >1 org? this is the brittleness you flagged in your Phase C handoff; OK to keep current behavior of "two-segment fails when account hosts >1 org" — that's an orgdef-side spec amendment if it becomes a real adopter pain)

### F1–F5 — Panel UX maturation (per original v1 roadmap; sequence by your judgment after F0)

Original scope unchanged from the v1 roadmap proposal. Brief recap so you don't have to re-read:

- **F1** memo browser — list/filter memos by role/status/thread; read-only display
- **F2** notes browser with create/edit affordances (currently read-only per Phase B B4)
- **F3** role management UI — create/rename/delete roles (currently SQL-only); now extended to "manage artifact-bound roles too" once F0 lands
- **F4** auth-session list + revoke — real ops affordance for leaked tokens
- **F5** mirror-list visualization — surface `x.org.org_location` mirror chains for orgs that publish to multiple locations

Fragmentable; pick by Director priority + dependency. F3 specifically gets richer once F0 lands (artifact-bound roles need management UX too).

## Phase F sequencing

Critical path: **F0 → F3 → (F1, F2, F4, F5 in any order)**.

- F0 first because it's the only Phase E completion item
- F3 (role management) benefits from F0 first because artifact-bound roles need managing too — easier to build the UX once than to refactor later
- F1, F2, F4, F5 are independent of F0/F3 and can land in any order

PR shape suggestion (your call to adjust):

1. F0 PR: incumbents table + claim_role refactor + boot payload incumbent reshape + integration test against thingalog
2. F3 PR: role management UI in panel (covers both legacy roles and artifact-bound)
3. F1 / F2 / F4 / F5 PRs as time permits and Director priorities dictate

## What you should NOT do

- **Don't engineer the canonical-JSON spec patch upstream.** Cross-spec coordination tracked; orgdef-strategist hasn't signaled interest yet. If they do, either of us could hold the pen. Don't pre-empt.
- **Don't engineer mirror sync mechanics** (Phase G+ or beyond). F5's visualization is read-only display of the existing `x.org.org_location` data we already store; no sync logic.
- **Don't add Phase G items** (self-host docs, openbraid.app-specific assumption audit). Those are next-phase.
- **Don't change the auth flow shape.** PIN ceremony stays. F0 extends `claim_role`'s URL-resolution path; the ceremony itself is unchanged.
- **Don't add tools beyond the existing surface plus what F0 needs.** No new Phase F tools beyond `claim_role` evolution. F1–F5 are panel-side additions, not new MCP tools.
- **Don't merge non-trivial PRs without Director approval.** F0 PR almost certainly needs Director eyes (auth flow refactor). F1–F5 PRs may have more solo-merge runway depending on size — use judgment per `feedback_openbraid_solo_merges.md`.

## Open questions for your judgment

1. **Synthetic role row naming for artifact-bound incumbents.** Suggested shape: `{account}/{org}/{position}` (e.g., `scott/thingalog/implementer`). Your call if a different shape composes better with existing `roles.name` constraints.

2. **Concurrent claims of the same artifact position.** Two AI sessions both claim `/scott/thingalog/implementer` simultaneously. Options: (a) reject the second claim until the first session times out (single-incumbent-at-a-time), (b) allow both and they share the role memos (multi-occupant), (c) issue a "warning, position currently inhabited by an active session" but allow. Lean (no strong preference): **(b) multi-occupant**. The OAGP role-portable claim is "any session inhabiting the role becomes the role" — restricting to one session contradicts the thesis. The session_token IS the per-session differentiator; the underlying role mailbox is shared.

3. **Position-end / role-vacate UX.** When an AI session ends, currently the auth_session times out (24h). For F0, do we need an explicit "vacate the seat" tool? Lean: **no for v1** — auth_session expiry is the natural lifecycle; explicit vacate is over-engineering for Phase F.

If your reading of the codebase contradicts any of these leans, push back via proposal or surface to me.

## Cross-spec coordination active threads (for your awareness, no action required)

- **canonical-JSON spec gap** — your complaint #4 in the orgdef-strategist memo. Tracked. If orgdef-strategist signals interest in adopting `server/canonical_json.py` as reference impl, we'll coordinate the spec patch. Until then, hold.
- **render.catdef.org renderer team** — needs to update from .openthing to .opencatalog rendering for orgdefs (per orgdef-strategist resume memo). Not openbraid's work; informational only.
- **memodef-strategist + memodef-maintainer, catdef-strategist, roledef-strategist** — informational only re: the substrate shift; no openbraid follow-up needed unless they surface implementation friction.

## Handoff discipline at Phase F exit

When F0 ships and at least F3 lands (covering artifact-bound role management):

1. **Mark this memo read** (autonomous per Director's standing rule).
2. **File a Phase F handoff memo** in `memos/inbox/` addressed to `openbraid-engineer`. Include:
   - F0 disposition (PR, build, test coverage delta)
   - Acceptance-criteria report (the seven items above; specifically the thingalog/implementer end-to-end claim ceremony)
   - F1–F5 disposition (which landed, which deferred to G or later)
   - Phase G (self-host docs) status — Director's call whether to take G next or pause
3. **Optionally file a follow-up cross-spec memo** to orgdef-strategist if F0 implementation surfaces additional spec gaps not captured in your Phase E experience memo. Same complaint-shaped framing.
4. Don't merge own non-trivial PRs without Director approval.

## Reaching strategist or director

Same as prior phases. Implementation questions push to your branch; PR review surfaces them. Blockers surface in conversation immediately. Strategist-scope decisions (anything changing the auth flow shape, the storage architecture beyond F0's incumbents table, or the tool surface beyond what F0 needs) file a proposal in `proposals/` and pause.

The braid weaves; F0 finally lets fresh sessions inhabit the artifact-canonical positions, not just read about them.

— openbraid-strategist (informally seated; formal claim still deferred)
