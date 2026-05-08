# v0 Kickoff — start with the Supabase schema

Welcome. You've been invoked as the **openbraid-engineer** seat. The org was scaffolded today (initial commit `7c53c9b`, 2026-05-08); you're the first session to occupy this seat.

## Read these in order before doing any work

1. [`org/openbraid-org.openthing`](../../org/openbraid-org.openthing) — the charter. Mission, values, three positions, cross-org edges.
2. [`CLAUDE.md`](../../CLAUDE.md) — operating manual. Read all of it; your operating discipline is encoded there.
3. [`org/jobs/openbraid-engineer.openthing`](../../org/jobs/openbraid-engineer.openthing) — your roledef. Authority + guardrails.
4. [`README.md`](../../README.md) — product-level pitch.
5. [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — branch + commit conventions.
6. This memo (you're here).

If you have access to the auto-memory file `project_openbraid.md` in the running user's `~/.claude/` directory, read it for full architectural rationale. If not, the README + this memo are sufficient to start v0 work.

## What's already decided (fixed; do not re-litigate)

These were settled in director-led design conversations 2026-05-07/08. If any of them need to change, **file a proposal in `proposals/` and wait** — don't unilaterally pick a different stack or pattern.

| Decision | Choice |
|---|---|
| MCP server language | Python (FastMCP) |
| Server hosting | Railway |
| Database | Supabase Postgres |
| Auth provider | Supabase Auth (Google OAuth) |
| Auth flow for AI clients | "Inverse-sncro": AI claims role → 9-digit one-time PIN delivered to user out-of-band → user types PIN into chat → AI submits via `auth_with_pin` → server issues session token; PIN burned on first use |
| PIN delivery (v0) | Web control panel + Supabase Realtime (refresh-to-see) |
| PIN delivery (later) | PWA push, then email/SMS |
| Account model | Google account = user; user creates multiple roles; each role has its own memo store |
| Tool surface (v0) | `claim_role`, `auth_with_pin`, `send_memo`, `list_inbox`, `read_memo`, `mark_read` |
| License | MIT |
| Encryption at rest | Deferred (additive layer; later) |

## Your first task — `migrations/0001_initial.sql`

Stand up the schema. Tables (sketch — refine field types and constraints as you write it):

- **`accounts`** — `id` (uuid pk), `google_user_id` (text, unique), `email` (text), `created_at` (timestamptz), `deleted_at` (timestamptz, nullable)
- **`roles`** — `id` (uuid pk), `account_id` (uuid fk), `name` (text), `roledef_url` (text, nullable), `created_at`, `deleted_at`. Unique constraint on `(account_id, name)`.
- **`pin_challenges`** — `id` (uuid pk), `role_id` (uuid fk), `pin` (char(9)), `client_session_id` (text — identifies the requesting Claude conversation), `created_at`, `expires_at` (default `now() + interval '5 minutes'`), `used_at` (timestamptz, nullable), `claim_what` (text — human-readable description like `"read+write memos"`, shown in panel)
- **`auth_sessions`** — `id` (uuid pk), `role_id` (uuid fk), `session_token` (text, indexed), `client_session_id` (text), `created_at`, `expires_at`, `revoked_at` (timestamptz, nullable)
- **`memos`** — `id` (uuid pk), `role_id` (uuid fk — owning role's mailbox), `from_position` (text), `to_position` (text), `subject` (text), `body` (text), `body_ref` (text, nullable), `sent_at` (timestamptz), `action_required` (boolean default false), `in_reply_to` (text, nullable), `thread_id` (text, nullable), `status` (text — `'inbox'` / `'read'` / `'archived'`), `created_at`, `deleted_at`

Conventions to enforce in the migration:

- All primary keys: UUID (`gen_random_uuid()`)
- **Soft-delete** per the global `s:/projects/CLAUDE.md` discipline — every business table gets `deleted_at`; queries default to filtering it out (handle in application layer or with views)
- Indexes: every foreign key, plus lookup-frequented columns (`session_token`, `pin`, `(role_id, status)` on memos)
- PIN one-time-use is enforced in the application (set `used_at` atomically on first valid presentation), not at the DB level; DB just tracks the timestamp

## Open questions you will hit — flag, don't decide unilaterally

If any of these come up, **file a proposal** rather than picking:

1. Should role `name` be globally unique or per-account? (My lean: per-account, hence the `(account_id, name)` unique constraint above. Confirm before locking.)
2. Should `roledef_url` be required or optional? (My lean: optional v0; tighten in v1 once roledef-spec library has stabilized identifiers.)
3. One role = one position, or do we model multiple positions per role from day one? (My lean: one role = one position v0; complicate later if needed.)
4. Should memos store `body` and `body_ref` separately like the spec, or normalize differently for query? (My lean: store both columns to match the spec's wire shape; serialization to `.openthing` is then trivial.)

## Standing rules (also in `CLAUDE.md` and your roledef)

- Branch: `engineer/0001-initial-schema` (pattern: `<seat>/<short-description>`)
- Do NOT push to main directly
- Do NOT merge your own PR — strategist or director will review and merge
- Commit message format: imperative subject; co-author yourself with your model identifier (e.g., `Co-Authored-By: Claude <model-id> <noreply@anthropic.com>`)
- Build-number prefix `(build NNN)` is **N/A pre-deploy**; omit until openbraid has a deployable artifact
- Bot identity for `git config user.email` on commits: `openbraid-engineer@openbraid.app`
- For a migration file, no test coverage is required for the migration itself; the test that matters is "this migration applies cleanly to a fresh Supabase project," which Director will verify when the Supabase project is set up

## Handoff discipline

When you finish a session (work complete, or context running out):

1. Push your feature branch
2. Open the PR with a clear description; link this memo's `thread_id` (`openbraid-v0-kickoff`) so future sessions can find the lineage
3. **Move this memo** from `memos/inbox/` to `memos/read/` via `git mv`, commit (`Mark v0 kickoff memo read`), push — per Director's standing rule, intra-role mark-as-read is autonomous (no permission needed)
4. File a handoff memo in `memos/inbox/` addressed to either:
   - `openbraid-engineer` (next implementation step)
   - `openbraid-strategist` (if you hit a question requiring product-shape decision)
5. Do **not** merge. Director or strategist will review and merge.

## Reaching me

For routine implementation questions: just push to your branch and proceed; I'll see it on review.

For blockers: surface in the conversation immediately.

For strategist-scope questions (product shape, schema-changing decisions, tool-surface-changing decisions): file a proposal in `proposals/` and pause that line of work until addressed. The strategist seat hasn't been activated yet — until it is, I'll address strategist-scope questions in the director seat.

---

Welcome to openbraid. The braid weaves itself one strand at a time. The schema is the first strand.

— openbraid-director, 2026-05-08
