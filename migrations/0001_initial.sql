-- 0001_initial.sql
-- openbraid v0 schema: accounts, roles, pin_challenges, auth_sessions, memos.
--
-- Conventions:
--   - UUID primary keys via gen_random_uuid() (pgcrypto).
--   - Soft-delete: every business table has deleted_at; live-row filtering is the
--     application layer's responsibility. No DB-level views in v0 — keep the
--     surface small until query patterns settle.
--   - Foreign keys are indexed. Hot lookup paths (auth_sessions.session_token,
--     pin_challenges.pin, memos by (role_id, status)) get explicit indexes.
--   - PIN one-time-use is enforced in the application by setting used_at
--     atomically on first valid presentation. The DB tracks the timestamp; it
--     does not enforce single-use as a constraint (the kickoff memo is explicit
--     about this division).
--
-- Open questions called out in the PR description; Director-stated leans are
-- followed inline:
--   - roles.name uniqueness: per-account (UNIQUE (account_id, name)).
--   - roles.roledef_url: nullable (optional in v0).
--   - one role = one position v0; no positions table.
--   - memos store body and body_ref as separate columns to mirror the
--     memodef:Memo wire shape.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- accounts -------------------------------------------------------------------
-- One row per Google-authenticated user. google_user_id is the stable
-- identifier from Supabase Auth; email is denormalized for display and may
-- change if the user changes their Google email.

CREATE TABLE accounts (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    google_user_id  text        NOT NULL UNIQUE,
    email           text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

-- roles ----------------------------------------------------------------------
-- One row per named role under an account. Each role owns a memo store
-- (memos.role_id) and is the unit an AI session claims via the inverse-sncro
-- PIN flow. roledef_url is optional in v0; when present it points at the
-- roledef:Role artifact the session should load on first action after auth.

CREATE TABLE roles (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id   uuid        NOT NULL REFERENCES accounts(id),
    name         text        NOT NULL,
    roledef_url  text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    deleted_at   timestamptz,
    UNIQUE (account_id, name)
);

CREATE INDEX roles_account_id_idx ON roles (account_id);

-- pin_challenges -------------------------------------------------------------
-- One row per outstanding role-claim challenge. The 9-digit PIN is delivered
-- out-of-band to the human gatekeeper (web panel in v0). client_session_id
-- identifies the requesting Claude conversation so the issued auth_session can
-- be bound to it. claim_what is the human-readable description shown in the
-- panel ("read+write memos") so the user knows what they're authorizing.
-- Single-use is enforced in the application by setting used_at atomically.

CREATE TABLE pin_challenges (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id            uuid        NOT NULL REFERENCES roles(id),
    pin                char(9)     NOT NULL,
    client_session_id  text        NOT NULL,
    claim_what         text        NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz NOT NULL DEFAULT (now() + interval '5 minutes'),
    used_at            timestamptz
);

CREATE INDEX pin_challenges_role_id_idx ON pin_challenges (role_id);
CREATE INDEX pin_challenges_pin_idx     ON pin_challenges (pin);

-- auth_sessions --------------------------------------------------------------
-- One row per session token issued after a successful PIN presentation. The
-- session is bound to a specific role and to the originating Claude
-- conversation (client_session_id). revoked_at lets the panel revoke a session
-- without deleting it; queries default to (revoked_at IS NULL AND now() <
-- expires_at).

CREATE TABLE auth_sessions (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id            uuid        NOT NULL REFERENCES roles(id),
    session_token      text        NOT NULL,
    client_session_id  text        NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz NOT NULL,
    revoked_at         timestamptz
);

CREATE INDEX auth_sessions_role_id_idx       ON auth_sessions (role_id);
CREATE UNIQUE INDEX auth_sessions_token_idx  ON auth_sessions (session_token);

-- memos ----------------------------------------------------------------------
-- One row per memo in a role's mailbox. Mirrors memodef:Memo on the wire:
-- from_position / to_position / subject / body / body_ref / sent_at /
-- action_required / in_reply_to / thread_id are all spec-shaped fields. status
-- is the lifecycle state ('inbox' | 'read' | 'archived') and is openbraid's
-- own — memodef itself doesn't prescribe a status field on the receiver side.

CREATE TABLE memos (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id         uuid        NOT NULL REFERENCES roles(id),
    from_position   text        NOT NULL,
    to_position     text        NOT NULL,
    subject         text        NOT NULL,
    body            text        NOT NULL,
    body_ref        text,
    sent_at         timestamptz NOT NULL,
    action_required boolean     NOT NULL DEFAULT false,
    in_reply_to     text,
    thread_id       text,
    status          text        NOT NULL DEFAULT 'inbox'
                    CHECK (status IN ('inbox', 'read', 'archived')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

CREATE INDEX memos_role_id_idx        ON memos (role_id);
CREATE INDEX memos_role_status_idx    ON memos (role_id, status);
CREATE INDEX memos_thread_id_idx      ON memos (thread_id);
