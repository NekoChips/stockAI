from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from queue import Empty, LifoQueue
from threading import Lock
from typing import Iterator, List

from ..config import MySQLConnectionConfig
from ..journal import deduplicate_decision_timeline, decision_event_state, decision_position_context, make_business_event_key, normalize_daily_report, order_event_state
from ..models import Bar, Decision, Direction, Fill, OrderStatus, PaperOrder, Portfolio, Position, Quote, StrategySignal
from ..strategy_catalog import strategy_definitions
from ..strategy_runtime import profile_from_config


class MySQLMarketDataStore:
    """MySQL implementation of the persistent market-data store.

    The PyMySQL import and network connection are intentionally deferred until the
    first database operation, so configuration inspection never opens a connection.
    """

    def __init__(self, connection: MySQLConnectionConfig | None) -> None:
        if connection is None:
            raise ValueError("MySQL 存储配置缺少连接信息。")
        self.host = connection.host
        self.port = connection.port
        self.database = connection.database
        self.username = connection.username
        self.password = connection.password
        self._initialized = False
        self._initialize_lock = Lock()
        self._pool_lock = Lock()
        self._pool: LifoQueue | None = None
        self._pool_size = 16
        self._pool_total = 0
        self._monitor_lock_connection = None

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self._initialize_schema()
            self._initialized = True

    def acquire_monitor_lock(self, name: str = "stockai_monitor") -> bool:
        """Acquire a MySQL advisory lock for the lifetime of one monitor process."""
        self.initialize()
        with self._initialize_lock:
            if self._monitor_lock_connection is not None:
                return True
            import pymysql

            connection = pymysql.connect(host=self.host, port=self.port, user=self.username, password=self.password, database=self.database, charset="utf8mb4", autocommit=True)
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT GET_LOCK(%s, 0)", (name,))
                    row = cursor.fetchone()
                if not row or int(row[0]) != 1:
                    connection.close()
                    return False
                self._monitor_lock_connection = connection
                return True
            except Exception:
                connection.close()
                raise

    def release_monitor_lock(self, name: str = "stockai_monitor") -> None:
        connection = self._monitor_lock_connection
        self._monitor_lock_connection = None
        if connection is None:
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        statements = [
            """CREATE TABLE IF NOT EXISTS bars (
                symbol VARCHAR(32) NOT NULL, interval_name VARCHAR(16) NOT NULL, timestamp_value DATETIME(6) NOT NULL,
                open_price DECIMAL(20,6) NOT NULL, high_price DECIMAL(20,6) NOT NULL, low_price DECIMAL(20,6) NOT NULL,
                close_price DECIMAL(20,6) NOT NULL, volume DECIMAL(24,4) NOT NULL, amount DECIMAL(24,4) NOT NULL,
                source VARCHAR(64) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval_name, timestamp_value)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS account_state (
                id VARCHAR(32) PRIMARY KEY, cash DECIMAL(20,6) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS positions (
                symbol VARCHAR(32) PRIMARY KEY, quantity BIGINT NOT NULL, available_quantity BIGINT NOT NULL,
                average_cost DECIMAL(20,6) NOT NULL, last_price DECIMAL(20,6) NOT NULL, realized_pnl DECIMAL(20,6) NOT NULL,
                highest_price DECIMAL(20,6) NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS decisions (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL,
                direction VARCHAR(16) NOT NULL, target_weight DECIMAL(12,8) NOT NULL, approved TINYINT NOT NULL,
                reasons TEXT NOT NULL, signal_strategy_id VARCHAR(128), signal_score DECIMAL(12,8),
                signal_confidence DECIMAL(12,8), signal_target_weight DECIMAL(12,8), signal_evidence TEXT,
                signal_objections TEXT, signal_explanation TEXT, signal_version VARCHAR(64),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_decisions_trade_date (trade_date),
                UNIQUE KEY uq_decisions_trade_date_symbol (trade_date, symbol)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS market_quotes (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL,
                symbol VARCHAR(32) NOT NULL, name VARCHAR(128) NOT NULL,
                latest_price DECIMAL(20,6) NOT NULL, change_percent DECIMAL(12,6) NOT NULL,
                previous_close DECIMAL(20,6) NOT NULL, quoted_at DATETIME(6) NOT NULL,
                observed_at DATETIME(6) NOT NULL,
                source VARCHAR(64) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_market_quotes_tick (trade_date, symbol, observed_at),
                INDEX idx_market_quotes_latest (symbol, trade_date, observed_at)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS market_quote_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL,
                symbol VARCHAR(32) NOT NULL, name VARCHAR(128) NOT NULL,
                latest_price DECIMAL(20,6) NOT NULL, change_percent DECIMAL(12,6) NOT NULL,
                previous_close DECIMAL(20,6) NOT NULL, quoted_at DATETIME(6) NOT NULL,
                observed_at DATETIME(6) NOT NULL, source VARCHAR(64) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_market_quote_events_tick (trade_date, symbol, observed_at),
                INDEX idx_market_quote_events_retention (observed_at),
                INDEX idx_market_quote_events_symbol (symbol, trade_date, observed_at)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS fills (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL,
                direction VARCHAR(16) NOT NULL, quantity BIGINT NOT NULL, price DECIMAL(20,6) NOT NULL,
                fee DECIMAL(20,6) NOT NULL, slippage DECIMAL(20,6) NOT NULL, order_id VARCHAR(64) NULL, timestamp_value DATETIME(6) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_fills_trade_date (trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS metadata (
                `key` VARCHAR(128) PRIMARY KEY, value TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS watchlist_items (
                symbol VARCHAR(32) PRIMARY KEY, name VARCHAR(128) NOT NULL, asset_type VARCHAR(16) NOT NULL,
                lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'observing', trading_enabled TINYINT NOT NULL DEFAULT 0,
                dormant_since DATE NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_watchlist_lifecycle (lifecycle_status, trading_enabled)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS watchlist_exclusions (
                symbol VARCHAR(32) PRIMARY KEY, removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS instrument_catalog (
                symbol VARCHAR(32) PRIMARY KEY, name VARCHAR(128) NOT NULL, asset_type VARCHAR(16) NOT NULL,
                source VARCHAR(64) NOT NULL, synced_date DATE NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_instrument_catalog_name (name)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                snapshot_date DATE PRIMARY KEY, cash DECIMAL(20,6) NOT NULL, total_asset DECIMAL(20,6) NOT NULL,
                total_market_value DECIMAL(20,6) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS backtest_runs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, strategy_id VARCHAR(128) NOT NULL, strategy_profile_id VARCHAR(128) NOT NULL DEFAULT 'default',
                parameters TEXT NOT NULL, metrics TEXT NOT NULL, status VARCHAR(32) NOT NULL,
                confirmed_at DATETIME(6) NULL, applied_at DATETIME(6) NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_backtest_status (status, created_at), INDEX idx_backtest_profile (strategy_profile_id, status)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS daily_reports (
                report_date DATE PRIMARY KEY, status VARCHAR(32) NOT NULL, summary TEXT NOT NULL,
                total_asset DECIMAL(20,6) NOT NULL, daily_pnl DECIMAL(20,6) NOT NULL, daily_return DECIMAL(20,8) NOT NULL,
                report_data LONGTEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS trading_calendar (
                market VARCHAR(8) NOT NULL DEFAULT 'CN', trade_date DATE NOT NULL, is_trading_day TINYINT NOT NULL,
                source VARCHAR(64) NOT NULL, synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (market, trade_date), INDEX idx_trading_calendar_flag (market, is_trading_day, trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS strategy_definitions (
                strategy_id VARCHAR(128) PRIMARY KEY, name_zh VARCHAR(128) NOT NULL, name_en VARCHAR(128) NOT NULL,
                category_zh VARCHAR(64) NOT NULL, category_en VARCHAR(64) NOT NULL,
                description_zh TEXT NOT NULL, description_en TEXT NOT NULL,
                enabled TINYINT NOT NULL DEFAULT 1, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS strategy_profiles (
                profile_id VARCHAR(128) PRIMARY KEY, name_zh VARCHAR(128) NOT NULL, name_en VARCHAR(128) NOT NULL,
                scope_type VARCHAR(32) NOT NULL, scope_value VARCHAR(128) NOT NULL, status VARCHAR(32) NOT NULL,
                revision INT NOT NULL, profile_data LONGTEXT NOT NULL, draft_data LONGTEXT NULL, draft_revision INT NULL,
                confirmed_by VARCHAR(128) NULL, confirmed_at DATETIME(6) NULL, effective_monitor_round VARCHAR(64) NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_strategy_profiles_scope (scope_type, scope_value, status)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS strategy_change_log (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, profile_id VARCHAR(128) NOT NULL, action VARCHAR(32) NOT NULL,
                operator_name VARCHAR(128) NOT NULL, before_data LONGTEXT, after_data LONGTEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_strategy_change_log_profile (profile_id, created_at)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS bar_price_tracks (
                symbol VARCHAR(32) NOT NULL, interval_name VARCHAR(16) NOT NULL, timestamp_value DATETIME(6) NOT NULL,
                raw_open DECIMAL(20,6) NOT NULL, raw_high DECIMAL(20,6) NOT NULL, raw_low DECIMAL(20,6) NOT NULL, raw_close DECIMAL(20,6) NOT NULL,
                qfq_open DECIMAL(20,6) NOT NULL, qfq_high DECIMAL(20,6) NOT NULL, qfq_low DECIMAL(20,6) NOT NULL, qfq_close DECIMAL(20,6) NOT NULL,
                volume DECIMAL(24,4) NOT NULL, amount DECIMAL(24,4) NOT NULL, adjustment_factor DECIMAL(28,12) NOT NULL,
                source VARCHAR(64) NOT NULL, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval_name, timestamp_value)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS orders (
                order_id VARCHAR(64) PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL, asset_type VARCHAR(16) NOT NULL,
                direction VARCHAR(16) NOT NULL, quantity BIGINT NOT NULL, requested_price DECIMAL(20,6) NOT NULL,
                filled_quantity BIGINT NOT NULL DEFAULT 0, average_fill_price DECIMAL(20,6) NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL, reason TEXT, rejected_reason TEXT, created_at DATETIME(6) NOT NULL,
                submitted_at DATETIME(6) NULL, updated_at DATETIME(6) NULL,
                INDEX idx_orders_open (symbol, status, updated_at), INDEX idx_orders_trade_date (trade_date, symbol)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS order_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, order_id VARCHAR(64) NOT NULL, trade_date DATE NOT NULL, status VARCHAR(32) NOT NULL,
                filled_quantity BIGINT NOT NULL DEFAULT 0, reason TEXT, event_at DATETIME(6) NOT NULL, INDEX idx_order_events_order (order_id, event_at)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS decision_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL, phase VARCHAR(24) NOT NULL,
                direction VARCHAR(16) NULL, approved TINYINT NULL, target_weight DECIMAL(12,8) NULL, status VARCHAR(32) NULL,
                filled_quantity BIGINT NOT NULL DEFAULT 0, position_quantity BIGINT NOT NULL DEFAULT 0, position_weight DECIMAL(12,8) NOT NULL DEFAULT 0, position_state VARCHAR(16) NOT NULL DEFAULT 'unknown',
                reasons TEXT, strategy_id VARCHAR(128), order_id VARCHAR(64),
                event_key VARCHAR(128) NOT NULL, monitor_round VARCHAR(64) NULL, event_at DATETIME(6) NOT NULL,
                created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                UNIQUE KEY uq_decision_events_event_key (event_key),
                INDEX idx_decision_events_date_symbol (trade_date, symbol, event_at),
                INDEX idx_decision_events_retention (phase, event_at), INDEX idx_decision_events_order (order_id, event_at)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS futures_positions (
                trade_date DATE NOT NULL, contract VARCHAR(16) NOT NULL, top10_long DECIMAL(20,2) NOT NULL DEFAULT 0,
                top10_short DECIMAL(20,2) NOT NULL DEFAULT 0, top10_net_ratio DECIMAL(10,6) NOT NULL DEFAULT 0,
                specific_seat_name VARCHAR(128) NULL, specific_seat_long DECIMAL(20,2) NULL, specific_seat_short DECIMAL(20,2) NULL,
                specific_seat_net_ratio DECIMAL(10,6) NULL, combined_net_ratio DECIMAL(10,6) NOT NULL DEFAULT 0,
                source VARCHAR(64) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, contract), INDEX idx_futures_trade_date (trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS overseas_market_data (
                market VARCHAR(32) NOT NULL, symbol VARCHAR(32) NOT NULL, trade_date DATE NOT NULL, name VARCHAR(128) NULL,
                prev_close DECIMAL(20,6) NOT NULL, close_price DECIMAL(20,6) NOT NULL, change_pct DECIMAL(10,6) NOT NULL,
                source_symbol VARCHAR(64) NOT NULL, is_proxy TINYINT NOT NULL DEFAULT 0,
                data_status VARCHAR(24) NOT NULL DEFAULT 'ready', source VARCHAR(64) NOT NULL DEFAULT 'akshare', fetched_at DATETIME(6) NOT NULL,
                PRIMARY KEY (market, symbol, trade_date), INDEX idx_overseas_trade_date (trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS data_sync_status (
                task_name VARCHAR(64) PRIMARY KEY, trade_date DATE NOT NULL, status VARCHAR(24) NOT NULL,
                success_count INT NOT NULL DEFAULT 0, failure_count INT NOT NULL DEFAULT 0,
                error_summary TEXT, started_at DATETIME(6) NOT NULL, finished_at DATETIME(6) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_data_sync_status_date (trade_date, status)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS instrument_sector_mapping (
                symbol VARCHAR(32) PRIMARY KEY, sector VARCHAR(64) NOT NULL, source VARCHAR(32) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS lhb_records (
                trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL, name VARCHAR(128) NULL, sector VARCHAR(64) NULL,
                net_buy DECIMAL(24,2) NULL, record_data LONGTEXT NOT NULL, source VARCHAR(64) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (trade_date, symbol),
                INDEX idx_lhb_symbol (symbol, trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS lhb_seat_profile (
                seat_name VARCHAR(256) PRIMARY KEY, seat_type VARCHAR(32) NULL, quant_firm VARCHAR(128) NULL,
                buy_count INT NOT NULL DEFAULT 0, t3_win_rate DECIMAL(10,6) NULL, profile_data LONGTEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS lhb_quant_seats (
                seat_name VARCHAR(256) PRIMARY KEY, quant_firm VARCHAR(128) NOT NULL, strategy_style VARCHAR(128) NULL,
                notes TEXT NULL, is_active TINYINT NOT NULL DEFAULT 1, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
        ]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                self._migrate_market_quotes(cursor)
                self._migrate_positions(cursor)
                self._migrate_fills(cursor)
                self._migrate_watchlist(cursor)
                self._migrate_strategy_profiles(cursor)
                self._migrate_backtest_runs(cursor)
                self._migrate_overseas_market_data(cursor)
                self._migrate_decision_events(cursor)
                self._migrate_order_events(cursor)

    @staticmethod
    def _migrate_market_quotes(cursor) -> None:
        """Upgrade the former latest-only quote table without discarding its row."""
        try:
            cursor.execute("SHOW COLUMNS FROM market_quotes")
            columns = {row[0] for row in cursor.fetchall()}
        except AttributeError:  # lightweight unit-test cursor
            return
        if {"id", "trade_date", "observed_at"}.issubset(columns):
            return
        if "id" not in columns:
            cursor.execute(
                "ALTER TABLE market_quotes DROP PRIMARY KEY, "
                "ADD COLUMN id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST"
            )
        if "trade_date" not in columns:
            cursor.execute("ALTER TABLE market_quotes ADD COLUMN trade_date VARCHAR(16) NOT NULL DEFAULT '' AFTER symbol")
            cursor.execute("UPDATE market_quotes SET trade_date=LEFT(quoted_at, 10) WHERE trade_date='' ")
        if "observed_at" not in columns:
            cursor.execute("ALTER TABLE market_quotes ADD COLUMN observed_at VARCHAR(40) NOT NULL DEFAULT '' AFTER quoted_at")
            cursor.execute("UPDATE market_quotes SET observed_at=quoted_at WHERE observed_at='' ")
        cursor.execute("ALTER TABLE market_quotes ADD UNIQUE KEY uq_market_quotes_tick (trade_date, symbol, observed_at)")
        cursor.execute("ALTER TABLE market_quotes ADD INDEX idx_market_quotes_latest (symbol, trade_date, observed_at)")

    @staticmethod
    def _migrate_overseas_market_data(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM overseas_market_data")
            columns = {row[0] for row in cursor.fetchall()}
        except AttributeError:
            return
        if "source_symbol" not in columns:
            cursor.execute("ALTER TABLE overseas_market_data ADD COLUMN source_symbol VARCHAR(64) NOT NULL DEFAULT '' AFTER symbol")
        if "is_proxy" not in columns:
            cursor.execute("ALTER TABLE overseas_market_data ADD COLUMN is_proxy TINYINT NOT NULL DEFAULT 0 AFTER source_symbol")
        if "data_status" not in columns:
            cursor.execute("ALTER TABLE overseas_market_data ADD COLUMN data_status VARCHAR(24) NOT NULL DEFAULT 'ready' AFTER is_proxy")

    @staticmethod
    def _migrate_positions(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM positions")
            columns = {row[0] for row in cursor.fetchall()}
            if "highest_price" not in columns:
                cursor.execute("ALTER TABLE positions ADD COLUMN highest_price DECIMAL(20,6) NOT NULL DEFAULT 0 AFTER realized_pnl")
        except Exception:
            return

    @staticmethod
    def _migrate_fills(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM fills")
            columns = {row[0] for row in cursor.fetchall()}
            if "order_id" not in columns:
                cursor.execute("ALTER TABLE fills ADD COLUMN order_id VARCHAR(64) NULL AFTER slippage")
        except Exception:
            return

    @staticmethod
    def _migrate_decision_events(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM decision_events")
            columns = {row[0] for row in cursor.fetchall()}
        except Exception:
            return
        if "filled_quantity" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN filled_quantity BIGINT NOT NULL DEFAULT 0 AFTER status")
        if "position_quantity" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN position_quantity BIGINT NOT NULL DEFAULT 0 AFTER filled_quantity")
        if "position_weight" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN position_weight DECIMAL(12,8) NOT NULL DEFAULT 0 AFTER position_quantity")
        if "position_state" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN position_state VARCHAR(16) NOT NULL DEFAULT 'unknown' AFTER position_weight")
        if "event_key" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN event_key VARCHAR(128) NULL AFTER event_at")
        cursor.execute("UPDATE decision_events SET event_key=CONCAT('legacy:', id) WHERE event_key IS NULL OR event_key='' ")
        try:
            cursor.execute("ALTER TABLE decision_events MODIFY event_key VARCHAR(128) NOT NULL")
        except Exception:
            pass
        if "monitor_round" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN monitor_round VARCHAR(64) NULL AFTER event_key")
        if "created_at" not in columns:
            cursor.execute("ALTER TABLE decision_events ADD COLUMN created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) AFTER event_at")
        for statement in (
            "ALTER TABLE decision_events ADD UNIQUE KEY uq_decision_events_event_key (event_key)",
            "ALTER TABLE decision_events ADD INDEX idx_decision_events_retention (phase, event_at)",
            "ALTER TABLE decision_events ADD INDEX idx_decision_events_order (order_id, event_at)",
        ):
            try:
                cursor.execute(statement)
            except Exception:
                pass

    @staticmethod
    def _migrate_order_events(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM order_events")
            columns = {row[0] for row in cursor.fetchall()}
            if "filled_quantity" not in columns:
                cursor.execute("ALTER TABLE order_events ADD COLUMN filled_quantity BIGINT NOT NULL DEFAULT 0 AFTER status")
        except Exception:
            return

    @staticmethod
    def _migrate_watchlist(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM watchlist_items")
            columns = {row[0] for row in cursor.fetchall()}
            if "lifecycle_status" not in columns:
                cursor.execute("ALTER TABLE watchlist_items ADD COLUMN lifecycle_status VARCHAR(24) NOT NULL DEFAULT 'observing'")
            if "trading_enabled" not in columns:
                cursor.execute("ALTER TABLE watchlist_items ADD COLUMN trading_enabled TINYINT NOT NULL DEFAULT 0")
            if "dormant_since" not in columns:
                cursor.execute("ALTER TABLE watchlist_items ADD COLUMN dormant_since DATE NULL")
            try:
                cursor.execute("ALTER TABLE watchlist_items ADD INDEX idx_watchlist_lifecycle (lifecycle_status, trading_enabled)")
            except Exception:
                pass
        except Exception:
            return
        try:
            cursor.execute("SHOW COLUMNS FROM watchlist_exclusions")
            columns = {row[0] for row in cursor.fetchall()}
            if "removed_at" not in columns:
                cursor.execute("ALTER TABLE watchlist_exclusions ADD COLUMN removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP")
        except Exception:
            return

    @staticmethod
    def _migrate_strategy_profiles(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM strategy_profiles")
            columns = {row[0] for row in cursor.fetchall()}
        except AttributeError:
            return
        if "draft_data" not in columns:
            cursor.execute("ALTER TABLE strategy_profiles ADD COLUMN draft_data LONGTEXT NULL AFTER profile_data")
        if "draft_revision" not in columns:
            cursor.execute("ALTER TABLE strategy_profiles ADD COLUMN draft_revision INT NULL AFTER draft_data")
        if "confirmed_by" not in columns:
            cursor.execute("ALTER TABLE strategy_profiles ADD COLUMN confirmed_by VARCHAR(128) NULL")
        if "confirmed_at" not in columns:
            cursor.execute("ALTER TABLE strategy_profiles ADD COLUMN confirmed_at DATETIME(6) NULL")
        if "effective_monitor_round" not in columns:
            cursor.execute("ALTER TABLE strategy_profiles ADD COLUMN effective_monitor_round VARCHAR(64) NULL")

    @staticmethod
    def _migrate_backtest_runs(cursor) -> None:
        try:
            cursor.execute("SHOW COLUMNS FROM backtest_runs")
            columns = {row[0] for row in cursor.fetchall()}
        except Exception:
            return
        if "strategy_profile_id" not in columns:
            cursor.execute("ALTER TABLE backtest_runs ADD COLUMN strategy_profile_id VARCHAR(128) NOT NULL DEFAULT 'default' AFTER strategy_id")
        if "confirmed_at" not in columns:
            cursor.execute("ALTER TABLE backtest_runs ADD COLUMN confirmed_at DATETIME(6) NULL AFTER status")
        if "applied_at" not in columns:
            cursor.execute("ALTER TABLE backtest_runs ADD COLUMN applied_at DATETIME(6) NULL AFTER confirmed_at")
        try:
            cursor.execute("SHOW INDEX FROM backtest_runs")
            indexes = {row[2] for row in cursor.fetchall()}
        except Exception:
            return
        if "idx_backtest_status" not in indexes:
            cursor.execute("CREATE INDEX idx_backtest_status ON backtest_runs (status, created_at)")
        if "idx_backtest_profile" not in indexes:
            cursor.execute("CREATE INDEX idx_backtest_profile ON backtest_runs (strategy_profile_id, status)")

    def save_bars(self, bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        if not bars:
            return 0
        self.initialize()
        rows = [(bar.symbol, interval, _database_datetime(bar.timestamp), str(bar.open_price), str(bar.high_price), str(bar.low_price), str(bar.close_price), str(bar.volume), str(bar.amount), source) for bar in bars]
        sql = """INSERT INTO bars (symbol, interval_name, timestamp_value, open_price, high_price, low_price, close_price, volume, amount, source)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON DUPLICATE KEY UPDATE open_price=VALUES(open_price), high_price=VALUES(high_price), low_price=VALUES(low_price), close_price=VALUES(close_price), volume=VALUES(volume), amount=VALUES(amount), source=VALUES(source), updated_at=CURRENT_TIMESTAMP"""
        self._executemany(sql, rows)
        return len(rows)

    def save_price_tracks(self, raw_bars: List[Bar], qfq_bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        self.initialize()
        raw_by_time = {item.timestamp: item for item in raw_bars}
        qfq_by_time = {item.timestamp: item for item in qfq_bars}
        rows = []
        for timestamp in sorted(set(raw_by_time) | set(qfq_by_time)):
            raw, qfq = raw_by_time.get(timestamp), qfq_by_time.get(timestamp)
            reference = qfq or raw
            if reference is None:
                continue
            raw = raw or reference
            qfq = qfq or reference
            factor = qfq.close_price / raw.close_price if raw.close_price else Decimal("1")
            rows.append((reference.symbol, interval, _database_datetime(timestamp), str(raw.open_price), str(raw.high_price), str(raw.low_price), str(raw.close_price), str(qfq.open_price), str(qfq.high_price), str(qfq.low_price), str(qfq.close_price), str(reference.volume), str(reference.amount), str(factor), source))
        if rows:
            self._executemany(
                """INSERT INTO bar_price_tracks (symbol, interval_name, timestamp_value, raw_open, raw_high, raw_low, raw_close, qfq_open, qfq_high, qfq_low, qfq_close, volume, amount, adjustment_factor, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE raw_open=VALUES(raw_open), raw_high=VALUES(raw_high), raw_low=VALUES(raw_low), raw_close=VALUES(raw_close), qfq_open=VALUES(qfq_open), qfq_high=VALUES(qfq_high), qfq_low=VALUES(qfq_low), qfq_close=VALUES(qfq_close), volume=VALUES(volume), amount=VALUES(amount), adjustment_factor=VALUES(adjustment_factor), source=VALUES(source)""",
                rows,
            )
        self.save_bars(qfq_bars or raw_bars, interval, source)
        return len(qfq_bars or raw_bars)

    def load_bars(
        self,
        symbol: str,
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
        price_mode: str = "qfq",
    ) -> List[Bar]:
        self.initialize()
        filters = ["symbol=%s", "interval_name=%s"]
        params: list[object] = [symbol, interval]
        if start is not None:
            filters.append("timestamp_value >= %s")
            params.append(_database_datetime(datetime.combine(start, time.min)))
        if end is not None:
            filters.append("timestamp_value < %s")
            params.append(_database_datetime(datetime.combine(end + timedelta(days=1), time.min)))
        where = " AND ".join(filters)
        if price_mode in {"raw", "qfq"}:
            prefix = "raw" if price_mode == "raw" else "qfq"
            select = f"symbol, timestamp_value, {prefix}_open, {prefix}_high, {prefix}_low, {prefix}_close, volume, amount, adjustment_factor"
            table = "bar_price_tracks"
        else:
            select, table = "symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount", "bars"
        if limit is None:
            rows = self._fetchall(f"SELECT {select} FROM {table} WHERE {where} ORDER BY timestamp_value ASC", tuple(params))
        else:
            rows = self._fetchall(f"SELECT * FROM (SELECT {select} FROM {table} WHERE {where} ORDER BY timestamp_value DESC LIMIT %s) AS recent ORDER BY timestamp_value ASC", (*params, limit))
        if not rows and price_mode in {"raw", "qfq"}:
            legacy_select = "symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount"
            if limit is None:
                rows = self._fetchall(f"SELECT {legacy_select} FROM bars WHERE {where} ORDER BY timestamp_value ASC", tuple(params))
            else:
                rows = self._fetchall(f"SELECT * FROM (SELECT {legacy_select} FROM bars WHERE {where} ORDER BY timestamp_value DESC LIMIT %s) AS recent ORDER BY timestamp_value ASC", (*params, limit))
        return [_bar_from_row(row, price_mode) for row in rows]

    def load_bars_batch(
        self,
        symbols: list[str],
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
        price_mode: str = "qfq",
    ) -> dict[str, List[Bar]]:
        """Load all requested instruments in one query, then apply per-symbol limits."""
        if not symbols:
            return {}
        self.initialize()
        placeholders = ",".join(["%s"] * len(symbols))
        filters = [f"symbol IN ({placeholders})", "interval_name=%s"]
        params: list[object] = [*symbols, interval]
        if start is not None:
            filters.append("timestamp_value >= %s")
            params.append(_database_datetime(datetime.combine(start, time.min)))
        if end is not None:
            filters.append("timestamp_value < %s")
            params.append(_database_datetime(datetime.combine(end + timedelta(days=1), time.min)))
        prefix = "raw" if price_mode == "raw" else "qfq"
        rows = self._fetchall(
            f"SELECT symbol, timestamp_value, {prefix}_open, {prefix}_high, {prefix}_low, {prefix}_close, volume, amount, adjustment_factor "
            f"FROM bar_price_tracks WHERE {' AND '.join(filters)} ORDER BY symbol ASC, timestamp_value DESC",
            tuple(params),
        )
        if not rows and price_mode in {"raw", "qfq"}:
            rows = self._fetchall(
                f"SELECT symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount "
                f"FROM bars WHERE {' AND '.join(filters)} ORDER BY symbol ASC, timestamp_value DESC",
                tuple(params),
            )
        result = {symbol: [] for symbol in symbols}
        for row in rows:
            bucket = result.setdefault(row[0], [])
            if limit is None or len(bucket) < limit:
                bucket.append(_bar_from_row(row, price_mode))
        for symbol in result:
            result[symbol].sort(key=lambda item: item.timestamp)
        return result

    def save_quotes(self, quotes: List[Quote]) -> int:
        if not quotes:
            return 0
        self.initialize()
        rows = [
            (
                _quote_trade_date(quote),
                quote.symbol,
                quote.name,
                str(quote.latest_price),
                str(quote.change_percent),
                str(quote.previous_close),
                _database_datetime(quote.timestamp),
                _database_datetime(quote.fetched_at),
                quote.source,
            )
            for quote in quotes
        ]
        self._executemany(
            """INSERT INTO market_quotes (
                trade_date, symbol, name, latest_price, change_percent, previous_close, quoted_at, observed_at, source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), latest_price=VALUES(latest_price),
                change_percent=VALUES(change_percent), previous_close=VALUES(previous_close),
                quoted_at=VALUES(quoted_at), source=VALUES(source), updated_at=CURRENT_TIMESTAMP""",
            rows,
        )
        self._executemany(
            """INSERT INTO market_quote_events (
                trade_date, symbol, name, latest_price, change_percent, previous_close, quoted_at, observed_at, source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE latest_price=VALUES(latest_price), change_percent=VALUES(change_percent),
                previous_close=VALUES(previous_close), quoted_at=VALUES(quoted_at), source=VALUES(source)""",
            rows,
        )
        self._execute("DELETE FROM market_quote_events WHERE observed_at < CURRENT_TIMESTAMP(6) - INTERVAL 7 DAY")
        return len(rows)

    def load_latest_quotes(self, symbols: list[str] | None = None) -> dict[str, dict]:
        self.initialize()
        sql = "SELECT symbol, name, latest_price, change_percent, previous_close, quoted_at, observed_at, source FROM market_quotes"
        params: tuple = ()
        if symbols:
            placeholders = ",".join(["%s"] * len(symbols))
            sql += f" WHERE symbol IN ({placeholders})"
            params = tuple(symbols)
        rows = self._fetchall(sql + " ORDER BY observed_at DESC, id DESC", params)
        latest: dict[str, dict] = {}
        for row in rows:
            if row[0] in latest:
                continue
            latest[row[0]] = {
                "symbol": row[0],
                "name": row[1],
                "latest_price": Decimal(row[2]),
                "change_percent": Decimal(row[3]),
                "previous_close": Decimal(row[4]),
                "quoted_at": _iso_datetime(row[5]),
                "observed_at": _iso_datetime(row[6]),
                "source": row[7],
            }
        return latest

    def load_quote_ticks(self, symbol: str, trade_date: date) -> list[dict]:
        self.initialize()
        rows = self._fetchall(
            "SELECT symbol, name, latest_price, change_percent, previous_close, quoted_at, observed_at, source "
            "FROM market_quotes WHERE symbol=%s AND trade_date=%s ORDER BY observed_at ASC, id ASC",
            (symbol, trade_date.isoformat()),
        )
        return [_quote_row(row) for row in rows]

    def prune_market_quotes(self, trade_date: date) -> int:
        self.initialize()
        rows = self._fetchall(
            "SELECT symbol, name, latest_price, change_percent, previous_close, quoted_at, observed_at, source "
            "FROM market_quotes WHERE trade_date<>%s ORDER BY observed_at ASC, id ASC",
            (trade_date.isoformat(),),
        )
        minute_bars = _quote_ticks_to_minute_bars([_quote_row(row) for row in rows])
        if minute_bars:
            self.save_bars(minute_bars, interval="minute", source="market_quotes")
        return self._execute("DELETE FROM market_quotes WHERE trade_date<>%s", (trade_date.isoformat(),))

    def load_watchlist_items(self) -> list[dict[str, str]]:
        self.initialize()
        return [{"symbol": row[0], "name": row[1], "asset_type": row[2], "lifecycle_status": row[3], "trading_enabled": row[4]} for row in self._fetchall("SELECT symbol, name, asset_type, lifecycle_status, trading_enabled FROM watchlist_items ORDER BY created_at ASC, symbol ASC")]

    def ensure_watchlist_defaults(self, instruments) -> None:
        self.initialize()
        if not instruments:
            return
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for item in instruments:
                    cursor.execute("SELECT 1 FROM watchlist_exclusions WHERE symbol=%s", (item.symbol,))
                    if cursor.fetchone():
                        continue
                    cursor.execute(
                        "INSERT IGNORE INTO watchlist_items (symbol, name, asset_type, lifecycle_status, trading_enabled) VALUES (%s, %s, %s, %s, %s)",
                        (item.symbol, item.name or item.symbol, item.asset_type, item.lifecycle_status, int(bool(item.trading_enabled))),
                    )

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM watchlist_exclusions WHERE symbol=%s", (symbol,))
                cursor.execute("INSERT INTO watchlist_items (symbol, name, asset_type) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), asset_type=VALUES(asset_type), updated_at=CURRENT_TIMESTAMP", (symbol, name, asset_type))

    def set_watchlist_trading_enabled(self, symbol: str, enabled: bool) -> None:
        self.initialize()
        status = "trading_enabled" if enabled else "observing"
        updated = self._execute(
            "UPDATE watchlist_items SET trading_enabled=%s, lifecycle_status=%s, updated_at=CURRENT_TIMESTAMP WHERE symbol=%s",
            (int(bool(enabled)), status, symbol),
        )
        if not updated:
            raise ValueError(f"标的 {symbol} 不在手动观察池中。")

    def remove_watchlist_item(self, symbol: str) -> None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM watchlist_items WHERE symbol=%s", (symbol,))
                cursor.execute("INSERT IGNORE INTO watchlist_exclusions (symbol) VALUES (%s)", (symbol,))

    def has_pending_orders(self, symbol: str) -> bool:
        """Return whether an unfinished order blocks watchlist removal."""
        self.initialize()
        try:
            row = self._fetchone(
                "SELECT COUNT(*) FROM orders WHERE symbol=%s AND status IN (%s, %s, %s, %s)",
                (symbol, OrderStatus.CREATED.value, OrderStatus.APPROVED.value, OrderStatus.SUBMITTED.value, OrderStatus.PARTIALLY_FILLED.value),
            )
        except Exception:
            # Older installations do not have the optional order event table;
            # the current synchronous simulator has no pending order state.
            return False
        return bool(row and int(row[0]) > 0)

    def restore_watchlist_item(self, symbol: str) -> None:
        self.initialize()
        self._execute("DELETE FROM watchlist_exclusions WHERE symbol=%s", (symbol,))

    def load_removed_watchlist_symbols(self) -> set[str]:
        self.initialize()
        return {str(row[0]) for row in self._fetchall("SELECT symbol FROM watchlist_exclusions")}

    def replace_instrument_catalog(self, items: list[dict[str, str]], synced_date: str, source: str) -> int:
        if not items:
            return 0
        self.initialize()
        rows = [(str(item["symbol"]), str(item["name"]), str(item["asset_type"]), source, synced_date) for item in items]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM instrument_catalog")
                cursor.executemany("INSERT INTO instrument_catalog (symbol, name, asset_type, source, synced_date) VALUES (%s, %s, %s, %s, %s)", rows)
                cursor.execute("INSERT INTO metadata (`key`, value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=CURRENT_TIMESTAMP", ("instrument_catalog_synced_date", synced_date))
        return len(rows)

    def search_instrument_catalog(self, query: str, limit: int = 12) -> list[dict[str, str]]:
        self.initialize()
        text = str(query).strip().upper()
        if not text:
            return []
        pattern = f"%{text}%"
        rows = self._fetchall("SELECT symbol, name, asset_type FROM instrument_catalog WHERE UPPER(symbol) LIKE %s OR UPPER(name) LIKE %s ORDER BY CASE WHEN UPPER(symbol)=%s THEN 0 ELSE 1 END, name ASC LIMIT %s", (pattern, pattern, text, int(limit)))
        return [{"symbol": row[0], "name": row[1], "asset_type": row[2]} for row in rows]

    def instrument_catalog_status(self) -> dict[str, str | int]:
        self.initialize()
        count = self._fetchone("SELECT COUNT(*) FROM instrument_catalog")[0]
        row = self._fetchone("SELECT value FROM metadata WHERE `key`=%s", ("instrument_catalog_synced_date",))
        return {"count": int(count), "synced_date": row[0] if row else ""}

    def load_portfolio(self, initial_cash: Decimal) -> Portfolio:
        self.initialize()
        account = self._fetchone("SELECT cash FROM account_state WHERE id=%s", ("paper",))
        portfolio = Portfolio(Decimal(account[0]) if account else initial_cash)
        for row in self._fetchall("SELECT symbol, quantity, available_quantity, average_cost, last_price, realized_pnl, highest_price FROM positions ORDER BY symbol ASC"):
            portfolio.positions[row[0]] = Position(row[0], int(row[1]), int(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), Decimal(row[6]))
        return portfolio

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self.initialize()
        rows = [(item.symbol, item.quantity, item.available_quantity, str(item.average_cost), str(item.last_price), str(item.realized_pnl), str(item.highest_price)) for item in portfolio.positions.values()]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO account_state (id, cash) VALUES (%s, %s) ON DUPLICATE KEY UPDATE cash=VALUES(cash), updated_at=CURRENT_TIMESTAMP", ("paper", str(portfolio.cash)))
                cursor.execute("DELETE FROM positions")
                if rows:
                    cursor.executemany("INSERT INTO positions (symbol, quantity, available_quantity, average_cost, last_price, realized_pnl, highest_price) VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)

    def record_decision(self, decision: Decision, trade_date: date, portfolio: Portfolio | None = None) -> None:
        self.initialize()
        signal = decision.source_signal
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, reasons FROM decisions WHERE trade_date=%s AND symbol=%s ORDER BY id DESC LIMIT 1",
                    (trade_date.isoformat(), decision.symbol),
                )
                existing = cursor.fetchone()
                reasons = list(decision.reasons)
                if existing and existing[1]:
                    try:
                        reasons = list(dict.fromkeys([*json.loads(existing[1]), *reasons]))[-20:]
                    except (TypeError, ValueError):
                        pass
                values = (
                    decision.direction.value,
                    str(decision.target_weight),
                    int(decision.approved),
                    _dumps(reasons),
                    signal.strategy_id if signal else None,
                    str(signal.score) if signal else None,
                    str(signal.confidence) if signal else None,
                    str(signal.target_weight) if signal else None,
                    _dumps(signal.evidence) if signal else None,
                    _dumps(signal.objections) if signal else None,
                    signal.explanation if signal else None,
                    signal.version if signal else None,
                )
                if existing:
                    cursor.execute(
                        "UPDATE decisions SET direction=%s, target_weight=%s, approved=%s, reasons=%s, signal_strategy_id=%s, signal_score=%s, signal_confidence=%s, signal_target_weight=%s, signal_evidence=%s, signal_objections=%s, signal_explanation=%s, signal_version=%s WHERE id=%s",
                        (*values, existing[0]),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO decisions (trade_date, symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (trade_date.isoformat(), decision.symbol, *values),
                    )
                cursor.execute(
                    "SELECT id, direction, approved, target_weight, strategy_id FROM decision_events WHERE trade_date=%s AND symbol=%s AND phase='decision' ORDER BY id DESC LIMIT 1",
                    (trade_date.isoformat(), decision.symbol),
                )
                previous_event = cursor.fetchone()
                previous_state = (
                    str(previous_event[1]), str(previous_event[3]), bool(previous_event[2]), str(previous_event[4] or "")
                ) if previous_event else None
                state = decision_event_state(decision)
                if previous_state == state:
                    return
                position_quantity, position_weight, position_state = decision_position_context(portfolio, decision.symbol)
                cursor.execute(
                    "INSERT INTO decision_events (trade_date, symbol, phase, direction, approved, target_weight, status, filled_quantity, position_quantity, position_weight, position_state, reasons, strategy_id, event_key, event_at) VALUES (%s, %s, 'decision', %s, %s, %s, NULL, 0, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        trade_date.isoformat(), decision.symbol, decision.direction.value, int(decision.approved),
                        str(decision.target_weight), position_quantity, str(position_weight), position_state,
                        _dumps(decision.reasons), signal.strategy_id if signal else None,
                        make_business_event_key("decision", trade_date, decision.symbol, state, previous_event[0] if previous_event else None),
                        _database_datetime(datetime.now()),
                    ),
                )

    def compact_watch_decisions(self) -> int:
        """Keep one observation decision per symbol and trading day."""
        self.initialize()
        return self._execute(
            """DELETE FROM decisions WHERE direction=%s AND id NOT IN (
                SELECT id FROM (
                    SELECT MIN(id) AS id FROM decisions WHERE direction=%s GROUP BY trade_date, symbol
                ) AS retained
            )""",
            (Direction.WATCH.value, Direction.WATCH.value),
        )

    def compact_decision_events(self, trade_date: date | None = None) -> int:
        """Remove consecutive duplicate business events without touching order history."""
        self.initialize()
        sql = (
            "SELECT id, trade_date, symbol, phase, direction, approved, target_weight, status, "
            "filled_quantity, reasons, strategy_id, order_id, event_key, event_at "
            "FROM decision_events"
        )
        params: tuple = ()
        if trade_date is not None:
            sql += " WHERE trade_date=%s"
            params = (trade_date.isoformat(),)
        sql += " ORDER BY trade_date ASC, symbol ASC, phase ASC, event_at ASC, id ASC"
        rows = self._fetchall(sql, params)
        timeline = [
            {
                "_row_id": row[0], "trade_date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                "symbol": row[2], "phase": row[3], "direction": row[4], "approved": row[5],
                "target_weight": str(row[6]) if row[6] is not None else None, "status": row[7],
                "filled_quantity": int(row[8] or 0), "reasons": _loads(row[9]), "strategy_id": row[10],
                "order_id": row[11], "event_key": row[12], "event_at": _iso_datetime(row[13]),
            }
            for row in rows
        ]
        retained_ids = {item["_row_id"] for item in deduplicate_decision_timeline(timeline)}
        duplicate_ids = [item["_row_id"] for item in timeline if item["_row_id"] not in retained_ids]
        if not duplicate_ids:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for start in range(0, len(duplicate_ids), 500):
                    batch = duplicate_ids[start:start + 500]
                    placeholders = ", ".join(["%s"] * len(batch))
                    cursor.execute(f"DELETE FROM decision_events WHERE id IN ({placeholders})", tuple(batch))
        return len(duplicate_ids)

    def purge_decision_events(
        self,
        as_of: date | None = None,
        decision_retention_days: int = 30,
        order_retention_days: int = 730,
    ) -> int:
        """Delete expired strategy/order events without touching daily reports."""
        self.initialize()
        reference = as_of or date.today()
        removed = 0
        for phase, retention_days in (("decision", decision_retention_days), ("order", order_retention_days)):
            cutoff = (reference - timedelta(days=int(retention_days))).isoformat()
            removed += self._execute(
                "DELETE FROM decision_events WHERE phase=%s AND event_at < %s LIMIT 5000",
                (phase, cutoff),
            )
        return removed

    def load_decisions(self, trade_date: date) -> List[Decision]:
        self.initialize()
        rows = self._fetchall("SELECT symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version FROM decisions WHERE trade_date=%s ORDER BY id ASC", (trade_date.isoformat(),))
        return [_decision_from_row(row) for row in rows]

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        self.initialize()
        self._execute("INSERT INTO fills (trade_date, symbol, direction, quantity, price, fee, slippage, order_id, timestamp_value) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", ((trade_date or fill.timestamp.date()).isoformat(), fill.symbol, fill.direction.value, fill.quantity, str(fill.price), str(fill.fee), str(fill.slippage), fill.order_id or None, _database_datetime(fill.timestamp)))

    def save_order(self, order, trade_date: date | None = None):
        self.initialize()
        happened = order.updated_at or order.created_at
        day = trade_date or happened.date()
        values = (order.order_id, day.isoformat(), order.symbol, order.asset_type, order.direction.value, order.quantity, str(order.requested_price), order.filled_quantity, str(order.average_fill_price), order.status.value, order.reason, order.rejected_reason, _database_datetime(order.created_at), _database_datetime(order.submitted_at) if order.submitted_at else None, _database_datetime(happened))
        previous_event = self._fetchone(
            "SELECT id, direction, status, filled_quantity FROM decision_events WHERE phase='order' AND order_id=%s ORDER BY id DESC LIMIT 1",
            (order.order_id,),
        )
        previous_state = (
            str(previous_event[1]), str(previous_event[2]), int(previous_event[3] or 0)
        ) if previous_event else None
        state = order_event_state(order)
        changed = previous_state != state
        self._execute(
            """INSERT INTO orders (order_id, trade_date, symbol, asset_type, direction, quantity, requested_price, filled_quantity, average_fill_price, status, reason, rejected_reason, created_at, submitted_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE filled_quantity=VALUES(filled_quantity), average_fill_price=VALUES(average_fill_price), status=VALUES(status), reason=VALUES(reason), rejected_reason=VALUES(rejected_reason), submitted_at=VALUES(submitted_at), updated_at=VALUES(updated_at)""",
            values,
        )
        if changed:
            self._execute("INSERT INTO order_events (order_id, trade_date, status, filled_quantity, reason, event_at) VALUES (%s, %s, %s, %s, %s, %s)", (order.order_id, day.isoformat(), order.status.value, order.filled_quantity, order.reason or order.rejected_reason, _database_datetime(happened)))
            self._execute(
                "INSERT INTO decision_events (trade_date, symbol, phase, direction, status, filled_quantity, reasons, order_id, event_key, event_at) VALUES (%s, %s, 'order', %s, %s, %s, %s, %s, %s, %s)",
                (
                    day.isoformat(), order.symbol, order.direction.value, order.status.value, order.filled_quantity,
                    _dumps([order.reason or order.rejected_reason] if (order.reason or order.rejected_reason) else []),
                    order.order_id, make_business_event_key("order", day, order.symbol, state, previous_event[0] if previous_event else None),
                    _database_datetime(happened),
                ),
            )
        return order

    def load_open_orders(self, symbol: str | None = None):
        self.initialize()
        statuses = ("已创建", "风控通过", "已提交", "部分成交")
        sql = "SELECT order_id, symbol, direction, quantity, requested_price, status, reason, asset_type, filled_quantity, average_fill_price, created_at, submitted_at, updated_at, rejected_reason FROM orders WHERE status IN (%s, %s, %s, %s)"
        params: tuple = statuses
        if symbol:
            sql += " AND symbol=%s"
            params = (*params, symbol)
        return [_order_from_row(row) for row in self._fetchall(sql + " ORDER BY updated_at ASC", params)]

    def load_orders(self, limit: int = 100):
        self.initialize()
        return [_order_from_row(row) for row in self._fetchall("SELECT order_id, symbol, direction, quantity, requested_price, status, reason, asset_type, filled_quantity, average_fill_price, created_at, submitted_at, updated_at, rejected_reason FROM orders ORDER BY updated_at DESC LIMIT %s", (limit,))]

    def count_symbol_operations(self, trade_date: date, symbol: str) -> int:
        self.initialize()
        row = self._fetchone("SELECT COUNT(*) FROM orders WHERE trade_date=%s AND symbol=%s AND status IN (%s, %s, %s)", (trade_date.isoformat(), symbol, "已成交", "已拒绝", "已取消"))
        return int(row[0]) if row else 0

    def load_decision_events(self, trade_date: date, symbol: str | None = None) -> list[dict]:
        self.initialize()
        sql = "SELECT symbol, phase, direction, approved, target_weight, status, filled_quantity, position_quantity, position_weight, position_state, reasons, strategy_id, order_id, event_key, event_at FROM decision_events WHERE trade_date=%s"
        params: tuple = (trade_date.isoformat(),)
        if symbol:
            sql += " AND symbol=%s"
            params = (*params, symbol)
        return [{"symbol": row[0], "phase": row[1], "direction": row[2], "approved": bool(row[3]) if row[3] is not None else None, "target_weight": str(row[4]) if row[4] is not None else None, "status": row[5], "filled_quantity": int(row[6] or 0), "position_quantity": int(row[7] or 0), "position_weight": str(row[8] or 0), "position_state": row[9], "reasons": _loads(row[10]), "strategy_id": row[11], "order_id": row[12], "event_key": row[13], "event_at": _iso_datetime(row[14])} for row in self._fetchall(sql + " ORDER BY event_at ASC, id ASC", params)]

    def save_futures_positions(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.initialize()
        values = [(
            str(item["trade_date"]), str(item.get("contract", "IC")), str(item.get("top10_long", "0")), str(item.get("top10_short", "0")), str(item.get("top10_net_ratio", "0")), item.get("specific_seat_name"), item.get("specific_seat_long"), item.get("specific_seat_short"), item.get("specific_seat_net_ratio"), str(item.get("combined_net_ratio", "0")), str(item.get("source", "manual")),
        ) for item in rows]
        self._executemany("""INSERT INTO futures_positions (trade_date, contract, top10_long, top10_short, top10_net_ratio, specific_seat_name, specific_seat_long, specific_seat_short, specific_seat_net_ratio, combined_net_ratio, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE top10_long=VALUES(top10_long), top10_short=VALUES(top10_short), top10_net_ratio=VALUES(top10_net_ratio), specific_seat_name=VALUES(specific_seat_name), specific_seat_long=VALUES(specific_seat_long), specific_seat_short=VALUES(specific_seat_short), specific_seat_net_ratio=VALUES(specific_seat_net_ratio), combined_net_ratio=VALUES(combined_net_ratio), source=VALUES(source)""", values)
        return len(values)

    def load_latest_futures_position(self, contract: str = "IC") -> dict | None:
        self.initialize()
        row = self._fetchone("SELECT trade_date, contract, top10_long, top10_short, top10_net_ratio, specific_seat_name, specific_seat_long, specific_seat_short, specific_seat_net_ratio, combined_net_ratio, source FROM futures_positions WHERE contract=%s ORDER BY trade_date DESC LIMIT 1", (contract,))
        return {"trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]), "contract": row[1], "top10_long": str(row[2]), "top10_short": str(row[3]), "top10_net_ratio": str(row[4]), "specific_seat_name": row[5], "specific_seat_long": str(row[6] or 0), "specific_seat_short": str(row[7] or 0), "specific_seat_net_ratio": str(row[8] or 0), "combined_net_ratio": str(row[9]), "source": row[10]} if row else None

    def save_overseas_market_data(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.initialize()
        now = _database_datetime(datetime.now())
        values = []
        for item in rows:
            fetched_at = item.get("fetched_at")
            if isinstance(fetched_at, str):
                try:
                    fetched_at = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                except ValueError:
                    fetched_at = None
            if not isinstance(fetched_at, datetime):
                fetched_at = datetime.now(timezone.utc)
            if fetched_at.tzinfo is not None:
                fetched_at = fetched_at.astimezone(timezone.utc).replace(tzinfo=None)
            values.append((str(item["market"]), str(item["symbol"]), str(item.get("source_symbol") or item["symbol"]), int(bool(item.get("is_proxy", False))), str(item.get("data_status", "ready")), str(item["trade_date"]), item.get("name"), str(item["prev_close"]), str(item["close_price"]), str(item["change_pct"]), str(item.get("source", "akshare")), _database_datetime(fetched_at)))
        self._executemany("""INSERT INTO overseas_market_data (market, symbol, source_symbol, is_proxy, data_status, trade_date, name, prev_close, close_price, change_pct, source, fetched_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE source_symbol=VALUES(source_symbol), is_proxy=VALUES(is_proxy), data_status=VALUES(data_status), name=VALUES(name), prev_close=VALUES(prev_close), close_price=VALUES(close_price), change_pct=VALUES(change_pct), source=VALUES(source), fetched_at=VALUES(fetched_at)""", values)
        return len(values)

    def load_latest_overseas_data(self, market: str | None = None) -> list[dict]:
        self.initialize()
        where, params = ("WHERE market=%s", (market,)) if market else ("", ())
        rows = self._fetchall(f"SELECT o.market, o.symbol, o.source_symbol, o.is_proxy, o.data_status, o.trade_date, o.name, o.prev_close, o.close_price, o.change_pct, o.source, o.fetched_at FROM overseas_market_data o JOIN (SELECT market, symbol, MAX(trade_date) AS latest_date FROM overseas_market_data {where} GROUP BY market, symbol) latest ON latest.market=o.market AND latest.symbol=o.symbol AND latest.latest_date=o.trade_date ORDER BY o.market, o.symbol", params)
        return [{"market": row[0], "symbol": row[1], "source_symbol": row[2], "is_proxy": bool(row[3]), "data_status": row[4], "trade_date": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]), "name": row[6], "prev_close": str(row[7]), "close_price": str(row[8]), "change_pct": str(row[9]), "source": row[10], "fetched_at": row[11].isoformat() if hasattr(row[11], "isoformat") else str(row[11])} for row in rows]

    def save_data_task_status(self, task_name, trade_date, status, success_count, failure_count, error_summary, started_at, finished_at) -> None:
        self.initialize()
        self._execute("""INSERT INTO data_sync_status (task_name, trade_date, status, success_count, failure_count, error_summary, started_at, finished_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE trade_date=VALUES(trade_date), status=VALUES(status), success_count=VALUES(success_count), failure_count=VALUES(failure_count), error_summary=VALUES(error_summary), started_at=VALUES(started_at), finished_at=VALUES(finished_at)""", (task_name, str(trade_date), status, int(success_count), int(failure_count), error_summary, _database_datetime(started_at), _database_datetime(finished_at)))

    def load_data_task_status(self, task_name: str | None = None) -> list[dict]:
        self.initialize()
        where, params = ("WHERE task_name=%s", (task_name,)) if task_name else ("", ())
        rows = self._fetchall(f"SELECT task_name, trade_date, status, success_count, failure_count, error_summary, started_at, finished_at FROM data_sync_status {where} ORDER BY task_name", params)
        return [{"task_name": row[0], "trade_date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]), "status": row[2], "success_count": int(row[3]), "failure_count": int(row[4]), "error_summary": row[5] or "", "started_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]), "finished_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7])} for row in rows]

    def save_sector_mapping(self, symbol: str, sector: str, source: str = "manual") -> None:
        self.initialize()
        self._execute("INSERT INTO instrument_sector_mapping (symbol, sector, source) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE sector=VALUES(sector), source=VALUES(source)", (symbol, sector, source))

    def load_instrument_sector(self, symbol: str) -> str | None:
        self.initialize()
        row = self._fetchone("SELECT sector FROM instrument_sector_mapping WHERE symbol=%s", (symbol,))
        return str(row[0]) if row else None

    def load_sector_mappings(self, symbol: str | None = None) -> list[dict]:
        self.initialize()
        where, params = ("WHERE symbol=%s", (symbol,)) if symbol else ("", ())
        rows = self._fetchall(f"SELECT symbol, sector, source, updated_at FROM instrument_sector_mapping {where} ORDER BY symbol", params)
        return [{"symbol": row[0], "sector": row[1], "source": row[2], "updated_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3])} for row in rows]

    def save_lhb_records(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.initialize()
        values = [(str(item["trade_date"]), str(item["symbol"]), item.get("name"), item.get("sector"), item.get("net_buy"), _dumps_obj(item), str(item.get("source", "akshare"))) for item in rows]
        self._executemany("""INSERT INTO lhb_records (trade_date, symbol, name, sector, net_buy, record_data, source) VALUES (%s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), sector=VALUES(sector), net_buy=VALUES(net_buy), record_data=VALUES(record_data), source=VALUES(source)""", values)
        return len(values)

    def load_lhb_records(self, start: date | None = None, end: date | None = None, symbol: str | None = None) -> list[dict]:
        self.initialize()
        filters, params = [], []
        if start: filters.append("trade_date >= %s"); params.append(start.isoformat())
        if end: filters.append("trade_date <= %s"); params.append(end.isoformat())
        if symbol: filters.append("symbol=%s"); params.append(symbol)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        return [json.loads(row[0]) for row in self._fetchall("SELECT record_data FROM lhb_records" + where + " ORDER BY trade_date DESC", tuple(params))]

    def save_seat_profile(self, row: dict) -> None:
        self.initialize()
        self._execute("INSERT INTO lhb_seat_profile (seat_name, seat_type, quant_firm, buy_count, t3_win_rate, profile_data) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE seat_type=VALUES(seat_type), quant_firm=VALUES(quant_firm), buy_count=VALUES(buy_count), t3_win_rate=VALUES(t3_win_rate), profile_data=VALUES(profile_data)", (row["seat_name"], row.get("seat_type"), row.get("quant_firm"), int(row.get("buy_count", 0)), str(row.get("t3_win_rate", "0")), _dumps_obj(row)))

    def load_seat_profile(self, seat_name: str) -> dict | None:
        self.initialize()
        row = self._fetchone("SELECT profile_data FROM lhb_seat_profile WHERE seat_name=%s", (seat_name,))
        return json.loads(row[0]) if row else None

    def save_quant_seats(self, rows: list[dict]) -> int:
        if not rows: return 0
        self.initialize()
        self._executemany("INSERT INTO lhb_quant_seats (seat_name, quant_firm, strategy_style, notes, is_active) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE quant_firm=VALUES(quant_firm), strategy_style=VALUES(strategy_style), notes=VALUES(notes), is_active=VALUES(is_active)", [(row["seat_name"], row["quant_firm"], row.get("strategy_style"), row.get("notes"), int(row.get("is_active", True))) for row in rows])
        return len(rows)

    def load_quant_seats(self) -> list[dict]:
        self.initialize()
        return [{"seat_name": row[0], "quant_firm": row[1], "strategy_style": row[2], "notes": row[3], "is_active": bool(row[4])} for row in self._fetchall("SELECT seat_name, quant_firm, strategy_style, notes, is_active FROM lhb_quant_seats WHERE is_active=1")]

    def load_fills(self, trade_date: date) -> List[Fill]:
        self.initialize()
        return [_fill_from_row(row) for row in self._fetchall("SELECT symbol, direction, quantity, price, fee, slippage, timestamp_value, order_id FROM fills WHERE trade_date=%s ORDER BY id ASC", (trade_date.isoformat(),))]

    def count_fills(self, trade_date: date, symbol: str | None = None) -> int:
        self.initialize()
        if symbol:
            return int(self._fetchone("SELECT COUNT(*) FROM fills WHERE trade_date=%s AND symbol=%s", (trade_date.isoformat(), symbol))[0])
        return int(self._fetchone("SELECT COUNT(*) FROM fills WHERE trade_date=%s", (trade_date.isoformat(),))[0])

    def load_all_fills(self) -> List[Fill]:
        self.initialize()
        return [_fill_from_row(row) for row in self._fetchall("SELECT symbol, direction, quantity, price, fee, slippage, timestamp_value, order_id FROM fills ORDER BY timestamp_value ASC, id ASC")]

    def record_portfolio_snapshot(self, snapshot_date: date, portfolio: Portfolio) -> None:
        self.initialize()
        self._execute("""INSERT INTO portfolio_snapshots (snapshot_date, cash, total_asset, total_market_value) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE cash=VALUES(cash), total_asset=VALUES(total_asset), total_market_value=VALUES(total_market_value), updated_at=CURRENT_TIMESTAMP""", (snapshot_date.isoformat(), str(portfolio.cash), str(portfolio.total_asset()), str(portfolio.total_market_value())))

    def load_portfolio_snapshots(self) -> list[tuple[date, Decimal]]:
        self.initialize()
        return [(_as_date(row[0]), Decimal(row[1])) for row in self._fetchall("SELECT snapshot_date, total_asset FROM portfolio_snapshots ORDER BY snapshot_date ASC")]

    def ping(self) -> None:
        self.initialize()
        self._fetchone("SELECT 1")

    def last_quote_age_seconds(self) -> float | None:
        self.initialize()
        row = self._fetchone("SELECT MAX(observed_at) FROM market_quotes")
        if not row or row[0] is None:
            return None
        observed = _as_datetime(row[0])
        now = datetime.now(observed.tzinfo) if observed.tzinfo else datetime.now()
        return max(0.0, (now - observed).total_seconds())

    def record_backtest_run(self, strategy_id: str, parameters: dict, metrics: dict, status: str, strategy_profile_id: str = "default") -> None:
        self.initialize()
        self._execute("INSERT INTO backtest_runs (strategy_id, strategy_profile_id, parameters, metrics, status) VALUES (%s, %s, %s, %s, %s)", (strategy_id, strategy_profile_id, _dumps_obj(parameters), _dumps_obj(metrics), status))

    def load_backtest_runs(self, limit: int | None = 20) -> list[dict]:
        self.initialize()
        sql, params = "SELECT id, strategy_id, strategy_profile_id, parameters, metrics, status, confirmed_at, applied_at, created_at FROM backtest_runs ORDER BY id DESC", ()
        if limit is not None:
            sql, params = sql + " LIMIT %s", (limit,)
        rows = self._fetchall(sql, params)
        return [{"id": int(row[0]), "strategy_id": row[1], "strategy_profile_id": row[2], "parameters": json.loads(row[3]), "metrics": json.loads(row[4]), "status": row[5], "confirmed_at": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6], "applied_at": row[7].isoformat() if hasattr(row[7], "isoformat") else row[7], "created_at": row[8].isoformat() if hasattr(row[8], "isoformat") else row[8]} for row in rows]

    def update_backtest_run_status(self, run_ids: list[int], status: str) -> int:
        self.initialize()
        ids = [int(item) for item in run_ids]
        if not ids:
            return 0
        placeholders = ",".join(["%s"] * len(ids))
        return self._execute(f"UPDATE backtest_runs SET status=%s, confirmed_at=CURRENT_TIMESTAMP(6) WHERE id IN ({placeholders})", (status, *ids))

    def mark_backtest_runs_applied(self, run_ids: list[int]) -> int:
        self.initialize()
        ids = [int(item) for item in run_ids]
        if not ids:
            return 0
        placeholders = ",".join(["%s"] * len(ids))
        return self._execute(
            f"UPDATE backtest_runs SET status=%s, applied_at=CURRENT_TIMESTAMP(6) WHERE id IN ({placeholders})",
            ("已应用", *ids),
        )

    def save_daily_report(self, report: dict) -> None:
        self.initialize()
        report = normalize_daily_report(report)
        account = report.get("account") or {}
        self._execute(
            """INSERT INTO daily_reports (report_date, status, summary, total_asset, daily_pnl, daily_return, report_data)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE status=VALUES(status), summary=VALUES(summary), total_asset=VALUES(total_asset),
               daily_pnl=VALUES(daily_pnl), daily_return=VALUES(daily_return), report_data=VALUES(report_data),
               updated_at=CURRENT_TIMESTAMP""",
            (
                str(report["report_date"]),
                str(report.get("status") or "已归档"),
                str(report.get("summary") or ""),
                str(account.get("total_asset") or "0"),
                str(account.get("daily_pnl") or "0"),
                str(account.get("daily_return") or "0"),
                _dumps_obj(report),
            ),
        )

    def load_daily_reports(self, limit: int = 60, offset: int = 0) -> list[dict]:
        self.initialize()
        rows = self._fetchall(
            """SELECT report_date, status, summary, total_asset, daily_pnl, daily_return, updated_at
               FROM daily_reports ORDER BY report_date DESC LIMIT %s OFFSET %s""",
            (max(1, int(limit)), max(0, int(offset))),
        )
        return [
            {
                "report_date": _as_date(row[0]).isoformat(), "status": row[1], "summary": row[2], "total_asset": row[3],
                "daily_pnl": row[4], "daily_return": row[5],
                "updated_at": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6],
            }
            for row in rows
        ]

    def update_watchlist_lifecycle(self, symbol: str, status: str, dormant_since: date | None = None) -> None:
        self.initialize()
        self._execute("UPDATE watchlist_items SET lifecycle_status=%s, trading_enabled=0, dormant_since=%s WHERE symbol=%s", (status, dormant_since.isoformat() if dormant_since else None, symbol))

    def load_recent_decisions(self, symbol: str, limit: int = 20) -> list[Decision]:
        self.initialize()
        rows = self._fetchall("SELECT symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version FROM decisions WHERE symbol=%s ORDER BY trade_date DESC, id DESC LIMIT %s", (symbol, limit))
        return [_decision_from_row(row) for row in rows]

    def load_daily_report(self, report_date: date | str) -> dict | None:
        self.initialize()
        key = report_date.isoformat() if isinstance(report_date, date) else str(report_date)
        row = self._fetchone("SELECT report_data FROM daily_reports WHERE report_date=%s", (key,))
        return normalize_daily_report(json.loads(row[0])) if row else None

    def load_trading_calendar(self, year: int, market: str = "CN") -> dict[date, bool] | None:
        self.initialize()
        rows = self._fetchall(
            "SELECT trade_date, is_trading_day FROM trading_calendar WHERE market=%s AND trade_date >= %s AND trade_date < %s ORDER BY trade_date",
            (market.upper(), f"{int(year):04d}-01-01", f"{int(year) + 1:04d}-01-01"),
        )
        if not rows:
            return None
        return {_as_date(row[0]): bool(row[1]) for row in rows}

    def save_trading_calendar(self, year: int, trading_days: set[date], source: str, covered_until: date | None = None, market: str = "CN") -> int:
        self.initialize()
        start = date(int(year), 1, 1)
        end = covered_until or date(int(year), 12, 31)
        total = (end - start).days + 1
        from datetime import timedelta

        rows = [
            (market.upper(), (start + timedelta(days=index)).isoformat(), int((start + timedelta(days=index)) in trading_days), source)
            for index in range(total)
        ]
        self._executemany(
            "INSERT INTO trading_calendar (market, trade_date, is_trading_day, source) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE is_trading_day=VALUES(is_trading_day), source=VALUES(source), synced_at=CURRENT_TIMESTAMP",
            rows,
        )
        return total

    def ensure_strategy_defaults(self, config) -> None:
        self.initialize()
        definitions = strategy_definitions()
        self._executemany(
            "INSERT IGNORE INTO strategy_definitions (strategy_id, name_zh, name_en, category_zh, category_en, description_zh, description_en) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (item["strategy_id"], item["name_zh"], item["name_en"], item["category_zh"], item["category_en"], item["description_zh"], item["description_en"])
                for item in definitions
            ],
        )
        row = self._fetchone("SELECT profile_data, draft_data FROM strategy_profiles WHERE profile_id=%s", ("default",))
        if row:
            try:
                existing = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                existing = {}
            if int(existing.get("config_schema_version", 1)) < 2 and not row[1]:
                profile = profile_from_config(config, asset_type="etf")
                profile["migration_note"] = "旧默认策略已按新基线生成草稿，等待人工确认。"
                self._execute(
                    "UPDATE strategy_profiles SET draft_data=%s, draft_revision=revision+1, updated_at=CURRENT_TIMESTAMP WHERE profile_id=%s",
                    (_dumps_obj(profile), "default"),
                )
            return
        profile = profile_from_config(config, asset_type="etf")
        self._execute(
            "INSERT INTO strategy_profiles (profile_id, name_zh, name_en, scope_type, scope_value, status, revision, profile_data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            ("default", profile["name_zh"], profile["name_en"], "default", "", "active", 1, _dumps_obj(profile)),
        )

    def load_active_strategy_profile(self, symbol: str, asset_type: str) -> dict | None:
        self.initialize()
        for scope_type, scope_value in (("symbol", symbol), ("asset_type", asset_type), ("default", "")):
            row = self._fetchone("SELECT profile_data FROM strategy_profiles WHERE scope_type=%s AND scope_value=%s AND status=%s ORDER BY revision DESC LIMIT 1", (scope_type, scope_value, "active"))
            if row:
                return json.loads(row[0])
        return None

    def load_strategy_center(self, config) -> dict:
        self.ensure_strategy_defaults(config)
        definitions = self._fetchall("SELECT strategy_id, name_zh, name_en, category_zh, category_en, description_zh, description_en, enabled FROM strategy_definitions ORDER BY strategy_id")
        profiles = self._fetchall(
            "SELECT profile_id, profile_data, status, revision, updated_at, draft_data, draft_revision "
            "FROM strategy_profiles ORDER BY profile_id"
        )
        changes = self._fetchall("SELECT id, profile_id, action, operator_name, before_data, after_data, created_at FROM strategy_change_log ORDER BY id DESC LIMIT 50")
        profile_rows = []
        for row in profiles:
            profile = json.loads(row[1])
            if row[5]:
                profile = json.loads(row[5])
                active_profile = json.loads(row[1])
                profile.update(
                    {
                        "status": "draft",
                        "revision": row[6] or profile.get("revision") or 1,
                        "active_revision": row[3],
                        "pending_confirmation": True,
                        "draft_diff": _profile_diff(active_profile, profile),
                    }
                )
            else:
                profile.update({"status": row[2], "revision": row[3]})
            profile.update(
                {
                    "profile_id": row[0],
                    "updated_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                }
            )
            profile_rows.append(profile)
        return {
            "definitions": [dict(zip(("strategy_id", "name_zh", "name_en", "category_zh", "category_en", "description_zh", "description_en", "enabled"), row)) for row in definitions],
            "profiles": profile_rows,
            "changes": [{"id": row[0], "profile_id": row[1], "action": row[2], "operator": row[3], "before": json.loads(row[4]) if row[4] else None, "after": json.loads(row[5]) if row[5] else None, "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6])} for row in changes],
        }

    def save_strategy_profile(self, profile: dict, operator: str = "web") -> dict:
        self.initialize()
        profile_id = str(profile.get("profile_id") or profile.get("scope_value") or "default")
        previous_row = self._fetchone("SELECT profile_data, revision, status FROM strategy_profiles WHERE profile_id=%s", (profile_id,))
        previous = json.loads(previous_row[0]) if previous_row else None
        revision = int(previous_row[1]) + 1 if previous_row else 1
        saved = dict(profile)
        saved.update({"profile_id": profile_id, "status": "draft", "revision": revision})
        if previous_row and previous_row[2] == "active":
            self._execute(
                "UPDATE strategy_profiles SET draft_data=%s, draft_revision=%s, updated_at=CURRENT_TIMESTAMP WHERE profile_id=%s",
                (_dumps_obj(saved), revision, profile_id),
            )
        else:
            self._execute(
                "INSERT INTO strategy_profiles (profile_id, name_zh, name_en, scope_type, scope_value, status, revision, profile_data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name_zh=VALUES(name_zh), name_en=VALUES(name_en), scope_type=VALUES(scope_type), scope_value=VALUES(scope_value), status=VALUES(status), revision=VALUES(revision), profile_data=VALUES(profile_data), updated_at=CURRENT_TIMESTAMP",
                (profile_id, str(saved.get("name_zh") or profile_id), str(saved.get("name_en") or profile_id), str(saved.get("scope_type") or "symbol"), str(saved.get("scope_value") or profile_id), "draft", revision, _dumps_obj(saved)),
            )
        self._execute(
            "INSERT INTO strategy_change_log (profile_id, action, operator_name, before_data, after_data) VALUES (%s, %s, %s, %s, %s)",
            (profile_id, "save", operator, _dumps_obj(previous) if previous else None, _dumps_obj(saved)),
        )
        return saved

    def confirm_strategy_profile(self, profile_id: str, operator: str = "web") -> dict:
        self.initialize()
        row = self._fetchone("SELECT profile_data, status, draft_data, draft_revision FROM strategy_profiles WHERE profile_id=%s", (str(profile_id),))
        if not row:
            raise ValueError("策略组合不存在。")
        before = json.loads(row[0])
        profile = json.loads(row[2]) if row[2] else before
        profile["status"] = "active"
        revision = int(row[3] or (profile.get("revision") or 1))
        profile["revision"] = revision
        self._execute(
            "UPDATE strategy_profiles SET status=%s, revision=%s, profile_data=%s, draft_data=NULL, draft_revision=NULL, confirmed_by=%s, confirmed_at=CURRENT_TIMESTAMP(6), effective_monitor_round=%s, updated_at=CURRENT_TIMESTAMP WHERE profile_id=%s",
            ("active", revision, _dumps_obj(profile), operator, "next", str(profile_id)),
        )
        self._execute("INSERT INTO strategy_change_log (profile_id, action, operator_name, before_data, after_data) VALUES (%s, %s, %s, %s, %s)", (str(profile_id), "confirm", operator, _dumps_obj(before), _dumps_obj(profile)))
        return profile

    def apply_pending_strategy_profiles(self, operator: str = "monitor") -> list[dict]:
        self.initialize()
        rows = self._fetchall("SELECT profile_id, profile_data, draft_data, draft_revision FROM strategy_profiles WHERE draft_data IS NOT NULL")
        applied = []
        for profile_id, active_data, draft_data, draft_revision in rows:
            draft = json.loads(draft_data)
            if not draft.get("pending_activation"):
                continue
            before = json.loads(active_data)
            draft.update({
                "status": "active",
                "pending_activation": False,
                "confirmed_by": operator,
                "confirmed_at": datetime.now().isoformat(),
                "effective_monitor_round": "current",
                "revision": int(draft_revision or draft.get("revision") or 1),
            })
            self._execute(
                "UPDATE strategy_profiles SET status=%s, revision=%s, profile_data=%s, draft_data=NULL, draft_revision=NULL, confirmed_by=%s, confirmed_at=CURRENT_TIMESTAMP(6), effective_monitor_round=%s, updated_at=CURRENT_TIMESTAMP WHERE profile_id=%s",
                ("active", draft["revision"], _dumps_obj(draft), operator, "current", profile_id),
            )
            self._execute(
                "INSERT INTO strategy_change_log (profile_id, action, operator_name, before_data, after_data) VALUES (%s, %s, %s, %s, %s)",
                (profile_id, "apply_backtest", operator, _dumps_obj(before), _dumps_obj(draft)),
            )
            applied.append({"profile_id": profile_id, "source_backtest_id": draft.get("source_backtest_id")})
        return applied

    def discard_strategy_draft(self, profile_id: str, operator: str = "web") -> None:
        self.initialize()
        row = self._fetchone("SELECT profile_data, draft_data, status FROM strategy_profiles WHERE profile_id=%s", (profile_id,))
        if not row:
            raise ValueError("没有可撤销的策略草稿。")
        profile_data, draft_data, status = row
        if draft_data:
            self._execute("UPDATE strategy_profiles SET draft_data=NULL, draft_revision=NULL WHERE profile_id=%s", (profile_id,))
            before = json.loads(draft_data)
        elif status == "draft":
            self._execute("DELETE FROM strategy_profiles WHERE profile_id=%s", (profile_id,))
            before = json.loads(profile_data)
        else:
            raise ValueError("没有可撤销的策略草稿。")
        self._execute("INSERT INTO strategy_change_log (profile_id, action, operator_name, before_data, after_data) VALUES (%s, %s, %s, %s, NULL)", (profile_id, "discard_draft", operator, _dumps_obj(before)))

    def load_active_risk_config(self) -> dict | None:
        self.initialize()
        row = self._fetchone("SELECT value FROM metadata WHERE `key`=%s", ("risk_config_active",))
        return json.loads(row[0]) if row else None

    def load_risk_config_draft(self) -> dict | None:
        self.initialize()
        row = self._fetchone("SELECT value FROM metadata WHERE `key`=%s", ("risk_config_draft",))
        return json.loads(row[0]) if row else None

    def save_risk_config_draft(self, payload: dict, operator: str = "web") -> dict:
        self.initialize()
        draft = {**payload, "status": "draft", "pending_confirmation": True, "operator": operator}
        self._execute(
            "INSERT INTO metadata (`key`, value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=CURRENT_TIMESTAMP",
            ("risk_config_draft", _dumps_obj(draft)),
        )
        return draft

    def confirm_risk_config(self, operator: str = "web") -> dict:
        self.initialize()
        row = self._fetchone("SELECT value FROM metadata WHERE `key`=%s", ("risk_config_draft",))
        if not row:
            raise ValueError("没有待确认的风险配置草稿。")
        active = json.loads(row[0])
        active.update({"status": "active", "pending_confirmation": False, "operator": operator})
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO metadata (`key`, value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=CURRENT_TIMESTAMP",
                    ("risk_config_active", _dumps_obj(active)),
                )
                cursor.execute("DELETE FROM metadata WHERE `key`=%s", ("risk_config_draft",))
        return active

    def settle_t_plus_one(self, settle_date: date | None = None) -> bool:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                if settle_date:
                    cursor.execute("SELECT value FROM metadata WHERE `key`=%s", ("last_settle_date",))
                    row = cursor.fetchone()
                    if row and row[0] == settle_date.isoformat():
                        return False
                cursor.execute("UPDATE positions SET available_quantity=quantity, updated_at=CURRENT_TIMESTAMP")
                if settle_date:
                    cursor.execute("INSERT INTO metadata (`key`, value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=CURRENT_TIMESTAMP", ("last_settle_date", settle_date.isoformat()))
        return True

    @contextmanager
    def _connect(self) -> Iterator[object]:
        self._validate_connection_settings()
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("缺少 PyMySQL 依赖，请重新构建发布镜像或安装 pymysql。") from exc
        connection = self._acquire_connection(pymysql)
        healthy = True
        try:
            yield connection
            connection.commit()
        except Exception:
            healthy = False
            connection.rollback()
            raise
        finally:
            self._release_connection(connection, healthy)

    def _get_pool(self) -> LifoQueue:
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    self._pool = LifoQueue(maxsize=self._pool_size)
        return self._pool

    def _acquire_connection(self, pymysql):
        pool = self._get_pool()
        while True:
            try:
                connection = pool.get_nowait()
            except Empty:
                with self._pool_lock:
                    if self._pool_total < self._pool_size:
                        self._pool_total += 1
                        try:
                            return pymysql.connect(
                                host=self.host,
                                port=self.port,
                                user=self.username,
                                password=self.password,
                                database=self.database,
                                charset="utf8mb4",
                                autocommit=False,
                            )
                        except Exception:
                            self._pool_total -= 1
                            raise
                connection = pool.get()
            try:
                connection.ping(reconnect=True)
                return connection
            except Exception:
                connection.close()
                with self._pool_lock:
                    self._pool_total = max(0, self._pool_total - 1)

    def _release_connection(self, connection, healthy: bool = True) -> None:
        if not healthy:
            connection.close()
            with self._pool_lock:
                self._pool_total = max(0, self._pool_total - 1)
            return
        try:
            self._get_pool().put_nowait(connection)
        except Exception:
            connection.close()
            with self._pool_lock:
                self._pool_total = max(0, self._pool_total - 1)

    def close(self) -> None:
        """Close pooled connections during orderly process shutdown."""
        pool = self._pool
        if pool is None:
            return
        while True:
            try:
                pool.get_nowait().close()
            except Empty:
                break
        with self._pool_lock:
            self._pool_total = 0
        self._pool = None

    def _validate_connection_settings(self) -> None:
        values = (self.host, self.database, self.username, self.password)
        if not all(values) or any(str(value).startswith("${") for value in values):
            raise ValueError("MySQL 发布配置不完整，请在部署环境设置 STOCK_AI_MYSQL_* 变量。")

    def _execute(self, sql: str, params: tuple = ()) -> int:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return int(cursor.rowcount)

    def _executemany(self, sql: str, rows: list[tuple]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(sql, rows)

    def _fetchone(self, sql: str, params: tuple = ()):
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()

    def _fetchall(self, sql: str, params: tuple = ()):
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()


def _bar_from_row(row: tuple, price_mode: str = "qfq") -> Bar:
    factor = Decimal(row[8]) if len(row) > 8 else Decimal("1")
    return Bar(row[0], _as_datetime(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), Decimal(row[6]), Decimal(row[7]), price_mode, factor)


def _database_datetime(value: datetime) -> str:
    """Store timezone-aware application timestamps as local DATETIME values."""
    if value.tzinfo is not None:
        from zoneinfo import ZoneInfo

        value = value.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    return value.isoformat(sep=" ")


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _quote_trade_date(quote: Quote) -> str:
    timestamp = quote.fetched_at
    if isinstance(timestamp, date) and not isinstance(timestamp, datetime):
        return timestamp.isoformat()
    if timestamp.tzinfo is not None:
        from zoneinfo import ZoneInfo
        timestamp = timestamp.astimezone(ZoneInfo("Asia/Shanghai"))
    return timestamp.date().isoformat()


def _quote_row(row: tuple) -> dict:
    return {"symbol": row[0], "name": row[1], "latest_price": Decimal(row[2]), "change_percent": Decimal(row[3]), "previous_close": Decimal(row[4]), "quoted_at": _iso_datetime(row[5]), "observed_at": _iso_datetime(row[6]), "source": row[7]}


def _iso_datetime(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _quote_ticks_to_minute_bars(ticks: list[dict]) -> list[Bar]:
    from zoneinfo import ZoneInfo

    timezone = ZoneInfo("Asia/Shanghai")
    grouped: dict[tuple[str, datetime], list[dict]] = {}
    for tick in ticks:
        timestamp = datetime.fromisoformat(str(tick["observed_at"]))
        timestamp = timestamp.replace(tzinfo=timezone) if timestamp.tzinfo is None else timestamp.astimezone(timezone)
        bucket = timestamp.replace(second=0, microsecond=0)
        grouped.setdefault((str(tick["symbol"]), bucket), []).append(tick)
    bars: list[Bar] = []
    for (symbol, timestamp), group in sorted(grouped.items(), key=lambda item: item[0][1]):
        prices = [Decimal(str(item["latest_price"])) for item in group]
        bars.append(Bar(symbol, timestamp, prices[0], max(prices), min(prices), prices[-1], Decimal("0"), Decimal("0")))
    return bars


def _fill_from_row(row: tuple) -> Fill:
    return Fill(row[0], Direction(row[1]), int(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), _as_datetime(row[6]), row[7] or "" if len(row) > 7 else "")


def _order_from_row(row: tuple) -> PaperOrder:
    return PaperOrder(row[1], Direction(row[2]), int(row[3]), Decimal(row[4]), OrderStatus(row[5]), row[6] or "", row[0], row[7] or "etf", int(row[8] or 0), Decimal(row[9] or "0"), _as_datetime(row[10]), _as_datetime(row[11]) if row[11] else None, _as_datetime(row[12]) if row[12] else None, row[13] or "")


def _decision_from_row(row: tuple) -> Decision:
    signal = None
    if row[5]:
        signal = StrategySignal(row[5], row[0], Direction(row[1]), Decimal(row[6] or "0"), Decimal(row[7] or "0"), Decimal(row[8] or row[2]), _loads(row[9]), _loads(row[10]), row[11] or "", row[12] or "v1")
    return Decision(row[0], Direction(row[1]), Decimal(row[2]), bool(row[3]), _loads(row[4]), signal)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=isinstance(value, dict))


def _dumps_obj(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _profile_diff(active: dict, draft: dict) -> list[dict]:
    """Compact draft comparison consumed by the strategy-center confirmation UI."""
    ignored = {"status", "revision", "updated_at", "confirmed_at", "confirmed_by", "effective_monitor_round", "pending_activation", "pending_confirmation", "source_backtest_id", "source_backtest_parameters"}
    return [
        {"field": key, "before": active.get(key), "after": draft.get(key)}
        for key in sorted((set(active) | set(draft)) - ignored)
        if active.get(key) != draft.get(key)
    ]


def _loads(value: str | None) -> list[str]:
    return [str(item) for item in json.loads(value)] if value else []
