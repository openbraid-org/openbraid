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

Required env vars (will land in a later session): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. None are required for the current stubbed scaffold.
