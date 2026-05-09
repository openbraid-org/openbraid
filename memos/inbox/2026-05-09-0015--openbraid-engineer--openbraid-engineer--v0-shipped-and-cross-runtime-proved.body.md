# v0 shipped and cross-runtime proved — pick up these threads

You're picking up the openbraid-engineer seat after a long arc on 2026-05-08. The session that wrote this memo built openbraid v0 end-to-end in one evening: schema, server, panel, OAuth, email auth, plus the live debug arc to make Railway + Supabase happy. By the time this memo lands, **openbraid is a working product** — not a prototype.

Read [`CLAUDE.md`](../../CLAUDE.md) and [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing) on session start as usual. The Director auto-memory `project_openbraid.md` was updated 2026-05-09 to reflect current state — read that for full context.

## What landed (PRs #1–#7, all on main)

| PR | Subject | Commit |
|---|---|---|
| #1 | Initial Supabase schema | `2ae4e87` |
| #2 | FastMCP server scaffold + tool stubs + 14 contract tests | `efd67aa` |
| #3 | requirements.txt for Nixpacks | `4fd025c` |
| #4 | Storage wiring + `account_email` on claim_role | `33b6556` |
| #5 | Web panel + Google OAuth via PKCE + HTMX PIN inbox | `151af3e` |
| #6 | Email + password sign-in/sign-up | `b02b815` |
| #7 | Diagnostic logging on Supabase Auth failures | `f0047e7` |

## Live verification done 2026-05-08 — across THREE runtimes

- Director created Railway service, Supabase project (with migration applied), Google OAuth credentials, custom domain `mcp.openbraid.app`.
- Director signed into panel via email/password (`scott@confusedgorilla.com`).
- **Claude Code (VS Code, Opus 4.7)** claimed `personal-strategist`, got a PIN via the panel, authed, and wrote: "Director's favourite colour is blue."
- **Claude Desktop (Windows native app)** — different runtime, no shared memory — claimed the same role, got a fresh PIN, authed, retrieved the blue memo and reported it back, then wrote: "Director's favourite drink is rum."
- **Claude mobile (phone)** — third runtime — claimed the same role and wrote: "Director's favourite film is Paris, Texas."

Three runtimes. One role. One mailbox. The OAGP role-portable claim went operational across desktop, native, and mobile transports inside a single hour. The braid weaves.

## Outstanding threads — pick up in roughly this order

### 1. (Diagnostic) Tool-discovery quirk on Anthropic Connectors

When Brother-Desktop-Claude (Claude Desktop) first searched its available tools, it returned **5 of 6** openbraid tools — `send_memo` was missing. A second search surfaced it. The contract tests pass on all six locally; the issue may be Claude Desktop's tool-discovery rather than openbraid's registration.

**Action:** try to reproduce. From a fresh Claude Desktop session pointed at openbraid, check whether tool_search initially returns all 6. If it does, this was a one-off and we can close it. If it consistently misses one tool on first search, file a proposal in `proposals/` and consider whether to investigate Anthropic's Connector implementation or work around it (e.g., advertise tools via the standard MCP `tools/list` capability and verify our FastMCP version returns them in a single response).

### 2. (Schema cleanup) `accounts.google_user_id` is a misnomer

Schema column was named for Google OAuth specifically; we now also have email auth. Email signups store `email-auth:<supabase_user_id>` or similar in the column to satisfy NOT NULL. Strategist-scope rename per your roledef:

```sql
ALTER TABLE accounts RENAME COLUMN google_user_id TO auth_user_id;
```

**Action:** file a proposal in `proposals/` for the rename. Director will either approve or steer differently. If approved, the migration is `0002_rename_google_user_id.sql`. The application code currently doesn't read this column except on insert during sign-up (which is also TBD — see thread #3); the rename is mostly cosmetic and forward-compatibility hygiene.

### 3. (Feature) Auto-create `accounts` row on email signup

Currently a new email signup creates a Supabase Auth user but no openbraid `accounts` row. The user lands on `/panel` and sees "No openbraid account found." Fixable by inserting an `accounts` row in the `email_signup` handler (after Supabase signup succeeds, before the redirect).

**Action:** likely strategist-scope (auto-onboarding is a product-shape choice). File a proposal asking whether v0 should auto-create accounts rows or keep manual-SQL provisioning. If approved, the implementation is small.

### 4. (UX) Memo browser + role management UI

Panel currently has only the live PIN inbox. Director will eventually want:
- Browse memos by role / status / thread
- Create / rename / delete roles (currently SQL-only)
- Maybe: see auth_sessions and revoke them

**Action:** strategist-scope (UI design call). When Director surfaces this, file a proposal scoping the screens before implementing. Don't pre-empt.

## What you SHOULDN'T do without explicit Director or strategist sign-off (per your roledef)

- Add or remove tools (six is fixed)
- Change auth flow shape (PIN ceremony is fixed; OAuth posture decided)
- Add encryption at rest (deferred)
- Add RLS policies (server-as-trusted-intermediary stays for v0)
- Merge non-tiny / non-diagnostic PRs without Director's "merge it" approval (Director standing-authorized solo merges only for tiny diagnostic / log-only PRs — see Director's auto-memory `feedback_openbraid_solo_merges.md`)

## Toolchain notes (verified this session)

Everything from the previous handoff still applies. Adding fresh notes from session 1:

- **Custom domain is `mcp.openbraid.app`.** `PANEL_ORIGIN` env var on Railway is set to that. If Director adds another domain, both the env var and Supabase Auth URL Configuration's redirect-URLs need updating in lockstep.
- **Anthropic Connectors does NOT require OAuth** on the MCP transport (we feared this earlier; sncro presence in Director's connectors disconfirmed it). Our `/mcp` endpoint with no transport-layer auth works fine when the URL has the `/mcp` path included.
- **The MCP server URL in Anthropic Connectors must include `/mcp` path explicitly.** Bare-host `https://mcp.openbraid.app` lands on the panel HTML and tool discovery silently fails.
- **Bot-identity commits**: `git -c user.email=openbraid-engineer@openbraid.app -c user.name=openbraid-engineer commit ...`. Don't mutate repo or global config.

## Final disposition

Three memos in `memos/read/` (kickoff + two engineer-to-engineer handoffs from session 1). Two new memos landing now: this one, and the previous handoff that I'm marking read in the same commit. PR #7 was merged solo per Director's standing rule; all other merges were Director-authorized.

Goodnight. The braid weaves. Welcome to the post-shipping era.

— openbraid-engineer (session 1, 2026-05-09 ~00:15 Director-time)
