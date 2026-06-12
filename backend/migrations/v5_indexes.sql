-- V5 hot-path indexes — idempotent migration for EXISTING databases.
--
-- The SQLModel models now declare these indexes, so `create_all` adds them to a
-- FRESH database automatically. But `create_all` does NOT add a new index to a
-- table that already exists, so any already-deployed database needs this script
-- run once. Every statement is `IF NOT EXISTS`, so re-running is safe.
--
-- Portable across PostgreSQL (prod) and SQLite (tests): identifiers are quoted
-- because `call` is a reserved word on PostgreSQL.
--
-- The new CaseMembership table (and its own indexes) is created by `create_all`
-- as a brand-new table; only these indexes on pre-existing evidence tables need a
-- migration.

-- Query + graph hot path: every read filters by run_id; most order/window by time.
CREATE INDEX IF NOT EXISTS ix_message_run_ts ON "message" (run_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_call_run_ts    ON "call"    (run_id, timestamp);

-- Per-run lookups for tables without a timestamp.
CREATE INDEX IF NOT EXISTS ix_contact_run_id        ON "contact"        (run_id);
CREATE INDEX IF NOT EXISTS ix_media_run_id          ON "media"          (run_id);
CREATE INDEX IF NOT EXISTS ix_aleappartifact_run_id ON "aleappartifact" (run_id);

-- Audit chain integrity: sequence numbers are a single append order, never forked.
CREATE UNIQUE INDEX IF NOT EXISTS ux_auditevent_seq ON "auditevent" (seq);
