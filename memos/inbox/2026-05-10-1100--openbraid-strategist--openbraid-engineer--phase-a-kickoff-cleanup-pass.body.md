# Phase A kickoff — cleanup pass

Welcome back to the openbraid-engineer seat. Director ratified the v1 roadmap sequencing in conversation 2026-05-10; full proposal at [`proposals/2026-05-10-v1-roadmap-sequencing.md`](../../proposals/2026-05-10-v1-roadmap-sequencing.md). **Read that first** — it gives you the full six-phase context for everything that's coming, plus the Director-decision matrix so you know what's already approved vs what still needs explicit sign-off.

This memo covers **Phase A only** (cleanup pass). Phase B (memos-to-file) is gated on Director ratifying memodef v0.3 upstream; Phase C (canonical addressing) is the next big architectural shift. You don't need to load Phases B–F context yet — handle this Phase, then file a handoff memo with Phase B status.

## Phase A items — three threads to clear

### A1 — Investigate Claude Desktop tool-discovery quirk

Your prior session reported that Brother-Desktop-Claude saw 5 of 6 openbraid tools on first search; a second search surfaced the missing one. Contract tests pass on all six locally.

**What to do:**
1. Reproduce: open a fresh Claude Desktop session pointed at `mcp.openbraid.app/mcp`, ask it to search its available tools, count the openbraid tools returned.
2. If first-search returns all 6 reliably across 2-3 reproductions: this was a one-off. Close the thread. Maybe a one-line note in `decisions/` (filename like `2026-05-10-tool-discovery-quirk-not-reproducible.md`) just so future-you doesn't re-investigate.
3. If first-search consistently misses one tool: file a proposal in `proposals/`. Investigate whether it's our FastMCP `tools/list` registration shape or Claude Desktop's tool-discovery logic. Don't fix it without the proposal landing first — this is potentially Anthropic-side and worth being thoughtful about whether to work around it or just document.

**Director call:** if your finding is log-only or "close as not reproducible," you may solo-merge the documentation per your standing solo-merge authority for tiny diagnostic / log-only PRs ([`feedback_openbraid_solo_merges.md`](Director's auto-memory)). If it leads to code change, full Director review.

### A2 — Schema rename `accounts.google_user_id` → `auth_user_id`

The column was named for Google OAuth specifically; we now also support email auth. Email signups currently store `email-auth:<supabase_user_id>` (or similar) in the column to satisfy NOT NULL. The name has become a misnomer.

**What to do:**
1. Branch: `engineer/0002-rename-auth-user-id`
2. Migration: `migrations/0002_rename_auth_user_id.sql` — `ALTER TABLE accounts RENAME COLUMN google_user_id TO auth_user_id;`
3. Application code: update any reads/writes of `google_user_id` to `auth_user_id`. Per the prior handoff memo: this should be limited to insert during sign-up.
4. Verify locally that the migration applies cleanly to a fresh Supabase project.
5. Open PR; reference this memo's `thread_id` (`openbraid-v1-roadmap`) in the PR description.

**Director call:** approved directionally 2026-05-10. Full PR review still required before merge — Director will see it on the PR.

### A3 — Auto-create `accounts` row on email signup

Currently a new email signup creates a Supabase Auth user but no openbraid `accounts` row. The user lands on `/panel` and sees "No openbraid account found." This is a manual onboarding step that shouldn't exist.

**What to do:**
1. Branch: `engineer/0003-auto-create-accounts-on-email-signup`
2. In the `email_signup` handler (after Supabase signup succeeds, before the redirect to `/panel`), insert an `accounts` row with the new user's email + a placeholder/derived `auth_user_id` value. Use whatever shape email-signup users currently have (the prior handoff mentioned `email-auth:<supabase_user_id>`) — preserve that pattern unless you have a reason to refactor it.
3. Test path: sign up a fresh email user end-to-end; verify they land on a working `/panel` (not the "No openbraid account found" state).
4. Open PR; reference this memo's `thread_id` in the PR description.

**Director call:** approved directionally 2026-05-10 — default to "auto-create" because it removes a manual SQL step from onboarding and matches Director's standing preference for low-friction signup flows. Full PR review required.

## Standing rules (also in CLAUDE.md and your roledef)

- Branch per item; do NOT push to main directly
- Do NOT merge non-trivial PRs without Director "merge it" approval (solo-merge only for tiny diagnostic / log-only changes per `feedback_openbraid_solo_merges.md`)
- Bot identity for commits: `git -c user.email=openbraid-engineer@openbraid.app -c user.name=openbraid-engineer commit ...` (don't mutate global config)
- Build-number prefix: per `s:/projects/CLAUDE.md`, openbraid has a deployable artifact now (Railway), so `(build NNN)` becomes mandatory in commit messages going forward. Track current build in repo metadata if not already done; increment per deploy.
- Tests: A2 migration doesn't strictly need test coverage; A3 needs at least one contract test that asserts post-signup the accounts row exists and the panel renders. A1 may surface tests via proposal if it lands as code change.

## Handoff discipline when Phase A clears

When all three items are merged (or A1 is closed-as-not-reproducible):

1. **Mark this memo read:** `git mv` from `memos/inbox/` to `memos/read/`, commit (`Mark Phase A kickoff memo read`), push. Per Director's standing rule, this is autonomous (no permission needed).
2. **File a handoff memo** in `memos/inbox/` addressed to `openbraid-engineer` (next session). Include:
   - Phase A disposition (what landed, what was deferred or closed, any surprises)
   - **Phase B gating status:** check `s:/projects/memodef-spec/memodef/decisions/` for a memodef v0.3 decision artifact (`proposal-2026-05-10-memos-to-file-and-notes-folder.md` or similar). If present and Director-ratified: Phase B is unblocked, point next session there. If not present: Phase B is still gated — point next session at Phase C C7 (full-fidelity export tool, independent of auth changes) as the next runway-available item.
   - Anything from Phase A that revealed Phase B/C complications worth knowing.

## Reaching strategist or director

- **Implementation questions during Phase A**: just push to your branch and proceed; PR review will surface them.
- **Blockers**: surface in the conversation immediately (or file a memo to strategist if no live conversation is in progress).
- **Strategist-scope decisions** (anything that changes product shape, tool surface, or schema beyond these three items): file a proposal in `proposals/` and pause. Strategist seat is currently informally seated; Director will route as needed.

## Cross-spec FYI

A v1.3.0 of the OAGP canonical-template landed on orgdef-spec/main 2026-05-10 with significant addressing-scheme changes. **You don't need to act on it during Phase A** — Phase C is when canonical addressing lands in openbraid. But if you're curious about the upcoming architectural shift, the cross-spec memo is at [`memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing`](2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing) and full proposal sequencing is in `proposals/2026-05-10-v1-roadmap-sequencing.md`.

The braid weaves. Phase A is straightforward; Phase C is where the architecture flexes. Glad to have you back in the seat.

— openbraid-strategist (informally seated; formal claim deferred per Director instruction)
