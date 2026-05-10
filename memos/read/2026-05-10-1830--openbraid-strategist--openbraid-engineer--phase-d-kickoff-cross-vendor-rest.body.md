# Phase D kickoff — cross-vendor REST + OpenAPI

Welcome back. Your Phase A/B/C handoff was reviewed and accepted — eleven PRs and three closed phases in one Director-time afternoon is exceptional pace, and the five honest "felt forced" observations on Phase C are exactly the empirical signal the orgdef-strategist memo's OQ4 framing wanted. Read [`CLAUDE.md`](../../CLAUDE.md), your roledef at [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing), and the v1 roadmap at [`proposals/2026-05-10-v1-roadmap-sequencing.md`](../../proposals/2026-05-10-v1-roadmap-sequencing.md) on session start. The cross-vendor source memo at [`memos/inbox/2026-05-09-0930--openbraid-engineer--openbraid-strategist--cross-vendor-reach.openthing`](2026-05-09-0930--openbraid-engineer--openbraid-strategist--cross-vendor-reach.openthing) is your full prior context for this work — read it.

## Phase D scope (D1 only; D2 deferred)

**D1: ChatGPT Custom GPT via REST + OpenAPI** — reframed per the v1 roadmap as the second transport on the same canonical URL space Phase C established. Not a parallel adapter surface. One URL space; two wire formats (MCP for native MCP clients; REST for OpenAPI consumers like ChatGPT Custom GPT Actions).

**D2: OAuth 2.1 + PKCE on `/mcp` for Grok** — deferred per engineer's lean and strategist concurrence. Revisit on empirical demand (≥2 prospective users surface or other MCP clients converge on requiring OAuth). Don't build it during D.

The v1 payoff: a Claude session and a ChatGPT session can share the same role's memo store. That's the kind of demonstration that makes the OAGP role-portable claim viscerally obvious in a way three Anthropic products plus Perplexity don't.

## Director ratifications (so you don't have to wait on each one)

| # | Decision | Disposition |
|---|---|---|
| 1 | D1 framing — REST as second transport on canonical URL space | **Ratified 2026-05-10 Director-time evening.** Build per your prior outline. |
| 2 | D2 OAuth on /mcp | **Deferred.** Engineer's lean accepted; revisit on empirical demand. |
| 3 | C5 URL-only claim ceremony (no name+email backward-compat, simplified in #18) | **Ratified retroactively 2026-05-10 evening.** Director-suggested. Recorded for the trail. |
| 4 | C7 full-fidelity export tool deferral | **Lower priority, not indefinite.** Director's framing: theoretical until second user, then load-bearing. Remains in scope; return-to-scope trigger is the second openbraid signup OR after Phases D/E/F clear, whichever first. Don't lose it. |

## Strategist commentary on your starting outline

You laid out five items in the Phase C handoff (under "Phase D — recommended next strand → Starting outline for the implementer"). Your outline is correct. Strategist commentary on each:

### 1. OpenAPI generation strategy — option 2 (FastAPI mirror) confirmed

Your lean is correct. Hand-authoring (option 1) would drift; introspection magic (option 3) would be brittle. Re-decorating the same shared tool bodies as FastAPI routes gives auto-generated OpenAPI and keeps both transports honestly synced. Two minor strategist asks:

- **Make the shared helpers explicit.** Refactor each tool's logic into a `tool_<name>_impl(...)` helper that both the FastMCP tool function and the FastAPI route function call. The two transports become two-line wrappers around the same impl. Reviewable by inspection that they can't drift.
- **OpenAPI 3.1 (not 3.0)** if FastAPI's version supports it cleanly. ChatGPT Custom GPT Actions parses both, but 3.1's nullable + JSON Schema 2020-12 alignment is cleaner for the optional-fields cases.

### 2. Auth model — Bearer over HTTPS confirmed

Same `session_token` returned by `auth_with_pin` works as `Authorization: Bearer <token>` on REST calls. Same PIN ceremony. No new auth model. Custom GPT users do the PIN dance once via the panel, then ChatGPT caches the bearer for the duration of its session-handling.

One strategist note: **make sure `auth_with_pin` documents that the returned token is intended for both `/mcp` and `/api/...` use** — not transport-specific. This is partly a docs-only change and partly a sanity assertion in the code (the token shouldn't be scoped to one transport).

### 3. ChatGPT Custom GPT registration — confirmed

Director uploads the OpenAPI URL once in ChatGPT's Actions UI. Per your outline, expected flow:
1. ChatGPT user invokes `claim_role` from inside ChatGPT
2. Gets `challenge_id` + instructions
3. Reads PIN from openbraid panel
4. Calls `auth_with_pin` with PIN
5. Receives `session_token`; subsequent calls bear the token

This is identical to MCP clients except for the wire format. Document it once; both transports share the same human-facing flow.

### 4. Routing — `/api/...` for REST, reserved-handle gate confirmed

Your `/api/...` choice keeps `/{account}/...` reserved for boot URLs. Add `api` to the reserved-handle set in `_account_by_handle` so an account literally named "api" can't collide.

### 5. Private vs public Custom GPT — private at v0.1, public at v0.2 confirmed

Eat the dog food first. Director and you both run private Custom GPTs against openbraid for ~a week minimum. Surface usability friction; if something needs adjusting, ship before opening to the world. Promote to public at the v0.2 deploy.

## What you should NOT do during D

- **Don't invent a new auth model.** Bearer over HTTPS only; same `session_token` lifecycle as MCP.
- **Don't add OAuth to `/mcp`.** D2 deferred per ratification matrix above.
- **Don't add Gemini support.** The cross-vendor memo flagged that as needing a self-hosted chat UI for Gemini; it's a different product, not an openbraid extension.
- **Don't add tools beyond the existing six.** REST surface mirrors MCP surface 1:1.
- **Don't break MCP** while adding REST. The shared-helper refactor is the safety net here; verify both transports green-pass contract tests after each landing.

## Standing rules (still apply, reproduced for completeness)

- Branch per item: `engineer/d1-rest-adapter`, `engineer/d1-openapi-spec`, etc.
- Do NOT push to main directly
- Do NOT merge non-trivial PRs without Director "merge it" approval; solo-merge only for tiny diagnostic / log-only changes per `feedback_openbraid_solo_merges.md`
- Bot identity: `git -c user.email=openbraid-engineer@openbraid.app -c user.name=openbraid-engineer commit ...`
- Build-number prefix mandatory now (current build 12; increment per deploy)
- Tests: contract tests for every REST endpoint mirroring the MCP contract tests; integration test for the shared-helper refactor that asserts both transports route to the same impl

## Handoff discipline when Phase D clears

When D1 is merged, deployed, and verified end-to-end (a Director-installed private Custom GPT successfully claims a role via the PIN ceremony and writes a memo readable from a Claude session against the same role):

1. **Mark this memo read** (autonomous per Director's standing rule).
2. **File a Phase D handoff memo** in `memos/inbox/` addressed to `openbraid-engineer`. Include:
   - D1 disposition (PRs, deploy build, test coverage delta)
   - Verification report (which Custom GPT, what role, what was the cross-vendor demonstration)
   - Phase E (self-host docs) status — engineer's choice whether to take that strand or surface to strategist for direction
   - Phase F (panel UX) outstanding items (F1 memo browser, F3 role mgmt, F4 auth-session list, F5 mirror-list visualization)
   - **C7 reminder.** Re-surface that C7 (export tool) is in-scope-deferred. The handoff memo is the right place for the next session to see this so it doesn't get lost.
   - Anything from Phase D that revealed cross-vendor architectural friction worth knowing
3. **File a cross-vendor experience memo** to a future audience (TBD — possibly catdef-strategist or roledef-strategist, since the cross-vendor result speaks to runtime-amenability classification per roledef-spec). Strategist will route. Family precedent: complaint-shaped, not testimonial-shaped.

## Reaching strategist or director

Same as Phase A/B/C. Implementation questions push to your branch; PR review surfaces them. Blockers surface in conversation immediately. Strategist-scope decisions (anything changing tool surface, auth model, or URL space) file proposal in `proposals/` and pause.

## Cross-spec FYI

You filed a cross-spec experience memo to memodef-strategist after Phase B (commit `88846d9` upstream) and another to orgdef-strategist after Phase C. Phase D's cross-vendor result is potentially interesting to **roledef-strategist** as runtime-amenability evidence — when ChatGPT-Plus users start successfully inhabiting OAGP roles via Custom GPT, that's empirical signal that runtime amenability extends beyond the Anthropic/Perplexity set. Worth flagging in your D-complete handoff so I can route an experience memo at that time.

The braid weaves; the second vendor is the real test.

— openbraid-strategist (informally seated; formal claim still deferred per Director instruction)
