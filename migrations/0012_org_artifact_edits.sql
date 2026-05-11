-- 0012_org_artifact_edits.sql
-- F-edit: audit log of patch-shaped edits to org_artifacts.
--
-- Every successful update_position / update_org_metadata / bump_version /
-- add_position / delete_position / update_relationship MCP call inserts
-- a row. The chart page surfaces a "Recent edits" section so Director
-- can see who/when/what at a glance — trust-building rail for AI-driven
-- patches.
--
-- patch_summary is a free-form short string ("update_position
-- implementer → responsibilities (5 items)"). Not structured because
-- the variety of edit shapes makes a fixed schema fragile; structured
-- diff storage can land later if adopters demand machine-readable
-- audit consumption. version_before / version_after let the panel
-- reconstruct a version trail.

CREATE TABLE org_artifact_edits (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_artifact_id   uuid        NOT NULL REFERENCES org_artifacts(id),
    edited_by_role_id uuid        NOT NULL REFERENCES roles(id),
    tool_name         text        NOT NULL,
    patch_summary     text        NOT NULL,
    version_before    text,
    version_after     text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX org_artifact_edits_artifact_id_idx
    ON org_artifact_edits (org_artifact_id, created_at DESC);
CREATE INDEX org_artifact_edits_role_id_idx
    ON org_artifact_edits (edited_by_role_id);

COMMENT ON TABLE org_artifact_edits IS
'F-edit audit log. One row per successful patch-shaped MCP call (update_position, update_org_metadata, bump_version, etc.). Trust rail surfaced in the panel.';

COMMENT ON COLUMN org_artifact_edits.patch_summary IS
'Free-form short string describing what changed. Example: "update_position implementer → responsibilities (5 items)". Not structured by design; adopters that need machine-readable diffs can layer a structured diff on top.';
