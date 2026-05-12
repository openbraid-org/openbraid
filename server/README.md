# openbraid MCP server

v0 scaffold. The six tools are registered but raise `NotImplementedError`. Storage and auth land in follow-on sessions.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows; use `source .venv/bin/activate` on Unix
pip install -e ".[dev]"
python -m server.main           # streamable-HTTP on :8000
```

For local MCP-client integration testing via stdio:

```bash
FASTMCP_TRANSPORT=stdio python -m server.main
```

## Run tests

```bash
pytest
```

Contract tests verify every tool registers with the right name and parameter schema. They're the gate that catches "tool got renamed but client wasn't updated" regressions.

## Run on Railway

The repo's [`Procfile`](../Procfile) entry `web: python -m server.main` is the deploy command. Railway provides `$PORT`; the server binds `0.0.0.0:$PORT` over streamable-HTTP transport.

## Environment variables

Required:

- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_ANON_KEY` — Supabase anon key (used by the auth/login flow)
- `SUPABASE_SERVICE_KEY` — Supabase service-role key (used by the DB layer)
- `PANEL_ORIGIN` — public origin of the panel (e.g. `https://www.openbraid.app`); used for OAuth redirects and canonical position URLs

Optional:

- `MCP_ORIGIN` — public origin of the MCP host; defaults to `PANEL_ORIGIN` with `www.` swapped for `mcp.`
- `PANEL_SESSION_TTL_SECONDS` — panel session-cookie lifetime in seconds; default `604800` (7 days). Should be `<=` the Supabase JWT expiry configured on the Authentication settings page, or sessions will appear logged in but tool calls will 401.
- `FASTMCP_TRANSPORT` — transport for the MCP server; default `streamable-http`. Set to `stdio` for local MCP-client integration testing.
- `PORT` — bind port for streamable-HTTP transport; Railway sets this automatically.
