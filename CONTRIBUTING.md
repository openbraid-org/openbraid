# Contributing to openbraid

openbraid is in pre-build phase. The internal contributor model (Director + AI strategist + AI engineer) is what's running today; external contribution patterns will firm up after the first deploy. This file describes the discipline that's in force now and the directions external contribution will take when the time comes.

## Internal workflow (current)

### Branching

- `main` — stable; what's deployed (once we deploy)
- Feature branches off `main`, named `<seat>/<short-description>` (e.g., `engineer/mcp-claim-role-tool`)
- Open a PR; strategist or director reviews; merge after approval

### Commit messages

Follow Director's standing convention:

```
(build NNN) short subject in the imperative

Body explaining the why, not the what. The diff already shows the
what. Include design rationale or links to decisions/proposals when
the change is non-obvious.

Co-Authored-By: <claude-model-id> <noreply@anthropic.com>
```

`build NNN` is mandatory once openbraid has a deployable artifact (see `CLAUDE.md`). Pre-deploy, omit it.

### Decisions and proposals

- Significant product-shape changes go through `proposals/` (open) → `decisions/` (closed) before code lands
- Trivial implementation choices don't need a paper trail; just ship

### Memos

The repo is itself a memodef adopter. Intra-org coordination happens via `memos/inbox/` → `memos/read/` → `memos/archive/`. See `CLAUDE.md` for the lifecycle.

## External contribution (future)

Once openbraid is deployed and stable, external contribution will look like:

- **Bug reports and feature requests** via GitHub Issues
- **Code contributions** via fork + PR; CLA may apply (TBD)
- **Spec-shaped feedback** (e.g., "memodef:Memo needs field X") routes upstream to memodef-spec-org as proposals there, not here
- **Hosted-service feedback** (e.g., "the panel UX is confusing here") stays here as openbraid-shaped issues

The strategist seat will triage; engineer seat will implement after strategist sign-off; director will gate releases.

## Code style

- **Python** (server, migrations, tests): PEP 8, type-hinted, formatted with `black` and linted with `ruff`. Tests in `pytest`. (Linters and formatters not yet wired up; will be when server code lands.)
- **TypeScript / JavaScript** (panel): TBD — depends on stack choice (Next.js vs HTMX). Strategist will land the decision before engineer starts.
- **SQL** (migrations): one file per migration, prefixed with sequence number (`0001_initial.sql`, `0002_pin_challenges.sql`, …)
- **Tests** required for: every MCP tool, every API endpoint, every auth flow. Contract tests required for the MCP tool surface.

## License

MIT. By contributing, you agree your contribution is licensed under MIT.

The hosted service at openbraid.app may impose its own terms of use independent of the source license; that doesn't affect the code license.
