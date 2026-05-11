-- 0009_incumbents.sql
-- Phase F F0: artifact-position claimability.
--
-- A row binds an artifact position (org_artifact_id + position.id from
-- the artifact's items[] array) to an openbraid auth identity (the
-- role row in `roles` that owns memos and gets PIN-claimed). The
-- binding lifecycle:
--   - Created on the first successful claim_role against an
--     artifact-backed position URL.
--   - Closed by setting `ended_at` when the binding is intentionally
--     released (no v1 UX for this yet; future panel affordance).
--   - One LIVE binding per (artifact, position) is allowed — the
--     unique index enforces this. Multi-occupant sharing is via
--     auth_sessions on the bound role; the role itself stays single.
--
-- Why not just put the artifact_id + position_id on the roles table
-- itself? Because legacy roles (personal-strategist, etc.) have no
-- artifact binding and the columns would be NULL for them. A separate
-- incumbents table keeps roles cleanly typed and lets the binding
-- carry its own metadata (claimed_at distinct from role.created_at).

CREATE TABLE incumbents (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_artifact_id   uuid        NOT NULL REFERENCES org_artifacts(id),
    position_id       text        NOT NULL,
    claimed_role_id   uuid        NOT NULL REFERENCES roles(id),
    account_id        uuid        NOT NULL REFERENCES accounts(id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    ended_at          timestamptz
);

-- One live binding per (artifact, position). When a binding ends, a
-- new binding for the same position can take its place; the partial
-- index excludes ended rows so re-binding doesn't violate uniqueness.
CREATE UNIQUE INDEX incumbents_artifact_position_live
    ON incumbents (org_artifact_id, position_id)
    WHERE ended_at IS NULL;

CREATE INDEX incumbents_artifact_id_idx ON incumbents (org_artifact_id);
CREATE INDEX incumbents_claimed_role_id_idx ON incumbents (claimed_role_id);
CREATE INDEX incumbents_account_id_idx ON incumbents (account_id);

COMMENT ON TABLE incumbents IS
'Phase F F0: binds an artifact position (org_artifacts + items[].id) to an openbraid role row, making artifact-backed position URLs claimable. Created on first claim; ended_at flips closed on intentional release (no v1 UX yet).';

COMMENT ON COLUMN incumbents.position_id IS
'The position''s `id` field inside the orgdef opencatalog''s items[] array (e.g. "implementer"). Text, not FK — positions live as JSON, not as their own rows.';

COMMENT ON COLUMN incumbents.claimed_role_id IS
'The roles row that owns this artifact-bound seat. Memos, auth_sessions, etc. attach to this role_id exactly like legacy roles. Synthetic name convention: "<org_slug>/<position_id>" (e.g. "thingalog/implementer") to distinguish from legacy role names.';
