-- Manual alternative to `flask db upgrade` for the step 1 security fixes (MySQL).
-- Use this ONLY if `flask db current` does not show 7e2fd18e1136.

-- Old sessions have no jti and can't be revoked: users simply log in again
DELETE FROM token;

ALTER TABLE token
    ADD COLUMN jti VARCHAR(36) NULL,
    ADD UNIQUE INDEX ix_token_jti (jti);

ALTER TABLE `user`
    ADD COLUMN verification_attempts INT NOT NULL DEFAULT 0;

-- Tell Alembic this migration is applied
UPDATE alembic_version SET version_num = 'a3f9c2d71b04';
