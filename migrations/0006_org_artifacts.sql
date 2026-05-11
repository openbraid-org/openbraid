-- 0006_org_artifacts.sql
-- Phase E E0-prep: the canonical-artifact storage substrate.
--
-- Per the orgdef-strategist 10:30 memo's principle: openbraid is the
-- HOSTING layer; orgdef.openthing artifacts are the CONTENT layer.
-- This table stores those artifacts as the canonical source of truth.
--
-- The `content` JSONB column holds the artifact verbatim (round-trip
-- MUST be byte-equivalent for E5 full-fidelity export to work). The
-- companion columns (`account_id`, `org_slug`, `version`) are
-- derived-from-content indexed fields for lookup, NOT canonical
-- substitutes for the artifact.
--
-- Director-ratified Postgres JSONB over Neo4j 2026-05-10 evening:
-- the canonical store IS the JSON artifact; relationships live inside
-- as fields; boot-payload DFS over <20-position artifacts is
-- sub-millisecond in code (BFI wins).
--
-- This migration is additive — existing `accounts`, `orgs`, `roles`,
-- `memos`, etc. tables continue to function via the legacy code path.
-- Phase E1 cutover (next PR) will start reading from org_artifacts
-- instead of the legacy orgs/roles tables.

CREATE TABLE org_artifacts (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id   uuid        NOT NULL REFERENCES accounts(id),
    org_slug     text        NOT NULL,
    content      jsonb       NOT NULL,
    version      text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    deleted_at   timestamptz
);

-- Live rows unique per (account, slug); soft-deleted rows don't
-- block re-uploads of the same slug. Same pattern as the v0 schema's
-- soft-delete convention.
CREATE UNIQUE INDEX org_artifacts_account_slug_unique
    ON org_artifacts (account_id, org_slug)
    WHERE deleted_at IS NULL;

CREATE INDEX org_artifacts_account_id_idx ON org_artifacts (account_id);

-- GIN index on content lets us query INTO the artifact when we need
-- to (e.g., "find all positions of type strategist across this
-- account's orgs"). Not used by E0-prep but cheap to land now since
-- the migration is one statement.
CREATE INDEX org_artifacts_content_gin_idx ON org_artifacts USING GIN (content);

COMMENT ON TABLE org_artifacts IS
'Canonical store for orgdef.openthing artifacts (Phase E). Each row is one operational org artifact, stored byte-equivalent for full-fidelity round-trip export. account_id and org_slug are derived indexed fields; content is the source of truth.';

COMMENT ON COLUMN org_artifacts.content IS
'The orgdef.openthing artifact as JSONB. Byte-equivalent round-trip required for E5 export. Validation happens at upload time; storage is faithful.';

COMMENT ON COLUMN org_artifacts.org_slug IS
'URL slug for the org, derived from artifact.id at upload time. Used in canonical URLs: mcp.openbraid.app/<account>/<org_slug>/<position>.';
