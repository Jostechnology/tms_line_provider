-- 001 — Scope line_tms_links to its OA channel.
--
-- A LINE userId is unique per channel: the id captured under one company's OA is
-- only usable to push through that same OA. The table previously stored
-- tms_id (globally UNIQUE) -> line_id with no channel reference, which (a) collides
-- across tenants that reuse a username and (b) loses which channel a line_id is
-- valid on. This adds company_id + oa_token and re-keys to (company_id, tms_id).
--
-- init_db() uses Base.metadata.create_all, which never ALTERs an existing table,
-- so run this by hand on any DB that already has line_tms_links. (Fresh dev DBs:
-- DROP TABLE line_tms_links; restart — create_all rebuilds it with the new shape.)
--
-- MySQL. Verify the old index name first: SHOW INDEX FROM line_tms_links;
-- a column with unique=True + index=True is typically `ix_line_tms_links_tms_id`.

ALTER TABLE line_tms_links
    ADD COLUMN company_id VARCHAR(64) NULL AFTER id,
    ADD COLUMN oa_token   VARCHAR(64) NULL AFTER line_id;

-- Best-effort backfill: if a line_id is also a known recipient, borrow its tenant.
UPDATE line_tms_links l
JOIN recipient_links r ON r.line_user_id = l.line_id
SET l.company_id = r.company_id,
    l.oa_token   = COALESCE(l.oa_token, r.oa_token)
WHERE l.company_id IS NULL;

-- Any row still unscoped can't be safely attributed to a channel — the user must
-- re-link through their OA. Drop them rather than guess a company_id.
DELETE FROM line_tms_links WHERE company_id IS NULL;

-- Drop the old global-unique index on tms_id; enforce per-tenant uniqueness.
ALTER TABLE line_tms_links DROP INDEX ix_line_tms_links_tms_id;
ALTER TABLE line_tms_links
    MODIFY company_id VARCHAR(64) NOT NULL,
    ADD INDEX ix_line_tms_links_company_id (company_id),
    ADD INDEX ix_line_tms_links_tms_id (tms_id),
    ADD UNIQUE KEY uq_line_tms_company_tms (company_id, tms_id);
