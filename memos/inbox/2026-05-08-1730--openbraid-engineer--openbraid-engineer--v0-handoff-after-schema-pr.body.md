# Handoff after schema PR — server scaffold is the next strand

You're picking up the openbraid-engineer seat after the first session (2026-05-08). Read [`CLAUDE.md`](../../CLAUDE.md) and [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing) first if you haven't.

## What I did

- Cut branch `engineer/0001-initial-schema` off main.
- Wrote [`migrations/0001_initial.sql`](../../migrations/0001_initial.sql) — five tables (`accounts`, `roles`, `pin_challenges`, `auth_sessions`, `memos`), `pgcrypto` extension, UUID PKs, soft-delete, indexes per the kickoff memo's spec.
- Followed Director's four stated leans inline rather than filing four separate proposals; called them out explicitly in the PR description for confirmation.
- Opened **[PR #1](https://github.com/openbraid-org/openbraid/pull/1)** against `main`. **NOT MERGED.**
- Marked the v0 kickoff memo read on `main` (commit `e38717e`).

## What's pending review

PR #1 is waiting on strategist (vacant) or director review. The PR description asks Director to confirm or redirect on:

1. `roles` name uniqueness: per-account (implemented `UNIQUE (account_id, name)`)
2. `roles.roledef_url`: nullable / optional in v0
3. One role = one position v0 (no `positions` table)
4. memos `body` + `body_ref` as separate columns (mirroring the memodef:Memo wire shape)

If Director redirects on any of these, that's a small follow-up migration — but **do not pre-empt by writing it until they say so.**

## What's next — recommended

The server scaffold is unblocked even before PR #1 merges (it doesn't depend on the schema being applied to a live Supabase project). My recommendation for the next session:

1. **Confirm PR #1 status first.** If unreviewed, leave it. If merged, note the merge in your session-start scan. If redirected, file the follow-up migration before starting server work.
2. **Scaffold `server/`** with FastMCP entry point and the six tool stubs from the kickoff memo: `claim_role`, `auth_with_pin`, `send_memo`, `list_inbox`, `read_memo`, `mark_read`. Stubs return `NotImplementedError` or fixed placeholder responses; the goal is shape, not behavior.
3. **Scaffold `tests/`** with `pytest.ini` and one passing smoke test per tool stub. Per the roledef, contract tests are required for the MCP tool surface — even stubs benefit from a contract test that asserts the tool's name, parameter schema, and return shape are wired correctly.
4. **Do NOT** plug Supabase in yet — that's a follow-on session once Director has the Supabase project provisioned and we have credentials in Railway env vars. Tool implementations stay stubbed until then.
5. **Open a separate PR** for the server scaffold (`engineer/server-scaffold` branch). Don't pile it onto PR #1.

## Things that would have been nice to know — additions to my own onboarding

(For your own session-start checklist, since the roledef is still settling:)

- The `gh` CLI is configured and works against `openbraid-org/openbraid`. PR creation via `gh pr create` worked first try.
- Bot identity for commits: `git -c user.email=openbraid-engineer@openbraid.app -c user.name=openbraid-engineer commit ...`. The repo's `user.email` is the human's identity by default; per-commit overrides are the cleanest way to stay seat-correct without mutating repo config.
- Co-author trailer per `CONTRIBUTING.md`: `Co-Authored-By: Claude <claude-opus-4-7> <noreply@anthropic.com>`. Replace the model id with whatever model is actually running you.
- Build number prefix `(build NNN)` is **omitted** pre-deploy — confirmed by the kickoff memo and by `CLAUDE.md`'s "Current build: N/A (pre-deploy)".
- The kickoff memo's "open questions you will hit" section is best read as "Director's leans, confirm in the PR" — not as a hard "file four proposals" gate. If you encounter something **without** a stated lean, then file a proposal.

## Out of scope for the next session

Per my roledef, do not do any of these without strategist/director sign-off:

- Add the seventh MCP tool (or remove one of the six)
- Change the auth flow shape
- Pick the panel stack (Next.js vs HTMX) — strategist owns that call
- Add encryption-at-rest (deferred per the kickoff memo)

If any of those come up, file a proposal in `proposals/` and pause.

## Final disposition

I am ending this session cleanly. Branch pushed, PR open, kickoff memo marked read, handoff memo filed. No half-finished implementations.

Good luck. The braid weaves itself one strand at a time. The server is the second strand.

— openbraid-engineer (session 1, 2026-05-08)
