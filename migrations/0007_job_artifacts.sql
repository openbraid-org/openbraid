-- 0007_job_artifacts.sql
-- Phase E E2: roledef:Job artifact ingestion.
--
-- Parallel substrate to org_artifacts (0006): one row per uploaded
-- roledef:Job artifact, content stored byte-equivalent for E5
-- full-fidelity round-trip. Jobs hang off the owning org_artifact via
-- `org_artifact_id` FK so a job's lifetime is scoped to its parent org;
-- when an org is soft-deleted, its jobs follow.
--
-- The `job_id` column is the artifact's `id` field (e.g. "implementer"
-- for thingalog/implementer.openthing). UNIQUE per (org_artifact, job_id)
-- among live rows: an org cannot have two jobs with the same id, but
-- a re-upload of the same id updates the existing row.
--
-- Position-to-job linkage happens at boot-payload time, NOT at the
-- schema level: an orgdef position's `job_definition.url` references
-- a job artifact; we resolve it by (account, org_slug, job_id) at read
-- time. The boot-payload builder embeds full content when a job is
-- ingested; falls back to the `{url: ...}` reference with a diagnostic
-- when the referenced job hasn't been uploaded yet.

CREATE TABLE job_artifacts (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_artifact_id  uuid        NOT NULL REFERENCES org_artifacts(id),
    job_id           text        NOT NULL,
    content          jsonb       NOT NULL,
    version          text        NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    deleted_at       timestamptz
);

CREATE UNIQUE INDEX job_artifacts_org_jobid_unique
    ON job_artifacts (org_artifact_id, job_id)
    WHERE deleted_at IS NULL;

CREATE INDEX job_artifacts_org_artifact_id_idx ON job_artifacts (org_artifact_id);
CREATE INDEX job_artifacts_content_gin_idx ON job_artifacts USING GIN (content);

COMMENT ON TABLE job_artifacts IS
'Canonical store for roledef:Job artifacts (Phase E2). One row per uploaded job artifact, scoped to its owning org_artifact. content is byte-equivalent for E5 round-trip export; job_id and version are derived indexed fields.';

COMMENT ON COLUMN job_artifacts.job_id IS
'The artifact''s `id` field (e.g. "implementer"). Used to resolve position.job_definition.url references at boot-payload assembly time.';

COMMENT ON COLUMN job_artifacts.content IS
'The roledef:Job artifact as JSONB. Byte-equivalent round-trip required for E5 export. Validation happens at upload time; storage is faithful.';
