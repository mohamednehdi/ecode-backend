-- Manual alternative to `flask db upgrade` for step 3 (API tokens, MySQL).
-- Use this ONLY if `flask db current` shows b5d1e8a2c907.

CREATE TABLE api_token (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    token_prefix VARCHAR(16) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    is_active TINYINT(1) NOT NULL,
    allowed_ips TEXT NULL,
    allowed_types TEXT NULL,
    quota_hourly INT NULL,
    quota_monthly INT NULL,
    valid_from DATETIME NULL,
    valid_until DATETIME NULL,
    created_at DATETIME NULL,
    last_used_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE INDEX ix_api_token_token_hash (token_hash)
);

CREATE TABLE api_usage (
    id INT NOT NULL AUTO_INCREMENT,
    token_id INT NOT NULL,
    created_at DATETIME NOT NULL,
    ip_address VARCHAR(45) NULL,
    PRIMARY KEY (id),
    INDEX ix_api_usage_token_time (token_id, created_at),
    FOREIGN KEY (token_id) REFERENCES api_token (id)
);

-- Tell Alembic this migration is applied
UPDATE alembic_version SET version_num = 'c7e4f3b9a120';
