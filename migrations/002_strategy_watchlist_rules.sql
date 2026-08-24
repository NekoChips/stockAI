-- StockAI strategy/watchlist/calendar rules migration.
-- Run manually after a verified mysqldump backup. Do not execute in the MySQL
-- client as a single pasted shell command.

-- 1. Keep removed symbols auditable and make watchlist lifecycle explicit.
ALTER TABLE watchlist_exclusions
    ADD COLUMN removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE watchlist_items
    ADD COLUMN lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'observing',
    ADD COLUMN trading_enabled TINYINT NOT NULL DEFAULT 0,
    ADD COLUMN dormant_since DATE NULL,
    ADD INDEX idx_watchlist_lifecycle (lifecycle_status, trading_enabled);

-- 2. Store the three exchange calendars in one table.
ALTER TABLE trading_calendar
    ADD COLUMN market VARCHAR(8) NOT NULL DEFAULT 'CN' FIRST;

ALTER TABLE trading_calendar
    DROP PRIMARY KEY,
    ADD PRIMARY KEY (market, trade_date),
    DROP INDEX idx_trading_calendar_flag,
    ADD INDEX idx_trading_calendar_flag (market, is_trading_day, trade_date);

-- 3. Configuration confirmation metadata. Existing active records remain
-- active; new changes are written to draft_data until manually confirmed.
ALTER TABLE strategy_profiles
    ADD COLUMN confirmed_by VARCHAR(128) NULL,
    ADD COLUMN confirmed_at DATETIME(6) NULL,
    ADD COLUMN effective_monitor_round VARCHAR(64) NULL;

-- 4. Support idempotent daily decision lookup and report expansion.
ALTER TABLE decisions
    ADD INDEX idx_decisions_symbol_date (trade_date, symbol, id);

-- 4a. Keep the peak unadjusted price needed by trailing-stop risk checks.
ALTER TABLE positions
    ADD COLUMN highest_price DECIMAL(20,6) NOT NULL DEFAULT 0 AFTER realized_pnl;

-- 4b. Preserve raw quote events for seven days for source/limit diagnostics.
CREATE TABLE IF NOT EXISTS market_quote_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    latest_price DECIMAL(20,6) NOT NULL,
    change_percent DECIMAL(12,6) NOT NULL,
    previous_close DECIMAL(20,6) NOT NULL,
    quoted_at DATETIME(6) NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    source VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_market_quote_events_tick (trade_date, symbol, observed_at),
    INDEX idx_market_quote_events_retention (observed_at),
    INDEX idx_market_quote_events_symbol (symbol, trade_date, observed_at)
) CHARACTER SET utf8mb4;

-- 5. Optional order state table used to block removal while an order is open.
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    quantity BIGINT NOT NULL,
    requested_price DECIMAL(20,6) NOT NULL,
    status VARCHAR(24) NOT NULL,
    reason TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_orders_symbol_status (symbol, status, updated_at)
) CHARACTER SET utf8mb4;

-- 6. Verify before starting the new monitor.
SHOW CREATE TABLE watchlist_items;
SHOW CREATE TABLE trading_calendar;
SHOW CREATE TABLE strategy_profiles;
SELECT lifecycle_status, trading_enabled, COUNT(*) AS total
FROM watchlist_items GROUP BY lifecycle_status, trading_enabled;
