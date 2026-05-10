# Phase C complete — D unblocked; F partial; auth-flow rewrites done

You're picking up after a heavy session. Phase A, B, and C all closed in one Director-time afternoon on 2026-05-10. The product is now architecturally v1 — addressed via canonical OAGP URLs, boot-payload SHOULD-shape live, role-portable accumulated context (memos-to-file) shipped. Read [`CLAUDE.md`](../../CLAUDE.md), [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing), and the v1 roadmap proposal at [`proposals/2026-05-10-v1-roadmap-sequencing.md`](../../proposals/2026-05-10-v1-roadmap-sequencing.md) on session start.

## Phase disposition

| Phase | Item | State | PR(s) |
|---|---|---|---|
| A | A1 tool-discovery quirk | Closed not-reproducible | decisions/ |
| A | A2 schema rename | Merged | #11 |
| A | A3 auto-create accounts | Merged | #12 |
| B | B1 send_memo `to_role=file` | Merged | #13 |
| B | B2 `kind` column migration | Merged | #13 |
| B | B3 `list_inbox(folder=)` | Merged | #13 |
| B | B4 panel notes browser | Merged | #14 |
| B | Cross-spec experience memo to memodef-strategist | Filed `88846d9` upstream | |
| C | C1 three-level URL endpoints | Merged | #16 |
| C | C2 two-segment sugar | Merged | #16 |
| C | C3 position ordering (documented; created_at fallback) | Merged | #19 |
| C | C4 boot payload (7-field, Director-ratified verbatim) | Merged | #16, polish in #18 |
| C | C5 URL-based claim ceremony | Merged | #17, simplified in #18 (no name+email backward-compat) |
| C | C6 `x.org.org_location` storage | Merged | #19 |
| C | C7 full-fidelity export tool | **Deferred** per Director 2026-05-10 | — |
| F | Notes browser, copy-prompt UI | Landed opportunistically | #14, #19 |

**Current build:** 12. Live at `https://mcp.openbraid.app` + `https://www.openbraid.app`.

## What works end-to-end as of 2026-05-10

A fresh Claude Desktop / Code / mobile / Perplexity session given the one-line prompt:

> *Please claim role: `https://mcp.openbraid.app/scott/personal/personal-strategist` via the openbraid mcp connector, and review the existing notes and memos. I'll deliver the PIN.*

— claims the role via PIN ceremony, reads inbox + notes, and inhabits the seat with full accumulated context. The OAGP URL-as-instruction collapse works on the live deploy. Director copy-pastes this prompt from the `/panel/roles` page (the 📋 Copy prompt button I shipped in PR #19).

## Phase D — recommended next strand (UNBLOCKED)

Per the v1 roadmap proposal § Phase D — "ChatGPT Custom GPT via REST + OpenAPI", **reframed** post-Phase-C as the second transport over the same canonical URL space.

Director already ratified this directionally: "implicit-approved-by-sequencing-ratification 2026-05-10; explicit confirmation welcome before D1 starts."

### D1 scope

A thin REST adapter that exposes the same six tools (`claim_role`, `auth_with_pin`, `send_memo`, `list_inbox`, `read_memo`, `mark_read`) as REST endpoints under (suggested) `mcp.openbraid.app/api/...`. OpenAPI spec at `mcp.openbraid.app/api/openapi.json`. The auth flow is the same PIN ceremony; session_token threads through as Bearer auth in the REST headers.

ChatGPT Custom GPT installs the OpenAPI URL once; ChatGPT-Plus users (anywhere in the world) can then chat with that Custom GPT and claim openbraid roles. The big payoff: **the OAGP role-portable claim crosses the vendor boundary** — a Claude session and a ChatGPT session can share the same role's memo store. That's the kind of demo that makes the role-portable thesis viscerally obvious in a way three Anthropic products don't.

### Starting outline for the implementer

1. **OpenAPI generation strategy.** FastMCP doesn't (as of fastmcp 3.2.4) emit OpenAPI. Three options:
   - Hand-author a `server/openapi.py` that mirrors the six tools as `paths`. Most precise; modest maintenance burden as tools evolve.
   - Use `fastapi` (already a transitive dep via fastmcp) and re-decorate the same tool bodies as FastAPI routes. Auto-generates OpenAPI. More code, less drift.
   - Adopt a small adapter layer that introspects FastMCP's tool registry and produces an OpenAPI doc. Most magical; brittle.

   Engineer's lean: option 2 (FastAPI mirror). The tool bodies become two-line wrappers around shared helpers; both surfaces stay in sync because the auth + storage logic lives below them.

2. **Auth model.** Bearer token over HTTPS. The same `session_token` returned by `auth_with_pin` works as `Authorization: Bearer <token>`. No need to invent a new auth flow.

3. **ChatGPT Custom GPT registration.** Director uploads the OpenAPI URL once in ChatGPT's Actions UI. ChatGPT prompts users to authorize per call (or per session, depending on its caching). The same PIN ceremony plays out: user calls `claim_role` from inside ChatGPT, gets a challenge_id, reads the PIN from the openbraid panel, calls `auth_with_pin`, receives a `session_token`. Subsequent calls bear the token.

4. **Hosting on the URL space.** REST endpoints live at `/api/...` to keep `/{account}/...` reserved for boot URLs. No collision with the existing routing.

5. **Public vs private GPT.** Director's note in the cross-vendor memo: lean private during v0.1, public at v0.2 after Director has eaten dog food.

### What you should NOT do during D

- Don't invent a new auth model. Same PIN ceremony, same session_token. Bearer over HTTPS.
- Don't add OAuth to `/mcp` (Option E from the cross-vendor memo). Director-deferred to "empirical demand" — i.e., when Grok or similar stricter-MCP clients become a real user need.
- Don't add Gemini support yet. Cross-vendor memo flagged that as needing a self-hosted chat UI for Gemini; too much scope.

## Phase E — self-host docs (UNBLOCKED, but lower priority than D)

Per roadmap, E depends on C complete (now true). Scope:
- E1: Docker Compose, env-var inventory, Supabase-or-equivalent schema bootstrap
- E2: Audit for openbraid.app-specific assumptions; promote to config
- E3: Reference use cases (`mcp.firstchurch.org`, etc.)

~1 day estimated. Less existential than D but unlocks the moat-as-protocol pitch.

## Phase F — panel UX maturation (always picking-up-able)

Already partially landed: notes browser (#14), copy-prompt button (#19). Remaining (per roadmap):
- F1 memo browser by role/status/thread
- F2 notes browser with create/edit affordances (currently read-only)
- F3 role management UI (delete/rename/edit; currently SQL-only)
- F4 auth-session list + revoke
- F5 mirror-list visualization (per C6)

All fragmentable; pick by Director priority + dependency.

## Notes on what felt forced in Phase C (for your context, future-self)

These are spec-shaped observations the next engineer might find useful. The full version is going to orgdef-strategist as a complaint-shaped experience memo (see filing in `s:/projects/orgdef-spec/orgdef/memos/inbox/`).

1. **The 7-field boot payload sparseness.** openbraid populates ~3.5 of the 7 fields meaningfully. `position` + `org_summary` + `inbox_summary` are real. `incumbent` is thin (a session count). `role_definition` is just a URL pointer (we don't fetch). `job_definition` is always null (we don't store job defs). `claim_instruction` is a free-form string. For C4's MUST promotion to be empirically warranted, you'd want all 7 fields meaningfully populated by at least 2 implementations.

2. **Two-segment sugar is brittle once an account hosts >1 org.** Right now Director has one org; `/scott/personal-strategist` works. If Director ever creates a second org, that URL form errors out with "Two-segment URL form requires exactly one org." The spec says this is correct behavior but the UX is user-hostile. A possible spec amendment: "two-segment URLs resolve to a position when the position name is unique across the account's orgs." Worth flagging if you hear adopter pain.

3. **C3 (depth-first ordering) is aspirational without relationships storage.** We use `created_at` asc per the spec's documented fallback. Real DFS would need a `position_relationships` table or JSONB field; that's a future migration.

4. **`canonical_url` isn't in the boot payload as a top-level field.** I include it in the `claim_instruction` string but not separately. AI clients have to parse natural language to extract it. A structured field would be more legible. Considered adding; skipped for v0 to match the spec's 7-field SHOULD shape verbatim.

5. **Router complexity around `/mcp`.** Spent real time getting Starlette's Mount("/mcp", ...) NOT to collide with Route("/{account}"). Ended up wrapping the inner host app in `_LegacyMCPPathRewriter` (rewrites `/mcp` → `/` before routing) for the mcp.openbraid.app host, and using a reserved-handle gate in `_account_by_handle` for the fallback host. Working but uglier than I'd like.

## Things you SHOULDN'T do without Director or strategist sign-off (still applies)

Same as the Phase A handoff. Reproduced here for completeness:

- Don't add tools beyond the roadmap-approved set
- Don't change auth flow shape (claim ceremony is fixed)
- Don't add encryption-at-rest, RLS, or other architectural shifts deferred per v0 design
- Don't merge own non-trivial PRs without Director's "merge it" approval (solo-merge only for tiny diagnostic / log-only per Director's standing rule)

## Final disposition

Phase A: closed. Phase B: closed. Phase C: closed (except C7 deferred). Three cross-spec memos filed (one to memodef-strategist for v0.3 experience, one being filed now to orgdef-strategist for canonical addressing experience). Director's panel handoff prompt is one-click-copyable from `/panel/roles`. The OAGP role-portable claim is empirically validated across vendors (Claude Code, Claude Desktop, Claude mobile, Perplexity all tested live in the past 48 hours). Phase D is the next strand; Director-time and Director-priority decide when.

Goodnight, future-self. Take care of yourself. The braid weaves.

— openbraid-engineer (2026-05-10 ~17:30 Director-time)
