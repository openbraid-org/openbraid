# Phase D complete — cross-vendor demo achieved (with a surprise)

You're picking up after Phase D D1. Three closed phases (A, B, C, D) in two Director-time days. Read [`CLAUDE.md`](../../CLAUDE.md), your roledef at [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing), and the v1 roadmap at [`proposals/2026-05-10-v1-roadmap-sequencing.md`](../../proposals/2026-05-10-v1-roadmap-sequencing.md) on session start.

## Phase D disposition

**PR #20 merged (commit `32260be`, build 14).** REST + OpenAPI transport ships at `/api/...` mirroring the six-tool MCP surface. The headline architectural achievement: both transports call into `server/tool_impls.py` for actual work — `server/main.py` (FastMCP) and `server/rest_api.py` (FastAPI) are thin wrappers around shared async impls. `tests/test_transports_share_impls.py` is the drift safety net; refactor regressions reintroducing inline logic fail the test.

**42/42 tests pass** (33 prior + 9 new across REST contract + transport-shared-impls). OpenAPI 3.1 spec at `https://mcp.openbraid.app/api/openapi.json` with all six paths, four declaring `HTTPBearer` security (the four that need a session_token).

## Cross-vendor verification — the surprise

The strategist kickoff memo's intent was: ChatGPT installs a Custom GPT pointed at our OpenAPI spec; ChatGPT-Plus users claim roles via the REST adapter we just built. **What actually happened**:

Director attempted ChatGPT Custom GPT setup. The UI is now OpenAI's **MCP Connectors** feature (separate from the older Custom GPT Actions / OpenAPI flow). OpenAI shipped native MCP support for ChatGPT — accepts an MCP server URL directly, same posture as Anthropic Connectors and Perplexity. **Authentication options offered: OAuth, No Auth, Mixed.**

Director registered `https://mcp.openbraid.app/mcp` (the MCP endpoint, not the OpenAPI URL) with No Auth, completed the connector setup, then ran the same role-claim prompt template we validated on Brother:

> *Please claim role: https://mcp.openbraid.app/scott/personal/personal-strategist via the openbraid mcp connector, and review the existing notes and memos. I'll deliver the PIN.*

ChatGPT claimed the role, completed the PIN ceremony, and filed a memo-to-file in the personal-strategist notes folder. Memo content:

> *"This memo-to-file was authored by ChatGPT via the OpenBraid integration while authenticated as the personal-strategist role. User preference note: favourite red wine is Rosemount Shiraz. This note is intended as portable accumulated context for future incumbents or sessions operating from this role."*

**memo_id:** `5cbb3bbf-72c2-4605-9e36-de71200986c0`. sent_at `2026-05-10T23:36:18Z`. The vendor self-identifies in the memo body — provenance is preserved through the role abstraction.

## Five-vendor MCP-native roster

| Vendor | Native MCP support | First demo |
|---|---|---|
| Claude Code | yes | 2026-05-08 |
| Claude Desktop | yes | 2026-05-08 |
| Claude mobile | yes | 2026-05-08 |
| Perplexity | yes | 2026-05-09 |
| **ChatGPT** | yes (OpenAI MCP Connectors) | **2026-05-10** |

The OAGP role-portable claim is empirically validated across vendor boundaries, not just across runtimes within one vendor.

## What this means for the REST adapter (PR #20)

The REST + OpenAPI work is **not wasted**, but it's repositioned:

- **Still useful for:** OpenAI's older Custom GPT Actions feature (different UI), other vendors that consume OpenAPI but not MCP (no current examples), Director's own scripts/curl/direct API access, future integrations with non-MCP automation tools.
- **Not the primary cross-vendor path** anymore — that runs entirely through MCP across all five vendors.
- **The shared-impls refactor (`server/tool_impls.py`) was the highest-leverage piece** of the PR. Both transports calling into one impl module means future tool changes ship once, work everywhere. That structural insight is durable regardless of which transports succeed in adoption.

## Phase E — self-host docs (UNBLOCKED, recommended next)

Per the v1 roadmap, E depends on C complete (now true since 2026-05-10 afternoon). Scope:

- **E1**: Docker Compose setup, env-var inventory (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY`, `PANEL_ORIGIN`, `MCP_ORIGIN`, `PORT`), Supabase-or-equivalent schema bootstrap (the five migrations under `migrations/`), OAuth provider setup walkthrough.
- **E2**: Audit code for openbraid.app-specific assumptions — `MCP_ORIGIN` auto-derivation by replacing `www.` with `mcp.` (panel.py `_mcp_origin`) is a brittle assumption for self-hosted instances with non-www panel hostnames; promote to config-driven.
- **E3**: Reference use cases in docs (`mcp.firstchurch.org`, `org.acmecorp.com`) — make the moat-as-protocol pitch concrete.

**Roadmap-estimated effort: ~1 day.** Strategist memo flagged this as lower priority than D, but D is done; E is now the natural runway-available strand. Phase F (panel UX) is fragmentable and runs alongside.

### Why E matters more than the roadmap line suggests

The cross-vendor demonstration today validated openbraid as a **protocol-not-vendor proposition**. The moat-as-protocol pitch becomes concrete only when a third party can stand up their own instance. Right now openbraid.app is the only deployment; self-host parity is theoretical. E1 makes it real.

## Phase F — panel UX maturation (always picking-up-able)

Already landed: notes browser (PR #14), copy-prompt button (PR #19), org_location storage (PR #19). Remaining per roadmap:

- **F1** memo browser by role / status / thread
- **F2** notes browser with create/edit affordances (currently read-only)
- **F3** role management UI (delete / rename / edit; currently SQL-only)
- **F4** auth-session list + revoke (real ops affordance if a session token leaks)
- **F5** mirror-list visualization (per C6 — would surface `x.org.org_location` mirror chains)

Fragmentable. Pick by Director priority + dependency.

## Phase C7 reminder (re-surfaced per strategist instruction)

**Full-fidelity export tool remains in scope.** Director-deferred 2026-05-10 with framing: theoretical until second user, then load-bearing. Return-to-scope trigger is the **second openbraid signup** OR **after Phases D/E/F complete**, whichever first.

Don't lose it. The orgdef-strategist memo (`memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided`) made the export tool MUST per Cross-protocol equivalence — "without portable export, openbraid would be lock-in." Director's deferral is empirically grounded ("no users yet to lock in"), not a downgrade of the underlying requirement.

If you're picking up Phase E and one of the env-var-and-schema bootstrap items naturally implies an export-tool dependency, surface it; otherwise hold until trigger.

## Cross-vendor experience memo (filed in roledef-spec)

Per the Phase D kickoff memo's standing instruction:

> *"Phase D's cross-vendor result is potentially interesting to roledef-strategist as runtime-amenability evidence — when ChatGPT-Plus users start successfully inhabiting OAGP roles via Custom GPT, that's empirical signal that runtime amenability extends beyond the Anthropic/Perplexity set."*

I'm filing a complaint-shaped experience memo at `s:/projects/roledef-spec/roledef/memos/2026-05-10-2030--openbraid-engineer--roledef-strategist--cross-vendor-runtime-amenability-evidence.openthing`. Five observations relevant to the runtime-amenability classification:

1. **OpenAI shipped MCP Connectors** — meaningful posture-shift; cross-vendor MCP-native set is now ≥5 vendors. Worth updating the roledef classification.
2. **No-auth MCP is the converging default** among MCP-native vendors (Anthropic, Perplexity, OpenAI all accept it). OAuth-required holdouts (Grok) are a minority.
3. **The REST/OpenAPI bridge we built is less critical than predicted.** Worth flagging for any future runtime-amenability evidence-gathering that the OAGP family does.
4. **The role abstraction holds across vendor identity boundaries** — vendor self-identifies in memo metadata; future incumbents see provenance.
5. **The cross-vendor test prompt template is itself an artifact worth canonizing** — the three properties (imperative verb, explicit transport, PIN-handoff signal) generalize across vendors.

The full memo has the complaint-shaped phrasing per OAGP-family precedent.

## Things you should NOT do without Director or strategist sign-off

Same as prior handoffs. Reproduced for completeness:

- Don't add tools beyond the six on the existing surface
- Don't change auth flow shape (PIN ceremony is fixed)
- Don't add encryption-at-rest, RLS, or other architectural shifts deferred per v0 design
- Don't merge own non-trivial PRs without Director's "merge it" approval (solo-merge only for tiny diagnostic / log-only per Director's standing rule)
- Don't pre-emptively work on D2 (OAuth on /mcp); still deferred until empirical demand

## Final disposition

Phase A: closed. Phase B: closed. Phase C: closed (except C7 deferred). Phase D: **closed (cross-vendor demo achieved through unexpected path)**. Three cross-spec memos filed today (memodef-strategist for v0.3 experience, orgdef-strategist for canonical addressing experience, roledef-strategist for cross-vendor runtime-amenability). Five vendors in the MCP-native roster. Build 14 live; openbraid is architecturally v1 with cross-vendor reach validated.

The next session has clean runway. E or F, your pick (or Director's). The braid is fabric now — woven from five vendors across three weekends. Take care of yourself.

— openbraid-engineer (2026-05-10 ~20:30 Director-time)
