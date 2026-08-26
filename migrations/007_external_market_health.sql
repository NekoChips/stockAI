-- External analysis data metadata and independent task health.
ALTER TABLE overseas_market_data
    ADD COLUMN IF NOT EXISTS source_symbol VARCHAR(64) NOT NULL DEFAULT '' AFTER symbol,
    ADD COLUMN IF NOT EXISTS is_proxy TINYINT NOT NULL DEFAULT 0 AFTER source_symbol,
    ADD COLUMN IF NOT EXISTS data_status VARCHAR(24) NOT NULL DEFAULT 'ready' AFTER is_proxy;

CREATE TABLE IF NOT EXISTS data_sync_status (
    task_name VARCHAR(64) PRIMARY KEY,
    trade_date DATE NOT NULL,
    status VARCHAR(24) NOT NULL,
    success_count INT NOT NULL DEFAULT 0,
    failure_count INT NOT NULL DEFAULT 0,
    error_summary TEXT,
    started_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_data_sync_status_date (trade_date, status)
) CHARACTER SET utf8mb4;
