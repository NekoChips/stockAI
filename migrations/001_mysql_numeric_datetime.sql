-- StockAI MySQL schema migration: VARCHAR numbers/timestamps -> native types.
-- Run this file manually during a maintenance window. The application does not
-- execute it automatically because MySQL DDL commits implicitly.
-- Tested target: MySQL 8.0.

-- 1. bars: normalize ISO timestamps before replacing the primary-key column.
ALTER TABLE bars DROP PRIMARY KEY;
ALTER TABLE bars ADD COLUMN timestamp_value_new DATETIME(6) NULL AFTER interval_name;
UPDATE bars
SET timestamp_value_new = STR_TO_DATE(
    REPLACE(SUBSTRING_INDEX(timestamp_value, '+', 1), 'T', ' '),
    IF(INSTR(timestamp_value, '.') > 0, '%Y-%m-%d %H:%i:%s.%f', '%Y-%m-%d %H:%i:%s')
);
SELECT COUNT(*) AS invalid_bars_timestamps FROM bars WHERE timestamp_value_new IS NULL;
ALTER TABLE bars DROP COLUMN timestamp_value;
ALTER TABLE bars CHANGE COLUMN timestamp_value_new timestamp_value DATETIME(6) NOT NULL;
ALTER TABLE bars ADD PRIMARY KEY (symbol, interval_name, timestamp_value);
ALTER TABLE bars
    MODIFY open_price DECIMAL(20,6) NOT NULL,
    MODIFY high_price DECIMAL(20,6) NOT NULL,
    MODIFY low_price DECIMAL(20,6) NOT NULL,
    MODIFY close_price DECIMAL(20,6) NOT NULL,
    MODIFY volume DECIMAL(24,4) NOT NULL,
    MODIFY amount DECIMAL(24,4) NOT NULL;

-- 2. quote ticks: retain all intraday rows while converting timestamp columns.
ALTER TABLE market_quotes
    ADD COLUMN quoted_at_new DATETIME(6) NULL,
    ADD COLUMN observed_at_new DATETIME(6) NULL;
UPDATE market_quotes
SET quoted_at_new = STR_TO_DATE(REPLACE(SUBSTRING_INDEX(quoted_at, '+', 1), 'T', ' '), IF(INSTR(quoted_at, '.') > 0, '%Y-%m-%d %H:%i:%s.%f', '%Y-%m-%d %H:%i:%s')),
    observed_at_new = STR_TO_DATE(REPLACE(SUBSTRING_INDEX(observed_at, '+', 1), 'T', ' '), IF(INSTR(observed_at, '.') > 0, '%Y-%m-%d %H:%i:%s.%f', '%Y-%m-%d %H:%i:%s'));
SELECT COUNT(*) AS invalid_quote_timestamps
FROM market_quotes
WHERE quoted_at_new IS NULL OR observed_at_new IS NULL;
ALTER TABLE market_quotes DROP INDEX uq_market_quotes_tick;
ALTER TABLE market_quotes
    DROP COLUMN quoted_at,
    DROP COLUMN observed_at,
    CHANGE COLUMN quoted_at_new quoted_at DATETIME(6) NOT NULL,
    CHANGE COLUMN observed_at_new observed_at DATETIME(6) NOT NULL,
    MODIFY trade_date DATE NOT NULL,
    MODIFY latest_price DECIMAL(20,6) NOT NULL,
    MODIFY change_percent DECIMAL(12,6) NOT NULL,
    MODIFY previous_close DECIMAL(20,6) NOT NULL;
ALTER TABLE market_quotes ADD UNIQUE KEY uq_market_quotes_tick (trade_date, symbol, observed_at);

-- 3. Remaining numeric/date columns.
ALTER TABLE account_state MODIFY cash DECIMAL(20,6) NOT NULL;
ALTER TABLE positions
    MODIFY average_cost DECIMAL(20,6) NOT NULL,
    MODIFY last_price DECIMAL(20,6) NOT NULL,
    MODIFY realized_pnl DECIMAL(20,6) NOT NULL;
ALTER TABLE decisions
    MODIFY trade_date DATE NOT NULL,
    MODIFY target_weight DECIMAL(12,8) NOT NULL,
    MODIFY signal_score DECIMAL(12,8) NULL,
    MODIFY signal_confidence DECIMAL(12,8) NULL,
    MODIFY signal_target_weight DECIMAL(12,8) NULL;
ALTER TABLE fills
    ADD COLUMN timestamp_value_new DATETIME(6) NULL AFTER slippage;
UPDATE fills
SET timestamp_value_new = STR_TO_DATE(REPLACE(SUBSTRING_INDEX(timestamp_value, '+', 1), 'T', ' '), IF(INSTR(timestamp_value, '.') > 0, '%Y-%m-%d %H:%i:%s.%f', '%Y-%m-%d %H:%i:%s'));
SELECT COUNT(*) AS invalid_fill_timestamps FROM fills WHERE timestamp_value_new IS NULL;
ALTER TABLE fills
    DROP COLUMN timestamp_value,
    CHANGE COLUMN timestamp_value_new timestamp_value DATETIME(6) NOT NULL,
    MODIFY trade_date DATE NOT NULL,
    MODIFY price DECIMAL(20,6) NOT NULL,
    MODIFY fee DECIMAL(20,6) NOT NULL,
    MODIFY slippage DECIMAL(20,6) NOT NULL;
ALTER TABLE instrument_catalog MODIFY synced_date DATE NOT NULL;
ALTER TABLE portfolio_snapshots
    MODIFY snapshot_date DATE NOT NULL,
    MODIFY cash DECIMAL(20,6) NOT NULL,
    MODIFY total_asset DECIMAL(20,6) NOT NULL,
    MODIFY total_market_value DECIMAL(20,6) NOT NULL;
ALTER TABLE daily_reports
    MODIFY report_date DATE NOT NULL,
    MODIFY total_asset DECIMAL(20,6) NOT NULL,
    MODIFY daily_pnl DECIMAL(20,6) NOT NULL,
    MODIFY daily_return DECIMAL(20,8) NOT NULL;

-- 4. Verify the new schema before restarting StockAI.
SHOW CREATE TABLE bars;
SHOW CREATE TABLE market_quotes;
SELECT COUNT(*) AS bars_rows FROM bars;
SELECT COUNT(*) AS quote_rows FROM market_quotes;
