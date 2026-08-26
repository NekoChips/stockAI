-- MySQL 8.0 one-time cleanup for historical duplicate business events.
-- The application startup first adds event_key, filled_quantity, position context,
-- monitor_round, created_at and the supporting indexes. Run this file only after
-- that startup.
-- Back up decision_events and daily_reports before executing this file.

CREATE TABLE IF NOT EXISTS decision_events_backup_before_compaction LIKE decision_events;
INSERT IGNORE INTO decision_events_backup_before_compaction
SELECT * FROM decision_events;

CREATE TEMPORARY TABLE tmp_decision_events_to_delete AS
SELECT id
FROM (
    SELECT
        id,
        phase,
        symbol,
        order_id,
        direction,
        approved,
        target_weight,
        status,
        filled_quantity,
        strategy_id,
        LAG(phase) OVER event_stream AS previous_phase,
        LAG(symbol) OVER event_stream AS previous_symbol,
        LAG(order_id) OVER event_stream AS previous_order_id,
        LAG(direction) OVER event_stream AS previous_direction,
        LAG(approved) OVER event_stream AS previous_approved,
        LAG(target_weight) OVER event_stream AS previous_target_weight,
        LAG(status) OVER event_stream AS previous_status,
        LAG(filled_quantity) OVER event_stream AS previous_filled_quantity,
        LAG(strategy_id) OVER event_stream AS previous_strategy_id
    FROM decision_events
    WINDOW event_stream AS (
        PARTITION BY trade_date, phase, COALESCE(order_id, symbol)
        ORDER BY event_at, id
    )
) AS ordered_events
WHERE phase = previous_phase
  AND symbol <=> previous_symbol
  AND order_id <=> previous_order_id
  AND (
      (
          phase = 'decision'
          AND direction <=> previous_direction
          AND approved <=> previous_approved
          AND target_weight <=> previous_target_weight
          AND strategy_id <=> previous_strategy_id
      )
      OR (
          phase = 'order'
          AND direction <=> previous_direction
          AND status <=> previous_status
          AND filled_quantity <=> previous_filled_quantity
      )
  );

DELETE events
FROM decision_events AS events
INNER JOIN tmp_decision_events_to_delete AS duplicates
    ON duplicates.id = events.id;

DROP TEMPORARY TABLE tmp_decision_events_to_delete;

-- Future runs are performed by monitor in batches. These statements are
-- intentionally limited so they do not create a long-running table lock.
DELETE FROM decision_events
WHERE phase = 'decision'
  AND event_at < NOW() - INTERVAL 30 DAY
LIMIT 5000;

DELETE FROM decision_events
WHERE phase = 'order'
  AND event_at < NOW() - INTERVAL 730 DAY
LIMIT 5000;
