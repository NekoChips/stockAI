-- One-time MySQL migration for historical duplicate daily decisions.
-- Run a mysqldump from the shell before executing this SQL file.
-- The retained row is the newest row (largest id) for each trade_date + symbol.

CREATE TABLE IF NOT EXISTS decisions_backup_before_unique LIKE decisions;
INSERT IGNORE INTO decisions_backup_before_unique
SELECT * FROM decisions;

DELETE older
FROM decisions AS older
INNER JOIN decisions AS newer
  ON newer.trade_date = older.trade_date
 AND newer.symbol = older.symbol
 AND newer.id > older.id;

SET @has_unique_decision_key := (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'decisions'
      AND index_name = 'uq_decisions_trade_date_symbol'
);
SET @add_unique_decision_key := IF(
    @has_unique_decision_key = 0,
    'ALTER TABLE decisions ADD UNIQUE KEY uq_decisions_trade_date_symbol (trade_date, symbol)',
    'SELECT 1'
);
PREPARE add_unique_decision_key FROM @add_unique_decision_key;
EXECUTE add_unique_decision_key;
DEALLOCATE PREPARE add_unique_decision_key;
