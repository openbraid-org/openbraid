# Phase F mid-handoff — F0, F3, F4 shipped; F1/F2/F5 + Phase G outstanding

## tl;dr

Three of six Phase F sub-phases live in production. F0 (the Phase E completion item) shipped with the full thingalog/implementer claim ceremony validated end-to-end. F3 and F4 turned the panel from a static role-list + separate PIN-poller into a unified live control surface. F1 (memo browser), F2 (notes browser create/edit), F5 (mirror-list viz) outstanding; Phase G untouched. Director consulting openbraid-strategist on sequencing.

## Per-sub-phase disposition

### F0 — artifact-position claimability (live)

**Phase E completion item.** Closes the URL-as-instruction gap that build 17 left open: artifact-backed position URLs (e.g. `/scott/thingalog/implementer`) are now claimable through the standard PIN ceremony. First claim creates a synthetic role row + incumbents binding; subsequent claims reuse it (multi-occupant via auth_sessions on the shared role per Director's lean).

- **PR #28 build 22** — initial F0 implementation
- **PR #29 build 23 (hotfix)** — `roles.org_id` was NOT NULL from migration 0004; artifact-bound roles have no legacy `orgs` row so insert failed with 23502. Migration 0011 drops NOT NULL.
- **PR #32 build 26 (hotfix)** — missing `artifacts_for_account` import in panel.py caused 500 on /panel/roles after F3 follow-up; import fix + new test_panel_smoke.py to gate this class of regression.

**Schema migrations applied:**
- `migrations/0009_incumbents.sql` — bind (org_artifact_id, position_id) → claimed_role_id
- `migrations/0010_canonical_role_names.sql` — rewrite all legacy role.name from short form (`personal-strategist`) to canonical URL form (`scott/personal/personal-strategist`)
- `migrations/0011_roles_org_id_nullable.sql` — drop NOT NULL on roles.org_id

**Synthetic role name convention** (Director ratified 2026-05-11): `<account_handle>/<org_slug>/<position_id>` (e.g. `scott/thingalog/implementer`). Future-proofs for cross-account claim flows where two users may oversee different roles in the same org. Affected lookups: `position_by_name` joins through orgs+accounts to compute canonical name; `send_memo` recipient lookup tries exact then suffix-match.

**Acceptance criteria (per kickoff memo) — 7/7 met:**

1. ✅ Upload `thingalog-organization.opencatalog` (verified in Phase E)
2. ✅ `claim_role(position_url="https://mcp.openbraid.app/scott/thingalog/implementer")` → PIN issued
3. ✅ Director read PIN from panel; `auth_with_pin` → session_token; role: `scott/thingalog/implementer`
4. ✅ `send_memo(to_role="file", subject="F0 smoke", body="...")` succeeded; memo `7492a695-...` filed as `kind: "note"`
5. ✅ `list_inbox(folder="notes")` returned the smoke memo with `from_position: scott/thingalog/implementer`
6. ✅ Boot payload at `/scott/thingalog/implementer` shows `incumbent.type: "ai-session-arc"`, `role_id`, `active_session_count: 1`, `notes_count: 1`
7. ✅ Two-segment sugar N/A (used 3-segment URL throughout the smoke)

### F3 — role management UI (live)

**Tight scope per Director's pre-implementation feedback:** display bug fixes from migration 0010, artifact-bound vs legacy distinction, soft-delete for legacy roles. Rename and vacate deferred per "just close the agent" lean.

- **PR #30 build 24** — initial F3
- **PR #31 build 25 (follow-up)** — Director surfaced chicken-and-egg gap: artifact-bound roles only appeared after first claim, but Director needed canonical URL BEFORE first claim. Added "Available positions" section listing all orgdef:Position items in uploaded opencatalogs without a live incumbents binding, each with a "Copy claim prompt" affordance.

**Changes:**
- Canonical URL bug fix (was doubling handle/org post-migration 0010)
- Per-role badge: artifact (gold-bordered) vs legacy (muted)
- Short-form display `<org>/<position>` prominent; full canonical URL muted below
- POST /panel/roles/{role_id}/delete soft-deletes legacy roles; rejects artifact-bound with friendly error directing to future vacate affordance
- Vacant artifact positions enumerated per artifact's items[] filtered by type=="orgdef:Position", excluding live-bound positions

### F4 — consolidated control panel (live)

**Director's re-scoping call:** the spec'd F4 was just "auth-session list + revoke." Director consolidated F1+F4+inbox into a single /panel/roles live surface — better UX than building separate views. Each role card now polls /panel/roles/{role_id}/live every 2s; per-card section shows pending PINs (gold-bordered, ready to copy) and active sessions (with per-row Revoke button).

- **PR #33 build 27** — consolidated panel

**Changes:**
- New route `GET /panel/roles/{role_id}/live` returns _role_live.html HTMX fragment with pending pin_challenges + active auth_sessions
- New route `POST /panel/sessions/{session_id}/revoke` sets revoked_at=now() with account-scoped auth check
- `/panel` redirects to `/panel/roles`
- Dropped per-card static last_access + last_pin queries (replaced by live polling)
- Inline JS in fragment handles ISO→relative time + PIN expiry marking (re-runs on each HTMX swap)

**End-to-end flow validated in production:** fresh AI session calls claim_role → PIN appears on role card within 2s → Director reads → AI calls auth_with_pin → PIN row replaced by active session row → Director clicks Revoke → session disappears within 2s; next MCP call from that AI gets "Invalid or expired session token."

## Outstanding work

### F1 — memo browser (outstanding)

Read-only display of directed memos by role/status/thread. Closes the visibility loop F4 started: live PINs and sessions are now visible per role, but you can't browse what AI sessions have actually been writing into memos. Medium scope. No schema; no new MCP tools; pure panel-side work.

Likely shape:
- New route `/panel/roles/{role_id}/inbox` (parallel to existing `/notes`) — lists kind=="inbox" memos
- Maybe a top-level `/panel/memos` cross-role view with filters (role, status, thread_id)
- Click memo → expanded view with body + body_ref render
- Reuse the existing per-role notes template structure

### F2 — notes browser create/edit (outstanding)

Extends F1 with affordances for filing memos directly from the panel (currently you can only file via `send_memo` MCP tool). Useful for Director to file notes / send directed memos without going through an AI client. Medium scope; depends on F1's shared template.

### F5 — mirror-list viz (deferred)

Surface `x.org.org_location` mirror chains for orgs that publish to multiple locations. **Speculative** — none of the six current opencatalog fixtures (memodef-spec, roledef-spec, catdef-spec, orgdef-spec, thingalog, openbraid-org) carry `x.org.org_location` data, so this is "build the viewer before there's data." Recommend deferring to G+ or until at least one org publishes mirror data.

### Phase G — self-host docs (untouched)

Docker Compose, env-var inventory, migration bootstrap, audit of openbraid.app-specific assumptions in the code. From v1 roadmap. Director's call when to start.

## Deferred items (carried from Phase E)

1. **Cross-spec canonical-JSON spec coordination** — my Phase E experience memo (`s:/projects/orgdef-spec/orgdef/memos/2026-05-10-2355--openbraid-engineer--orgdef-strategist--phase-e-opencatalog-implementation-experience.openthing`) flagged that "byte-equivalent round-trip" needs a SCHEMA-level canonical-JSON spec to be implementation-portable. orgdef-strategist hasn't signaled interest yet; on hold pending their move.

2. **Vacate-binding affordance for artifact-bound roles** — Director ratified the no-explicit-vacate-tool lean ("you can just close the agent"). No use case yet. If cross-account claims emerge, may want a way to end a binding cleanly so the position becomes reclaimable as fresh. Until then, parked.

## Hotfix discipline observations

Two hotfixes this phase, both panel-side:

1. **Build 23 (NULL org_id)** — caught by smoke testing F0 end-to-end; tests didn't catch because they mocked Supabase and the constraint was schema-level. Would have been hard to anticipate without smoke; schema constraints from prior migrations are easy to forget when adding new code paths.

2. **Build 26 (missing import)** — caught when Director clicked /panel/roles in production. Tests didn't catch because they mocked the route handler's dependencies without actually running the panel SSR. Added `tests/test_panel_smoke.py` with three guards (module-imports / ruff F821 / handler-runs-with-mocks) so this class of regression gets caught next time. **Going forward**: any new panel route should add a smoke test that runs the handler body, not just unit tests against the helpers.

## Test coverage trail

- Build 22: 105 tests (F0 added 6 in test_artifact_claim.py)
- Build 24: 105 tests (F3 panel-only; no test deltas)
- Build 25: 105 tests (F3 follow-up panel-only)
- Build 26: 108 tests (+3 panel_smoke guards)
- Build 27: 108 tests (F4 panel-only)

Test suite remains fast (~0.5s for the full run; pytest -q).

## Strategist questions (for the consultation)

1. **F1 first vs Phase G first?** Phase F panel UX is now operationally usable (F0 + F3 + F4). F1 (memo browser) would close the visibility loop; Phase G would shift focus to self-hosting. Both are valuable.

2. **F2 as part of F1 PR or as follow-up?** F2 extends F1's template, so building both in one PR is efficient but bigger. Split or bundled?

3. **Should F5 stay in Phase F or move to G+?** No data to visualize yet. Building speculatively risks the wrong abstraction.

4. **Vacate-binding revisit when?** Deferred indefinitely or wait for cross-account claim signal?

## Engineer-seat handoff notes

When next session picks this up:

- **Solo-merge runway**: feedback memory says diagnostic / log-only PRs can be solo-merged; panel UX changes have been getting Director eyes per the F0 review pattern. When in doubt, ask before merge.
- **Smoke discipline**: end-to-end flow against thingalog/implementer is the gold-standard validation. Run after any /panel/roles or claim_role change.
- **Test infrastructure**: test_panel_smoke.py is new — extend it for any new panel routes (the handler-runs-with-mocks pattern catches NameErrors and structural bugs before deploy).
- **Migration sequence**: 0001-0011 applied to prod. Next migration goes to 0012.
- **PR sequence**: PR #28-#33 merged. Next branch off main; current head is `(build 27) Phase F F4: consolidated /panel/roles control panel (#33)`.

— openbraid-engineer
