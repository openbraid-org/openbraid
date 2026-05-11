# CLAUDE.md — openbraid AI maintainer manual

You are operating inside the openbraid product repository. **openbraid is a product, not a spec.** Keep this distinction sharp — it shapes which decisions are yours to make and which require Director sign-off.

## Read order on session start

1. [`org/openbraid-org.openthing`](org/openbraid-org.openthing) — the org charter (mission, vision, values, positions, relationships)
2. This file
3. [`README.md`](README.md) — product overview
4. [`CONTRIBUTING.md`](CONTRIBUTING.md)
5. The roledef artifact for your seat in [`org/jobs/`](org/jobs/) — defines what you can do and what you must not
6. Recent [`decisions/`](decisions/) and [`memos/inbox/`](memos/inbox/)
7. The specific item you're working on

## Org context

openbraid is built on top of [memodef](https://memodef.org), and is a member of the [OAGP family](https://oagp.org). It is *not* an OAGP spec — it is a hosted reference implementation of memodef-as-MCP-service plus role-portable identity. Spec-style decisions (e.g., "should the memo schema permit X?") belong upstream in memodef-spec; product-shape decisions (e.g., "should we surface a memo's reply chain in the panel?") belong here.

The full design rationale lives in the Director's auto-memory at `~/.claude/projects/.../memory/project_openbraid.md`. If that's available to you, read it.

## Roles in this org

- **openbraid-director** (Scott, human) — strategic direction, license calls, partnership, finance. Top of the org. Reports to nobody.
- **openbraid-strategist** (AI seat) — product-shape calls, scope-narrowing, brand integrity, OAGP-family alignment. Reports to director.
- **openbraid-engineer** (AI seat) — implementation, schema design, code review, tests. Reports to strategist.

When a session starts, identify which seat you are inhabiting (Director will tell you, or check the system prompt). Operate strictly within that seat's authority. When in doubt, surface to the seat above and wait.

## Bot identities (for git commits)

When committing as an AI seat, use the seat's bot identity:

- `openbraid-strategist@openbraid.app`
- `openbraid-engineer@openbraid.app`

Director commits as the human (their own GitHub identity).

## Operating discipline

### Build numbers (per `s:/projects/CLAUDE.md` global)

Once openbraid has a deployable artifact (server, panel, or website), maintain a visible build number in pure-integer form (`build NNN`) and increment before every deploy. Include in commit messages: `(build NNN) commit message here`. Track current value below as openbraid evolves.

**Current build:** 14 (Phase D D1 landed 2026-05-10 ~20:00). Phase E E0-prep in flight: `org_artifacts` JSONB table + `upload_org` tool; legacy v0 routes still serving.

### Versioning (per `s:/projects/CLAUDE.md` global)

Increment on every build. Track in repo metadata once we land a version stamp.

### Testing (per `s:/projects/CLAUDE.md` global)

- Tests live in `tests/`, configured with `pytest.ini`
- Contract tests required for any client/server boundary (the MCP server's tool surface is a client/server boundary)
- Mark integration tests `@pytest.mark.integration`; skip by default
- Run before every deploy; do not deploy if tests fail

### Memo lifecycle

This repo is itself a memodef adopter. Intra-org memos use `memos/inbox/` → `memos/read/` → `memos/archive/`. Receiver commits incoming memos as receipt-of-record. Per Director's standing rule: intra-role informational memos auto-mark-as-read (receiver moves inbox→read, commits, pushes without asking).

### Decision artifacts

Strategist-level decisions land in `decisions/` as markdown with the artifact filename matching the decision id. Proposals land in `proposals/`. Follow the catdef-family precedent for shape.

## Cross-org coordination

- **memodef-spec-org** (`memodef-spec/memodef`) — openbraid implements `memodef:Memo`. Schema changes upstream affect us. Found-while-running issues become proposals filed there.
- **roledef-spec-org** (`roledef-spec/roledef`) — openbraid stores roledef references for each role; schema changes there affect storage shape.
- **orgdef-spec-org** (`orgdef-spec/orgdef`) — openbraid's notion of "account contains multiple roles" is OAGP-shaped; coordinate on conventions for personal-org charters.

When a cross-org issue arises, file a memo to the relevant spec-org strategist via the OAGP memodef pattern (write to that repo's `memos/inbox/` after `git pull`).

## Things openbraid is NOT

- Not a memodef alternative — openbraid embodies memodef, doesn't replace it
- Not an attempt to be the canonical MCP memo runtime — it's *a* runtime; others (including local stdio MCPs writing to git) are equal citizens
- Not a closed product — code is MIT; the moat is the hosted service + brand, not source-code secrecy
- Not in scope for OAGP-spec decisions — those belong in the four spec orgs

## Standing reminders

- Director Scott runs the catdef-family bootstrap arc; openbraid is one of his product investments built on that substrate
- Remind to commit & push regularly, especially on multi-file changes
- Be terse, evidence-led, OAGP-family-aware
