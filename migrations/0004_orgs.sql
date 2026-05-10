-- 0004_orgs.sql
-- Phase C foundation: introduce orgs as the missing layer between
-- accounts and roles, per the canonical OAGP position addressing
-- ratified upstream 2026-05-10 (orgdef-spec commit ba004ca).
--
-- Before: accounts -> roles
-- After:  accounts -> orgs -> roles
--
-- Each existing account is auto-migrated by creating a default 'personal'
-- org and re-parenting all that account's existing roles under it.
-- Director's framing on the default org name: "covers the use case of
-- someone who will never formally define an org, but wants the 'org of me'."
--
-- The roles.account_id column is intentionally retained even though
-- it's now derivable via roles.org_id -> orgs.account_id. Leaving it
-- avoids breaking the existing application-side `(account_id, name)`
-- lookups in claim_role / resolve_role_by_name / etc. C1+C2 (URL-
-- shaped endpoints) will introduce org-aware lookups; until then the
-- redundant account_id is harmless and keeps the v0 code path working.
--
-- The previous UNIQUE (account_id, name) constraint on roles is
-- replaced by UNIQUE (org_id, name) — role names need to be unique
-- within an org, not across the whole account. For accounts with one
-- 'personal' org (the v0 default and the C2 sugar case) this is
-- equivalent to the prior constraint.

-- New: orgs table -----------------------------------------------------------

CREATE TABLE orgs (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        uuid        NOT NULL REFERENCES accounts(id),
    name              text        NOT NULL,
    mission           text,
    vision            text,
    scope             text,
    governance_model  text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    deleted_at        timestamptz,
    UNIQUE (account_id, name)
);

CREATE INDEX orgs_account_id_idx ON orgs (account_id);

-- Migrate existing data ----------------------------------------------------

-- For each account that already owns roles, create a 'personal' org.
-- ON CONFLICT DO NOTHING handles the (unlikely) case where someone
-- has already manually created a personal org during testing.
INSERT INTO orgs (account_id, name)
SELECT DISTINCT account_id, 'personal'
FROM roles
WHERE deleted_at IS NULL
ON CONFLICT (account_id, name) DO NOTHING;

-- Add org_id column to roles (initially nullable so we can backfill).
ALTER TABLE roles
    ADD COLUMN org_id uuid REFERENCES orgs(id);

-- Backfill: every existing role gets parented under its account's
-- personal org.
UPDATE roles
SET org_id = (
    SELECT id FROM orgs
    WHERE orgs.account_id = roles.account_id
      AND orgs.name = 'personal'
      AND orgs.deleted_at IS NULL
)
WHERE org_id IS NULL;

-- Lock org_id NOT NULL going forward.
ALTER TABLE roles ALTER COLUMN org_id SET NOT NULL;

CREATE INDEX roles_org_id_idx ON roles (org_id);

-- Replace the old account-scoped uniqueness constraint with an
-- org-scoped one. Use the auto-generated constraint name from the
-- 0001 migration — Postgres names UNIQUE (col1, col2) constraints
-- as <table>_<col1>_<col2>_key by default.
ALTER TABLE roles DROP CONSTRAINT IF EXISTS roles_account_id_name_key;
ALTER TABLE roles ADD CONSTRAINT roles_org_id_name_key UNIQUE (org_id, name);

COMMENT ON TABLE orgs IS
'OAGP-shape org layer between accounts and roles. Each account auto-gets a "personal" org during the 0004 migration; users may create additional orgs going forward. The "org of me" default covers users who never formally define an org.';

COMMENT ON COLUMN roles.org_id IS
'FK to orgs.id. Required (NOT NULL) post-0004. The previous (account_id, name) uniqueness is now (org_id, name); org_id implies account_id via the orgs FK chain.';
