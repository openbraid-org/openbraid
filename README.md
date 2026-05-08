# openbraid

**Persistent memory and role-portable identity for stateless AI sessions.**

openbraid is a hosted MCP service that lets a Claude session — Desktop, mobile, or web — claim a named role, authenticate via a one-time PIN, and operate against a persistent memo store tied to that role. Multiple sessions across multiple devices and model versions can inhabit the same role; the role's memos are the continuity.

The metaphor is the name: a braid is multiple strands twisted into one continuous thread. openbraid weaves stateless conversations into a continuous identity.

## Status

**Pre-build.** Architecture decided 2026-05-08; scaffold landed; v0 implementation pending. See [`org/openbraid-org.openthing`](org/openbraid-org.openthing) for the org charter and [`org/jobs/`](org/jobs/) for the role roster.

## What's coming in v0

- **MCP server** (Python / FastMCP, hosted on Railway) exposing `claim_role`, `auth_with_pin`, `send_memo`, `list_inbox`, `read_memo`, `mark_read`
- **Storage** in Supabase (Postgres + Auth via Google OAuth)
- **Web control panel** at openbraid.app — live PIN-request inbox, role management, memo browser
- **Auth model** — "inverse sncro": Claude claims a role; openbraid generates a 9-digit one-time PIN and delivers it out-of-band to the user (live web panel in v0, push/email/SMS later); the user types the PIN into the conversation; subsequent tool calls are authorized via session token

See [`CLAUDE.md`](CLAUDE.md) for the AI-maintainer operating manual and the project memory at `~/.claude/projects/.../memory/project_openbraid.md` for the full design rationale.

## Relationship to OAGP

openbraid is an **implementation**, not a spec. It implements the [`memodef:Memo`](https://memodef.org) content type and embodies [orgdef](https://orgdef.org)'s claim that role incumbents can be portable AI sessions. It sits in the [Open Agentic Governance Pattern](https://oagp.org) family alongside the four specs (catdef, roledef, orgdef, memodef), the way `catdef.org`'s Cloudflare Worker sits alongside `catdef-spec`.

Postgres rows in openbraid serialize to `.openthing` for archival into git-based recipients, so memos written via openbraid can travel into the broader OAGP ecosystem.

## Repository layout

```
openbraid/
├── org/                      ← orgdef charter + roledef references
│   ├── openbraid-org.openthing
│   └── jobs/
│       ├── openbraid-director.openthing
│       ├── openbraid-strategist.openthing
│       └── openbraid-engineer.openthing
├── memos/                    ← intra-org AI-to-AI memos (memodef-style)
│   ├── inbox/
│   ├── read/
│   └── archive/
├── decisions/                ← strategist decision artifacts
├── proposals/                ← change proposals
├── server/                   ← MCP server code (Python/FastMCP) — pending
├── panel/                    ← web control panel — pending
├── migrations/               ← Supabase schema — pending
└── tests/                    ← pytest test suite — pending
```

## License

MIT. See [`LICENSE`](LICENSE).

The hosted service at openbraid.app may impose its own terms of use independent of the source license; the code is MIT regardless.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). v0 is being built by the seated engineer and strategist; external contribution patterns will firm up after the first deploy.
