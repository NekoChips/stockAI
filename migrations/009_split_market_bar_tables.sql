-- Split legacy bars data domains before removing the legacy table.
-- This migration creates target tables only. Historical backfill and the final
-- DROP TABLE bars must be executed separately after application validation.

CREATE TABLE IF NOT EXISTS index_price_tracks (
    symbol VARCHAR(32) NOT NULL,
    interval_name VARCHAR(16) NOT NULL,
    timestamp_value DATETIME(6) NOT NULL,
    open_price DECIMAL(20,6) NOT NULL,
    high_price DECIMAL(20,6) NOT NULL,
    low_price DECIMAL(20,6) NOT NULL,
    close_price DECIMAL(20,6) NOT NULL,
    volume DECIMAL(24,4) NOT NULL,
    amount DECIMAL(24,4) NOT NULL,
    source VARCHAR(64) NOT NULL,
    fetched_at DATETIME(6) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, interval_name, timestamp_value),
    INDEX idx_index_price_tracks_time (interval_name, timestamp_value, symbol)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS intraday_bars (
    symbol VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    interval_name VARCHAR(16) NOT NULL,
    timestamp_value DATETIME(6) NOT NULL,
    open_price DECIMAL(20,6) NOT NULL,
    high_price DECIMAL(20,6) NOT NULL,
    low_price DECIMAL(20,6) NOT NULL,
    close_price DECIMAL(20,6) NOT NULL,
    volume DECIMAL(24,4) NOT NULL,
    amount DECIMAL(24,4) NOT NULL,
    source VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, interval_name, timestamp_value),
    INDEX idx_intraday_bars_trade_date (trade_date, symbol, interval_name, timestamp_value)
) CHARACTER SET utf8mb4;

