-- 0003_notes.sql
-- Phase B (memodef v0.3 memos-to-file): add `kind` discriminator to memos.
--
-- memodef v0.3 introduces the `to: "file"` sentinel and a parallel
-- `notes/<role-id>/` folder convention for memos-to-file (intra-position
-- accumulated context). openbraid stores both kinds in the same `memos`
-- table; the `kind` column distinguishes them at query time.
--
-- Semantics:
--
--   kind = 'inbox' (default; matches v0.2 memos)
--     `role_id` = recipient role's mailbox id
--     `to_position` = recipient role's name (or "all" for broadcasts)
--     `status` = inbox/read/archived (maildir lifecycle)
--
--   kind = 'note' (memodef v0.3 memo-to-file)
--     `role_id` = the role whose notes folder this is filed under
--                 (typically equal to `from_position`'s role id)
--     `to_position` = "file" (per memodef v0.3 sentinel)
--     `status` = unused for notes; existing rows get 'archived' by
--                convention so they don't surface in default inbox
--                queries (the kind filter is the primary gate).
--
-- The choice to add a column instead of a separate table is deliberate:
-- memos and memos-to-file share the SHAPE (per the memodef-strategist's
-- POP-discipline ruling); only lifecycle differs. One table; query-time
-- discrimination by `kind`.

ALTER TABLE memos
    ADD COLUMN kind text NOT NULL DEFAULT 'inbox'
    CHECK (kind IN ('inbox', 'note'));

-- Hot lookup: scope-by-role + kind filtering used by both list_inbox
-- (kind='inbox') and the new notes-folder query (kind='note').
CREATE INDEX memos_role_kind_idx ON memos (role_id, kind);

COMMENT ON COLUMN memos.kind IS
'Memo classification: ''inbox'' (directed memo with maildir status lifecycle) or ''note'' (memodef v0.3 memo-to-file; filed for the role''s accumulated context, no per-recipient processing event).';
