# Handoff after server scaffold — Railway smoke, then storage wiring

You're picking up the openbraid-engineer seat after session 1 (2026-05-08). Read [`CLAUDE.md`](../../CLAUDE.md) and [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing) first if you haven't.

## State at session-1 close

- **PR #1** (initial schema) — merged on 2026-05-08 (commit `2ae4e87`). Director confirmed clean apply against a fresh Supabase project.
- **PR #2** (server scaffold + contract tests + FastMCP wiring) — open against `main`, awaiting strategist (vacant) / director review and merge. **NOT MERGED.** Do not start storage-wiring work until #2 is merged or redirected.
- **Tests** — 14/14 pass on `engineer/server-scaffold`. Server boots locally; `curl http://127.0.0.1:$PORT/mcp` returns the expected `406 Not Acceptable` for non-MCP HTTP.

## Director status as of close-of-session

Director said "I'm standing by to create the project in Railway when needed." That was authorization to *prepare* the deploy artifacts (Procfile + entry point — both in #2). The actual Railway provisioning is Director's call; don't proceed without it.

Same status applies to Supabase: schema is merged, but the actual project provisioning (creation, env-var population) is Director's.

## Next strand — two halves

### Half A: Railway smoke deploy (Director-blocked)

**Wait for Director to:**
1. Create the Railway project pointed at `openbraid-org/openbraid` and the merged `main` branch.
2. Confirm the deploy boots and the `/mcp` endpoint responds (the same 406-on-bare-curl signal proves the framework is running).
3. Optionally: hook the public URL into a custom domain (e.g., `mcp.openbraid.app`) — Director's call.

**Then your work:**
- If the deploy fails on Railway, debug from the Railway logs. Common Python-on-Railway gotchas: missing `requirements.txt` (we use pyproject.toml — Railway 2024+ Nixpacks auto-detects this; if it doesn't, add a `requirements.txt` shim), `$PORT` env var (handled in [`server/main.py`](../../server/main.py)), Python version pin (consider adding `.python-version` or `python-version` in `pyproject.toml` if Nixpacks picks the wrong one).
- Add a `/healthz` HTTP route to `server/main.py` if Railway's health check needs one. FastMCP's `http_app()` exposes the underlying Starlette app; you can mount custom routes on it.

### Half B: Storage wiring (Supabase) — the real work

Once Half A is green, replace each tool's `NotImplementedError` body with real Supabase calls. **This is the substantial PR.** Suggested approach:

1. **Add `supabase` (Python client) to runtime deps in `pyproject.toml`.** Flag in your PR description per the dependency-flagging guardrail.
2. **Create `server/db.py`** — module owning the Supabase client, with helpers per table. Connection comes from env: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. The MCP server holds the **service role key** so it can bypass RLS — that's intentional for v0 (no RLS yet).
3. **Implement tools in this order** (each gets its own commit, all in one PR):
   - `claim_role` first — generates a 9-digit PIN, inserts into `pin_challenges`, returns `challenge_id` + `expires_at`. *This is testable end-to-end without any other tool working.*
   - `auth_with_pin` — atomic-update `pin_challenges` SET `used_at = now()` WHERE `id = challenge_id AND pin = ? AND used_at IS NULL AND expires_at > now()` RETURNING `role_id`. The atomicity is the security gate; if zero rows updated, reject. Then insert into `auth_sessions` and return the token.
   - `send_memo`, `list_inbox`, `read_memo`, `mark_read` — each requires a valid `session_token` lookup (query `auth_sessions` for live session, get `role_id`, then operate on `memos`).
4. **Tests** — for each tool, add behavioral tests in `tests/test_<tool>.py` marked `@pytest.mark.integration`. Use a Supabase test schema or a docker-postgres fixture so they don't pollute the live DB. Contract tests in `test_tool_contracts.py` keep passing throughout.
5. **Update the contract test** — when stubs become real, the `test_stubs_raise_not_implemented` test must be deleted or rewritten (it intentionally fails when stubs go away — that's a feature, not a bug).

### Useful Supabase-specific notes for v0

- The service role key is sensitive — never log it, never echo it in error messages, never put it in test fixtures. Read from env only.
- For the atomic PIN burn, the `update ... where ... returning` pattern from postgrest is the cleanest:
  ```python
  result = supabase.table("pin_challenges").update(
      {"used_at": "now()"}
  ).eq("id", challenge_id).eq("pin", pin).is_("used_at", "null").gt("expires_at", "now()").execute()
  ```
  Postgrest will return zero rows if any condition fails — your authentication failure case.
- Supabase Realtime (for the panel's live PIN inbox) is a **panel concern**, not a server concern. Don't touch it from the MCP server.

## What you must NOT do (per roledef + kickoff memo)

- Do **not** add a seventh MCP tool, remove a tool, or rename one. Tool surface is fixed.
- Do **not** change the auth flow shape. Inverse-sncro PIN ceremony is fixed.
- Do **not** pick the panel stack (Next.js vs HTMX). Strategist owns that — and the strategist seat is vacant, so until staffed, surface to Director.
- Do **not** add encryption-at-rest. Deferred per kickoff memo.
- Do **not** merge your own PRs. Director or strategist reviews.
- Do **not** introduce dependencies without flagging them in the PR description (license, supply chain, maintenance).

## What's been verified about the toolchain (so you don't have to re-discover)

- **fastmcp 3.2.4** is what gets installed; it works.
- **`@mcp.tool()`** decoration leaves the bare async function callable — useful for direct unit testing of tool bodies before storage exists.
- **`mcp.list_tools()`** returns a list of `FunctionTool` objects with `.name`, `.description`, `.parameters` (a JSON-Schema dict with `properties` and `required`). The contract tests use this.
- **`pytest-asyncio` mode=auto** means you don't need `@pytest.mark.asyncio` on every async test — see `pytest.ini`.
- **Bot-identity commits**: `git -c user.email=openbraid-engineer@openbraid.app -c user.name=openbraid-engineer commit -m "..."`. Keep using per-commit overrides; don't mutate `~/.gitconfig` or repo-level `user.email`.
- **`(build NNN)` prefix** still pre-deploy. After Half A lands and there's a Railway deploy, `CLAUDE.md`'s "Current build" header in [`CLAUDE.md`](../../CLAUDE.md#L46) must be updated and commit messages start carrying `(build 1)`, `(build 2)`, etc.

## Final disposition

Ending session 1 cleanly:
- Schema merged.
- Server scaffold PR open and green.
- Two memos in `read/` (the kickoff and the inter-strand handoff).
- This memo filed, addressing future-engineer.

Good braiding.

— openbraid-engineer (session 1, 2026-05-08)
