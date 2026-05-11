-- 0008_drop_job_artifacts.sql
-- Phase E opencatalog-refactor: retire the separate job_artifacts surface.
--
-- orgdef SCHEMA v1.0.0 (orgdef-spec commits 7694b69 / dfe60da) moved
-- jobs from external sibling files into items[] entries inside the
-- orgdef .opencatalog. Position.job_definition now references a job
-- item in the SAME bundle by {id, version}; cross-file lookup is gone
-- (URL becomes optional fallback for rare cross-org references).
--
-- The job_artifacts table introduced in 0007 had a brief operational
-- life (build 17 only); no production data has accumulated yet (the
-- thingalog implementer test row from the E2 smoke is the only
-- occupant and is being superseded by the .opencatalog re-upload).
-- Drop is the clean path. Single-user pre-prod posture; per-Director
-- 2026-05-10 evening call.

DROP TABLE IF EXISTS job_artifacts;
