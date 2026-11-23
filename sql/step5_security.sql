-- Manual alternative to `flask db upgrade` for step 5 (audit log and key rotation, MySQL).
-- Use this ONLY if `flask db current` shows d4b7a1e90c53.

CREATE TABLE audit_log (
    id INT NOT NULL AUTO_INCREMENT,
    created_at DATETIME NOT NULL,
    actor_id INT NULL,
    actor_email VARCHAR(120) NULL,
    action VARCHAR(40) NOT NULL,
    target_type VARCHAR(20) NULL,
    target_id INT NULL,
    target_name VARCHAR(100) NULL,
    details TEXT NULL,
    ip_address VARCHAR(45) NULL,
    success TINYINT(1) NOT NULL,
    PRIMARY KEY (id),
    INDEX ix_audit_log_created (created_at),
    INDEX ix_audit_log_action (action, created_at)
);

ALTER TABLE api_token
    ADD COLUMN previous_token_hash VARCHAR(64) NULL,
    ADD COLUMN previous_valid_until DATETIME NULL,
    ADD COLUMN rotated_at DATETIME NULL;

CREATE INDEX ix_api_token_previous_token_hash ON api_token (previous_token_hash);

UPDATE alembic_version SET version_num = 'e8c2f6a41b7d';
