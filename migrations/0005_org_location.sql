-- 0005_org_location.sql
-- Phase C C6: store the OAGP `x.org.org_location` extension on orgs.
--
-- Per the orgdef-strategist memo (orgdef-spec ba004ca), each orgdef
-- artifact declares its canonical hosting via this extension. Two
-- shapes (single-location object, mirror-list array) are accepted —
-- both fit comfortably in a single JSONB column.
--
-- Single-location form:
--   {"protocol": "mcp", "url": "https://mcp.openbraid.app/scott/personal"}
--
-- Mirror-list form:
--   [
--     {"protocol": "mcp",  "url": "...", "authoritative": true},
--     {"protocol": "git", "url": "...", "authoritative": false}
--   ]
--
-- Director-ratified OQ5 posture: mirror-list is steady-state, not just
-- migration. Orgs publishing to multiple canonical locations is a
-- stable shape. This column accepts either form; the application
-- layer interprets per the value's structure.
--
-- Nullable: orgs without explicit canonical-location declarations
-- (e.g., the auto-migrated 'personal' org for Director's account) get
-- NULL until the user populates it.

ALTER TABLE orgs ADD COLUMN org_location jsonb;

COMMENT ON COLUMN orgs.org_location IS
'OAGP `x.org.org_location` extension: declares the canonical hosting location(s) of the org. Object shape for single-location, array shape for mirror-list with authoritative flag per entry. Nullable.';
