-- StockAI v0.1.3: price tracks, analysis-only external data, order state machine.
-- Run once on the release MySQL database before deploying the matching image.

CREATE TABLE IF NOT EXISTS bar_price_tracks (
  symbol VARCHAR(32) NOT NULL,
  interval_name VARCHAR(16) NOT NULL,
  timestamp_value DATETIME(6) NOT NULL,
  raw_open DECIMAL(20,6) NOT NULL, raw_high DECIMAL(20,6) NOT NULL, raw_low DECIMAL(20,6) NOT NULL, raw_close DECIMAL(20,6) NOT NULL,
  qfq_open DECIMAL(20,6) NOT NULL, qfq_high DECIMAL(20,6) NOT NULL, qfq_low DECIMAL(20,6) NOT NULL, qfq_close DECIMAL(20,6) NOT NULL,
  volume DECIMAL(24,4) NOT NULL, amount DECIMAL(24,4) NOT NULL, adjustment_factor DECIMAL(28,12) NOT NULL,
  source VARCHAR(64) NOT NULL, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (symbol, interval_name, timestamp_value)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS orders (
  order_id VARCHAR(64) PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL, asset_type VARCHAR(16) NOT NULL,
  direction VARCHAR(16) NOT NULL, quantity BIGINT NOT NULL, requested_price DECIMAL(20,6) NOT NULL,
  filled_quantity BIGINT NOT NULL DEFAULT 0, average_fill_price DECIMAL(20,6) NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL, reason TEXT, rejected_reason TEXT, created_at DATETIME(6) NOT NULL,
  submitted_at DATETIME(6) NULL, updated_at DATETIME(6) NULL,
  INDEX idx_orders_open (symbol, status, updated_at), INDEX idx_orders_trade_date (trade_date, symbol)
) CHARACTER SET utf8mb4;

-- MySQL has no portable ADD COLUMN IF NOT EXISTS across all supported versions.
-- The application performs this idempotent upgrade at startup. Run the following
-- block only when applying this migration manually to a database that predates it:
-- ALTER TABLE fills ADD COLUMN order_id VARCHAR(64) NULL AFTER slippage;

CREATE TABLE IF NOT EXISTS order_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, order_id VARCHAR(64) NOT NULL, trade_date DATE NOT NULL,
  status VARCHAR(32) NOT NULL, reason TEXT, event_at DATETIME(6) NOT NULL,
  INDEX idx_order_events_order (order_id, event_at)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS decision_events (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL, phase VARCHAR(24) NOT NULL,
  direction VARCHAR(16) NULL, approved TINYINT NULL, target_weight DECIMAL(12,8) NULL, status VARCHAR(32) NULL,
  reasons TEXT, strategy_id VARCHAR(128), order_id VARCHAR(64), event_at DATETIME(6) NOT NULL,
  INDEX idx_decision_events_date_symbol (trade_date, symbol, event_at)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS futures_positions (
  trade_date DATE NOT NULL, contract VARCHAR(16) NOT NULL, top10_long DECIMAL(20,2) NOT NULL DEFAULT 0,
  top10_short DECIMAL(20,2) NOT NULL DEFAULT 0, top10_net_ratio DECIMAL(10,6) NOT NULL DEFAULT 0,
  specific_seat_name VARCHAR(128) NULL, specific_seat_long DECIMAL(20,2) NULL, specific_seat_short DECIMAL(20,2) NULL,
  specific_seat_net_ratio DECIMAL(10,6) NULL, combined_net_ratio DECIMAL(10,6) NOT NULL DEFAULT 0,
  source VARCHAR(64) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trade_date, contract), INDEX idx_futures_trade_date (trade_date)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS overseas_market_data (
  market VARCHAR(32) NOT NULL, symbol VARCHAR(32) NOT NULL, trade_date DATE NOT NULL, name VARCHAR(128) NULL,
  prev_close DECIMAL(20,6) NOT NULL, close_price DECIMAL(20,6) NOT NULL, change_pct DECIMAL(10,6) NOT NULL,
  source VARCHAR(64) NOT NULL DEFAULT 'akshare', fetched_at DATETIME(6) NOT NULL,
  PRIMARY KEY (market, symbol, trade_date), INDEX idx_overseas_trade_date (trade_date)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS instrument_sector_mapping (
  symbol VARCHAR(32) PRIMARY KEY, sector VARCHAR(64) NOT NULL, source VARCHAR(32) NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS lhb_records (
  trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL, name VARCHAR(128) NULL, sector VARCHAR(64) NULL,
  net_buy DECIMAL(24,2) NULL, record_data LONGTEXT NOT NULL, source VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (trade_date, symbol),
  INDEX idx_lhb_symbol (symbol, trade_date)
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS lhb_seat_profile (
  seat_name VARCHAR(256) PRIMARY KEY, seat_type VARCHAR(32) NULL, quant_firm VARCHAR(128) NULL,
  buy_count INT NOT NULL DEFAULT 0, t3_win_rate DECIMAL(10,6) NULL, profile_data LONGTEXT NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;

CREATE TABLE IF NOT EXISTS lhb_quant_seats (
  seat_name VARCHAR(256) PRIMARY KEY, quant_firm VARCHAR(128) NOT NULL, strategy_style VARCHAR(128) NULL,
  notes TEXT NULL, is_active TINYINT NOT NULL DEFAULT 1,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;
