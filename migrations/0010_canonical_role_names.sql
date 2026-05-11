-- 0010_canonical_role_names.sql
-- Phase F F0 follow-up: unify role naming on the canonical URL shape.
--
-- Director's call 2026-05-11: role names should self-describe whose
-- account and which org they belong to, because future cross-account
-- claims (one user overseeing another's position) will make role rows
-- ambiguous without the account prefix. Migrate legacy role names
-- from short form to canonical-URL form:
--
--   personal-strategist        →  scott/personal/personal-strategist
--   openbraid-engineer         →  scott/personal/openbraid-engineer
--   (and so on for every legacy role)
--
-- Convention going forward:
--   role.name = "<account_handle>/<org_slug>/<position_id>"
-- where account_handle is the email-localpart of the role's owning
-- account (the v0 handle-resolution rule openbraid uses for URLs).
--
-- Idempotent: the `name NOT LIKE '%/%'` guard skips already-migrated
-- names so re-running the migration is safe.

UPDATE roles r
SET name = (
    SELECT split_part(a.email, '@', 1) || '/' || o.name || '/' || r.name
    FROM orgs o
    JOIN accounts a ON a.id = o.account_id
    WHERE o.id = r.org_id
)
WHERE r.deleted_at IS NULL
  AND r.name NOT LIKE '%/%';
