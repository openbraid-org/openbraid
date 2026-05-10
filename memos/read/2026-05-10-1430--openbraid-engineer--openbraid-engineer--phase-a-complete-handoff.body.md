# Phase A complete — Phase B still gated; next runway is Phase C C7 (export tool)

You're picking up the openbraid-engineer seat after Phase A landed. Read [`CLAUDE.md`](../../CLAUDE.md) and [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing) on session start as usual; the v1 roadmap is at [`proposals/2026-05-10-v1-roadmap-sequencing.md`](../../proposals/2026-05-10-v1-roadmap-sequencing.md) and remains the authoritative sequencing document.

## Phase A — done

| Item | Disposition | Build |
|---|---|---|
| A1 — tool-discovery quirk reproduction | **Closed not-reproducible.** 3 of 3 fresh Claude Desktop sessions returned all 6 openbraid tools on first `tool_search`. Captured in [`decisions/2026-05-10-tool-discovery-quirk-not-reproducible.md`](../../decisions/2026-05-10-tool-discovery-quirk-not-reproducible.md). Solo-merged. | 2 |
| A2 — `accounts.google_user_id` → `auth_user_id` | **Merged as PR #11.** Migration `0002_rename_auth_user_id.sql` applied to live Supabase before merge; column verified renamed. Pure metadata operation; no application-code changes. | 3 |
| A3 — auto-create accounts row on email signup | **Merged as PR #12.** New `server.db.ensure_account` helper handles both link-existing-bootstrap and insert-new paths. Wired into `email_signup` handler with `try/except` so failures don't block sign-up. 2 unit tests with mocked Supabase client. 15/15 tests pass. | 4 |

**Total time:** under one Director-time block (afternoon 2026-05-10). Half-a-day estimate from the kickoff memo was approximately right.

**Surprises during Phase A:** none material. Build-number tracking was bootstrapped (CLAUDE.md "Current build" updated from "N/A (pre-deploy)" to "1") since v0 had shipped without the convention being applied. Build numbers will not be retroactively applied to PRs #1-#10; counter starts at 1 for the housekeeping commit and increments per push to main.

## Phase B — still gated

Checked `s:/projects/memodef-spec/memodef/decisions/` at 14:30 Director-time on 2026-05-10. The directory contains:

- `bootstrap-deviation.md`
- `proposal-2026-04-29-catdef-strategist-architecture-validation.md`
- `proposal-2026-05-01-body-ref-v0.2.md`
- `receiver-commits-convention.md`
- `self-extraction-request.md`

No decision artifact exists for the memos-to-file-and-notes-folder proposal. The proposal itself is at `s:/projects/memodef-spec/memodef/proposals/2026-05-10-memos-to-file-and-notes-folder.md` — still in proposal state, not yet decision.

**Implication:** Phase B (B1 `to: "file"` sentinel acceptance, B2 notes storage migration, B3 `list_inbox(folder=...)` extension, B4 read-only notes browser) **cannot start.** Director ratification of memodef v0.3 upstream is the gate.

If you check this and find a decision artifact has landed since this memo was written: Phase B is unblocked, start with B1 + B2 (storage and tool acceptance) before B3 (API surface) and B4 (panel UI).

## Phase C C7 — recommended next runway

C7 is the full-fidelity export tool. **MUST per the orgdef memo:** "without portable export, openbraid would be lock-in." It's marked independent in the roadmap proposal — doesn't depend on C1-C6 (the URL-space and claim-ceremony rewires).

### Starting context for C7

Goal: an MCP tool (call it `export_role` or similar) that, given a session token, returns the full state of the authenticated role's mailbox in a portable format. The acceptance criterion is that the export can be re-imported into a different openbraid instance (or self-hosted instance) and the role's history is faithfully reconstructed.

What the export needs to include (per orgdef memo's "cross-protocol equivalence" requirement):

- All memos in the role's mailbox (inbox, read, archived) with full memodef:Memo shape
- Role definition (id, name, account_email, roledef_url, created_at)
- Auth ceremony state (no — auth tokens shouldn't be exported, they're session-bound)
- Account boundary (the role's account_email, but no other accounts' data)

Format suggestion: a JSON document with a memodef-compliant serialization. Each memo as a memodef:Memo; the role as a roledef:Role reference; account as bare email. **Sketch the format in a proposal first** before implementing — this is exactly the kind of strategist-scope artifact (the export shape becomes a de facto interop standard) that warrants explicit ratification.

Implementation sketch (don't take as gospel — strategist may steer):

1. New tool `export_role(session_token: str) -> dict` returning the full export.
2. New helpers in `server/db.py`: fetch all memos for the role, fetch role metadata.
3. Probably no schema changes (read-only).
4. Add to `EXPECTED_TOOLS` in `tests/test_tool_contracts.py` so the contract test catches future drift.

### Things you SHOULDN'T do without explicit Director or strategist sign-off (still applies)

- Add tools beyond what's specified in the roadmap (the roadmap allows C7 = export tool; nothing else gets added unilaterally)
- Change the claim ceremony or auth flow (Phase C C5 is the ceremony rewire; that's gated by Phase C C1+C4 — not on C7's path)
- Add encryption-at-rest, RLS policies, or other architectural shifts deferred per the v0 design
- Merge own non-trivial PR without Director approval (only solo-merge tiny diagnostic / log-only PRs per Director's standing rule)

## Notes from this session

- **Build-number convention is now active.** CLAUDE.md "Current build" should track the latest deployed build but practical bookkeeping ratchets are awkward (each push-to-main is a new build, but updating CLAUDE.md inside a commit is itself a push). Pragmatic stance: commit-message build-number prefixes are authoritative; CLAUDE.md is bumped opportunistically when the file is being edited for other reasons.
- **PR review pace works fine.** Director merged PR #11 and PR #12 same-session after explicit "merge them" request. Don't take this as standing authorization for future PRs — still ask explicitly per PR (per Director's standing rule).
- **Director's email signup status:** as of Phase A close, Director may or may not have completed the email-signup smoke test described in PR #12's body. If the smoke test hasn't happened, encourage Director to do it next session (sign up a fresh email, confirm panel renders without "no account" state) — that closes the A3 verification loop.
- **Cross-spec memo from orgdef-strategist** (`memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing`) is informational for now. Do NOT mark it read; it's strategist-seat material and the strategist (when formally seated) will handle the disposition. If you accidentally inhabit the strategist seat and do mark it read, file an addendum noting that.

## Final disposition

Ending this session cleanly:
- Phase A done; three items closed/merged.
- Two PRs merged with Director's explicit per-PR approval.
- One decision artifact filed (A1 closure).
- Two memos in `read/` from the v0 era (v0-shipped engineer→engineer; cross-vendor-reach engineer→strategist), both processed.
- One memo (the Phase A kickoff from openbraid-strategist) about to be marked read in the same commit as this handoff filing.
- One cross-spec memo (orgdef-strategist) still in inbox, addressed to openbraid-strategist seat — leave it.

Goodnight, future-self. Phase C C7 is the strand — it's where the moat-as-protocol pitch becomes empirical.

— openbraid-engineer (2026-05-10 afternoon Director-time)
