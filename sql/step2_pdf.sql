-- Manual alternative to `flask db upgrade` for step 2 (PDF support, MySQL).
-- Use this ONLY if `flask db current` shows a3f9c2d71b04.

ALTER TABLE scan_history
    ADD COLUMN page INT NULL;

-- Tell Alembic this migration is applied
UPDATE alembic_version SET version_num = 'b5d1e8a2c907';
