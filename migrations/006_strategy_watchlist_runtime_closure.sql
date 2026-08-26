-- Existing MySQL installations: close the backtest-to-strategy and runtime watchlist contracts.
-- The application also performs these checks during MySQL initialization.

ALTER TABLE backtest_runs
    ADD COLUMN strategy_profile_id VARCHAR(128) NOT NULL DEFAULT 'default' AFTER strategy_id,
    ADD COLUMN confirmed_at DATETIME(6) NULL AFTER status,
    ADD COLUMN applied_at DATETIME(6) NULL AFTER confirmed_at;

CREATE INDEX idx_backtest_status ON backtest_runs (status, created_at);
CREATE INDEX idx_backtest_profile ON backtest_runs (strategy_profile_id, status);

-- Configuration-defined instruments are seeded into watchlist_items by the application
-- on startup. Do not copy them manually here: the runtime config is the source of
-- initial values, while MySQL remains the source of subsequent changes.
