-- Migrate only legacy minute bars. Do not use bars to backfill watchlist
-- raw/qfq tracks or index history; those datasets must be re-synced from the
-- configured AlphaFeed history provider.
-- Run after 009_split_market_bar_tables.sql and before dropping bars.

INSERT INTO intraday_bars (
    symbol,
    trade_date,
    interval_name,
    timestamp_value,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    amount,
    source
)
SELECT
    symbol,
    DATE(timestamp_value),
    '1m',
    timestamp_value,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    amount,
    CONCAT('legacy:', source)
FROM bars
WHERE interval_name IN ('minute', '1m')
ON DUPLICATE KEY UPDATE
    trade_date = VALUES(trade_date),
    open_price = VALUES(open_price),
    high_price = VALUES(high_price),
    low_price = VALUES(low_price),
    close_price = VALUES(close_price),
    volume = VALUES(volume),
    amount = VALUES(amount),
    source = VALUES(source),
    updated_at = CURRENT_TIMESTAMP;

