-- Manual alternative to `flask db upgrade` for step 4 (statistics columns, MySQL).
-- Use this ONLY if `flask db current` shows c7e4f3b9a120.

ALTER TABLE api_usage
    ADD COLUMN status_code SMALLINT NULL,
    ADD COLUMN duration_ms INT NULL,
    ADD COLUMN codes_found INT NULL,
    ADD COLUMN pages SMALLINT NULL,
    ADD COLUMN file_type VARCHAR(8) NULL,
    ADD COLUMN file_bytes INT NULL,
    ADD COLUMN thorough TINYINT(1) NULL;

CREATE INDEX ix_api_usage_created ON api_usage (created_at);

UPDATE alembic_version SET version_num = 'd4b7a1e90c53';
