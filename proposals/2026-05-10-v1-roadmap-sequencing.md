# v1 roadmap sequencing

**Disposition:** Director-ratified in design conversation 2026-05-10. Proposed by openbraid-strategist (informally seated; formal claim ceremony deferred per Director instruction pending Phase C).
**Filed:** 2026-05-10 by openbraid-strategist
**Origin:** Synthesis of three inputs landing 2026-05-08 through 2026-05-10:
1. Engineer→engineer "v0 shipped" handoff (`memos/inbox/2026-05-09-0015--*v0-shipped*`) — outstanding threads from session 1
2. Engineer→strategist "cross-vendor reach" memo (`memos/inbox/2026-05-09-0930--*cross-vendor-reach*`) — strategist-pending decisions on ChatGPT and Grok
3. orgdef-strategist→openbraid-strategist "canonical OAGP position addressing" cross-spec memo (`memos/inbox/2026-05-10-1000--*canonical-oagp-position-addressing*`) — orgdef commit `ba004ca`, foundational architectural shift
4. memodef v0.3 proposal (`memodef-spec/memodef/proposals/2026-05-10-memos-to-file-and-notes-folder.md`) — strategist-pending; awaits Director ratification upstream

**Schema impact:** none on memodef/orgdef; openbraid-internal schema changes per phase.

## Summary

Sequence v1 work into six phases (A–F). Phase A clears outstanding session-1 debt. Phases B and C are the two scope expansions surfaced by recent OAGP-family decisions; Phase B (memos-to-file) is smaller and unlocks role-portable continuity sooner; Phase C (canonical addressing) is the bigger architectural shift but reshapes the auth/URL surface, so it gates Phases D and E. Phase D (cross-vendor reach) and Phase E (self-host readiness) follow Phase C. Phase F (panel UX maturation) is fragmentable and runs alongside whichever phase needs UI affordances next.

## Sequencing principles

1. **Things downstream work depends on go first.** Canonical addressing (Phase C) changes the URL space and the claim ceremony; cross-vendor REST (Phase D) and self-host story (Phase E) both depend on the URL space being settled.
2. **Auth-surface rewrites done as rarely as possible.** Each rewrite risks breaking working sessions across runtimes. Batch all changes that touch the auth flow into one well-tested wave (Phase C C5).
3. **Role-portable continuity sooner rather than later.** The openbraid thesis is "the role is the seat, not the runtime." Memos-to-file (Phase B) is the missing piece that makes successive incumbents inherit accumulated context without per-handoff memo overhead.
4. **Cleanups clear the deck.** Don't pile new architecture on top of `google_user_id` and unhandled tool-discovery quirks; finish session-1's open threads first.
5. **Director-action batches.** Group migrations, ratifications, and external setup so Director isn't interrupted on every phase.

## Phase A — Cleanup

| # | Item | Source | Gating | Director call |
|---|---|---|---|---|
| A1 | Investigate Claude Desktop tool-discovery quirk (5 of 6 tools surfacing on first search). Reproduce; close as one-off if not reproducible; file proposal if persistent. | engineer→engineer handoff thread #1 | None | Solo-merge if log-only finding (per `feedback_openbraid_solo_merges.md`) |
| A2 | Schema rename `accounts.google_user_id` → `auth_user_id`. Migration `0002_rename_auth_user_id.sql`. Application code updated where it reads/writes the column. | engineer→engineer handoff thread #2 | None | Director-approved directionally 2026-05-10; full PR review for the migration |
| A3 | Auto-create `accounts` row on email signup (after Supabase Auth signup succeeds, before the `/panel` redirect). Removes the manual SQL provisioning step. | engineer→engineer handoff thread #3 | None | Director-approved directionally 2026-05-10; full PR review |

**Estimated effort:** half a day total (engineer self-paced).
**Phase exit criterion:** A2 and A3 PRs merged; A1 closed (either as not-reproducible or with follow-up issue filed).
**Hand-off:** when Phase A complete, file handoff memo with Phase B status (Director-ratified-yet?) and either proceed to Phase B or stand by for memodef v0.3 ratification.

## Phase B — Memos-to-file (memodef v0.3 features)

The role-portable continuity unlock. Bounded scope; openbraid becomes implementation #1 of memodef v0.3, providing the empirical evidence the proposal's OQ4/OQ5 framing wants for promotion to MUST.

| # | Item | Source | Gating |
|---|---|---|---|
| B1 | Add `to: "file"` sentinel acceptance in `send_memo` validation; reject `action_required: true` combined with `to: "file"` (Pass-with-notes-level invalid per memodef proposal) | memodef v0.3 §Conformance Tests | Director ratifies memodef v0.3 upstream |
| B2 | Storage: `kind` column on `memos` (`'inbox'` / `'note'`); for `kind='note'`, the `filed_under_role_id` carries the role-folder semantic (re-use `to_position` value `"file"` per the spec). Migration `0003_notes.sql`. | derived from B1 | B1 ratification |
| B3 | API surface: extend `list_inbox(folder=...)` with optional folder-scoping arg. **Strategist call:** one tool, scope-by-arg — matches OAGP-family preference for fewer tools with more parameters over parallel tool surfaces. (Engineer may push back via proposal if the implementation forces a different shape.) | memodef v0.3 OQ5 (openbraid-side decision) | None (strategist-decided) |
| B4 | Panel: read-only notes browser (per role). Editing parity with memo browser deferred to Phase F. | derived | Optional in this phase |

**Estimated effort:** 1–2 days once gating clears.
**Phase exit criterion:** B1–B3 merged; B4 either landed or explicitly deferred to Phase F.
**Cross-spec follow-up:** file an "experience memo" back to memodef-strategist's inbox after first hand-authored memo-to-file lands in production, framed complaint-shaped per the family precedent — what felt forced, what slot was hardest to fill, what we'd change. (Per orgdef-strategist's standing recommendation re: openbraid as first adopter.)

## Phase C — Canonical addressing (orgdef-strategist memo)

The biggest body of work. Reshapes URL space and claim ceremony.

| # | Item | Source | Sub-gating |
|---|---|---|---|
| C1 | Three-level URL endpoints on `mcp.openbraid.app`: `/{account}` (org list), `/{account}/{org}` (position list), `/{account}/{org}/{position}` (boot payload) | orgdef memo §Three-level URL semantics | None (foundational) |
| C2 | Two-segment URL sugar: `/{account}/{position}` resolves to implicit org when account hosts exactly one. | orgdef memo §Three-level URL semantics | C1 |
| C3 | Position list ordering: depth-first walk of `reports_to` / `directs` / `validates_for` edges; fall back to `positions` array order when ambiguous. | orgdef memo §Position list ordering | C1; requires orgdef artifacts in DB |
| C4 | Boot payload shape (SHOULD per OQ4): position metadata + org summary + role definition + job definition + incumbent state + inbox summary + claim instruction. | orgdef memo §Boot payload | C1; **strategist-Director sync recommended before lock** since openbraid is implementation #1 and the SHOULD becomes de facto template until 2+ exist |
| C5 | Claim ceremony rewire: `claim_role` accepts a position URL primarily; backward-compat with name-based for v0 sessions. PIN ceremony preserved (the inverse-sncro UX is brand value per charter). | orgdef memo + Director instruction | C1, C4 |
| C6 | `x.org.org_location` extension parsing + storage: single-location and mirror-list shapes; `authoritative` flag handling. | orgdef memo §`x.org.org_location` | C1 |
| C7 | Full-fidelity export tool as MCP tool. **MUST per orgdef memo:** "without portable export, openbraid would be lock-in." Independent of other C items; could land earlier if engineer is parallel-shipping. | orgdef memo §Cross-protocol equivalence | None (independent) |

**Estimated effort:** 3–5 days.
**Sub-sequencing within Phase C:** C1 + C7 first (independent of auth changes); then C4 (boot payload — pause for Director sync before lock); then C5 (claim ceremony rewire); then C2/C3/C6 (refinement and edge cases).
**Phase exit criterion:** all C items merged; first claim-via-URL ceremony verified end-to-end from at least two runtimes.
**Cross-spec follow-up:** none required during Phase C; the orgdef-strategist memo explicitly says "design v1+ around this addressing scheme; v0 is what shipped, that's what shipped."

## Phase D — Cross-vendor reach

| # | Item | Source | Gating |
|---|---|---|---|
| D1 | **Option B** from engineer→strategist memo: ChatGPT Custom GPT via REST + OpenAPI. **Reframed:** REST endpoints expose the same canonical URL space Phase C defines (`/{account}/{org}/{position}` etc.). Not a parallel adapter surface; the *second transport* on a single URL space. | Engineer→strategist memo + reframe per orgdef memo | Phase C complete |
| D2 | **Option E**: OAuth 2.1 + PKCE on `/mcp` for Grok and stricter MCP clients. **Deferred** per engineer's lean and strategist concurrence — re-evaluate when ≥2 prospective users surface OR when other MCP clients converge on requiring OAuth. | Engineer→strategist memo addendum | Empirical demand |

**Estimated effort:** D1 ~1–2 days after Phase C. D2 deferred.
**Phase exit criterion:** D1 verified — a ChatGPT Custom GPT installs and successfully claims a role + reads a memo against the same role mailbox a Claude session uses.
**Director call needed:** approve D1 framing-as-second-transport (vs separate adapter surface).

## Phase E — Self-host + open-source readiness (the moat)

| # | Item | Source | Gating |
|---|---|---|---|
| E1 | Self-host setup documentation: Docker Compose, env var inventory, Supabase-or-equivalent schema bootstrap, OAuth provider setup walkthrough. | orgdef memo §Cross-protocol equivalence "self-host parity is load-bearing" | Phase C |
| E2 | Audit code for openbraid.app-specific assumptions (hardcoded domains, branding); promote to config. | derived | Phase C |
| E3 | Reference use cases in docs: `mcp.firstchurch.org`, `org.acmecorp.com` — make the moat-as-protocol pitch concrete. | orgdef memo | E1 |

**Estimated effort:** ~1 day.
**Phase exit criterion:** a third-party developer can clone the repo and stand up a working `mcp.<their-domain>` instance from documentation alone.

## Phase F — Panel UX maturation

Fragmentable; runs alongside whichever phase needs UI affordances. Items below are unordered; pick by Director priority + dependency.

| # | Item | Source | Gating |
|---|---|---|---|
| F1 | Memo browser by role / status / thread | engineer→engineer handoff thread #4 | Strategist proposal scoping the screens |
| F2 | Notes browser (per role; create/edit affordances if not in B4) | derived from Phase B | B complete |
| F3 | Role management UI (create / rename / delete; currently SQL-only) | engineer→engineer handoff | Strategist proposal |
| F4 | Auth-session list + revoke | engineer→engineer handoff | Lower priority |
| F5 | Mirror-list visualization (which orgdefs are mirrored where; sync direction) | derived from Phase C C6 | C6 |

**Estimated effort:** 3–5 days, fragmentable across multiple sessions.

## Director decisions captured (and pending)

| # | Decision | Disposition | Phase gated |
|---|---|---|---|
| 1 | A2 schema rename direction | Approved 2026-05-10 directionally; full PR review pending | A2 |
| 2 | A3 auto-create accounts default | Approved 2026-05-10 directionally; full PR review pending | A3 |
| 3 | Ratify memodef v0.3 (memos-to-file) upstream | **Pending — Director action required**; cross-spec answer goes to memodef-strategist's inbox | Phase B |
| 4 | Boot payload field set sync | Pending — strategist + Director sync recommended before C4 locks | C4 |
| 5 | D1 framing (REST as second transport on canonical URL space) | Implicit-approved-by-sequencing-ratification 2026-05-10; explicit confirmation welcome before D1 starts | D1 |
| 6 | D2 OAuth deferral | Approved 2026-05-10; revisit on empirical demand | D2 |

## Open questions / risks

1. **Phase B is gated on memodef v0.3 ratification upstream** — if Director defers the ratification, Phase B slides. Engineer should not start B work before ratification; can use the time for Phase C C7 (export tool, independent).
2. **Phase C C4 boot payload shape** — openbraid as implementation #1 sets the de facto template. Worth a strategist-Director sync to align field set before lock; otherwise we may discover the shape is wrong only after a second implementation tries to use it.
3. **Director bandwidth on cross-spec ratifications** — memodef v0.3 ratification, boot payload sync, possible orgdef coordination on `x.org.notes_location` extension all need Director attention. Surface these as a single ratification batch when convenient.
4. **The "right order" for engineer-pickup is fixed; the "right pace" is empirical.** Engineer self-paces within phase; strategist re-evaluates if a phase blocks for >24h on something a proposal could unblock.

## What this proposal is NOT

- Not a deadline-bound plan; engineer self-paces within phases.
- Not a replacement for individual proposals on items that need them (Phase A3 product-shape, Phase B3 API surface choice, Phase C4 boot payload shape, Phase D1 framing). This is the sequencing layer; per-item proposals follow per phase.
- Not a commitment to ship any phase by a specific date. The roadmap is the order; the calendar is the Director's call.

## Cross-references

- v0 shipped handoff: [`memos/read/2026-05-09-0015--openbraid-engineer--openbraid-engineer--v0-shipped-and-cross-runtime-proved.openthing`](../memos/read/2026-05-09-0015--openbraid-engineer--openbraid-engineer--v0-shipped-and-cross-runtime-proved.openthing) (will be in `read/` after engineer marks; currently in `inbox/`)
- Cross-vendor reach memo: [`memos/inbox/2026-05-09-0930--openbraid-engineer--openbraid-strategist--cross-vendor-reach.openthing`](../memos/inbox/2026-05-09-0930--openbraid-engineer--openbraid-strategist--cross-vendor-reach.openthing)
- Canonical OAGP addressing memo: [`memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing`](../memos/inbox/2026-05-10-1000--orgdef-strategist--openbraid-strategist--canonical-oagp-position-addressing-decided.openthing)
- Upstream orgdef decision: https://github.com/orgdef-spec/orgdef/blob/main/decisions/proposal-canonical-oagp-position-addressing.md (commit `ba004ca`)
- Upstream memodef proposal: https://github.com/memodef-spec/memodef/blob/main/proposals/2026-05-10-memos-to-file-and-notes-folder.md
- Charter: [`org/openbraid-org.openthing`](../org/openbraid-org.openthing)
- Engineer roledef: [`org/jobs/openbraid-engineer.openthing`](../org/jobs/openbraid-engineer.openthing)
