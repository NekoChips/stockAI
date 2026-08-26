-- MySQL 8.0 one-time cleanup for duplicated decision rows inside archived reports.
-- Run a mysqldump from the shell before executing this SQL file.
-- For each report_date + symbol, the last decision in the JSON array is retained.

CREATE TABLE IF NOT EXISTS daily_reports_backup_before_decision_cleanup LIKE daily_reports;
INSERT IGNORE INTO daily_reports_backup_before_decision_cleanup
SELECT * FROM daily_reports;

CREATE TEMPORARY TABLE tmp_daily_report_decisions AS
SELECT report_date, JSON_ARRAYAGG(decision) AS decisions
FROM (
    SELECT report_date, symbol, decision, ord
    FROM (
        SELECT
            reports.report_date,
            entries.ord,
            entries.symbol,
            entries.decision,
            ROW_NUMBER() OVER (
                PARTITION BY reports.report_date, entries.symbol
                ORDER BY entries.ord DESC
            ) AS row_number_for_symbol
        FROM daily_reports AS reports
        JOIN JSON_TABLE(
            reports.report_data,
            '$.decisions[*]' COLUMNS (
                ord FOR ORDINALITY,
                symbol VARCHAR(32) PATH '$.symbol',
                decision JSON PATH '$'
            )
        ) AS entries ON TRUE
    ) AS ranked
    WHERE row_number_for_symbol = 1
) AS retained
GROUP BY report_date;

UPDATE daily_reports AS reports
JOIN tmp_daily_report_decisions AS normalized
  ON normalized.report_date = reports.report_date
SET reports.report_data = JSON_SET(
    reports.report_data,
    '$.decisions',
    normalized.decisions
),
    reports.updated_at = CURRENT_TIMESTAMP;

DROP TEMPORARY TABLE tmp_daily_report_decisions;
