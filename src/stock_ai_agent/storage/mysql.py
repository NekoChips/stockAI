from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from queue import Empty, LifoQueue
from threading import Lock
from typing import Iterator, List

from ..config import MySQLConnectionConfig
from ..models import Bar, Decision, Direction, Fill, Portfolio, Position, Quote, StrategySignal
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
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS decisions (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL,
                direction VARCHAR(16) NOT NULL, target_weight DECIMAL(12,8) NOT NULL, approved TINYINT NOT NULL,
                reasons TEXT NOT NULL, signal_strategy_id VARCHAR(128), signal_score DECIMAL(12,8),
                signal_confidence DECIMAL(12,8), signal_target_weight DECIMAL(12,8), signal_evidence TEXT,
                signal_objections TEXT, signal_explanation TEXT, signal_version VARCHAR(64),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_decisions_trade_date (trade_date)
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
            """CREATE TABLE IF NOT EXISTS fills (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date DATE NOT NULL, symbol VARCHAR(32) NOT NULL,
                direction VARCHAR(16) NOT NULL, quantity BIGINT NOT NULL, price DECIMAL(20,6) NOT NULL,
                fee DECIMAL(20,6) NOT NULL, slippage DECIMAL(20,6) NOT NULL, timestamp_value DATETIME(6) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_fills_trade_date (trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS metadata (
                `key` VARCHAR(128) PRIMARY KEY, value TEXT NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS watchlist_items (
                symbol VARCHAR(32) PRIMARY KEY, name VARCHAR(128) NOT NULL, asset_type VARCHAR(16) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS watchlist_exclusions (
                symbol VARCHAR(32) PRIMARY KEY, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                id BIGINT AUTO_INCREMENT PRIMARY KEY, strategy_id VARCHAR(128) NOT NULL, parameters TEXT NOT NULL,
                metrics TEXT NOT NULL, status VARCHAR(32) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS daily_reports (
                report_date DATE PRIMARY KEY, status VARCHAR(32) NOT NULL, summary TEXT NOT NULL,
                total_asset DECIMAL(20,6) NOT NULL, daily_pnl DECIMAL(20,6) NOT NULL, daily_return DECIMAL(20,8) NOT NULL,
                report_data LONGTEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS trading_calendar (
                trade_date DATE PRIMARY KEY, is_trading_day TINYINT NOT NULL,
                source VARCHAR(64) NOT NULL, synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_trading_calendar_flag (is_trading_day, trade_date)
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
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_strategy_profiles_scope (scope_type, scope_value, status)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS strategy_change_log (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, profile_id VARCHAR(128) NOT NULL, action VARCHAR(32) NOT NULL,
                operator_name VARCHAR(128) NOT NULL, before_data LONGTEXT, after_data LONGTEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_strategy_change_log_profile (profile_id, created_at)
            ) CHARACTER SET utf8mb4""",
        ]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                self._migrate_market_quotes(cursor)
                self._migrate_strategy_profiles(cursor)

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

    def load_bars(
        self,
        symbol: str,
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
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
        select = "symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount"
        if limit is None:
            rows = self._fetchall(f"SELECT {select} FROM bars WHERE {where} ORDER BY timestamp_value ASC", tuple(params))
        else:
            rows = self._fetchall(f"SELECT * FROM (SELECT {select} FROM bars WHERE {where} ORDER BY timestamp_value DESC LIMIT %s) AS recent ORDER BY timestamp_value ASC", (*params, limit))
        return [_bar_from_row(row) for row in rows]

    def load_bars_batch(
        self,
        symbols: list[str],
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
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
        rows = self._fetchall(
            f"SELECT symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount "
            f"FROM bars WHERE {' AND '.join(filters)} ORDER BY symbol ASC, timestamp_value DESC",
            tuple(params),
        )
        result = {symbol: [] for symbol in symbols}
        for row in rows:
            bucket = result.setdefault(row[0], [])
            if limit is None or len(bucket) < limit:
                bucket.append(_bar_from_row(row))
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
        return [{"symbol": row[0], "name": row[1], "asset_type": row[2]} for row in self._fetchall("SELECT symbol, name, asset_type FROM watchlist_items ORDER BY created_at ASC, symbol ASC")]

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM watchlist_exclusions WHERE symbol=%s", (symbol,))
                cursor.execute("INSERT INTO watchlist_items (symbol, name, asset_type) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), asset_type=VALUES(asset_type), updated_at=CURRENT_TIMESTAMP", (symbol, name, asset_type))

    def remove_watchlist_item(self, symbol: str) -> None:
        self.initialize()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM watchlist_items WHERE symbol=%s", (symbol,))
                cursor.execute("INSERT IGNORE INTO watchlist_exclusions (symbol) VALUES (%s)", (symbol,))

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
        for row in self._fetchall("SELECT symbol, quantity, available_quantity, average_cost, last_price, realized_pnl FROM positions ORDER BY symbol ASC"):
            portfolio.positions[row[0]] = Position(row[0], int(row[1]), int(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]))
        return portfolio

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self.initialize()
        rows = [(item.symbol, item.quantity, item.available_quantity, str(item.average_cost), str(item.last_price), str(item.realized_pnl)) for item in portfolio.positions.values()]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO account_state (id, cash) VALUES (%s, %s) ON DUPLICATE KEY UPDATE cash=VALUES(cash), updated_at=CURRENT_TIMESTAMP", ("paper", str(portfolio.cash)))
                cursor.execute("DELETE FROM positions")
                if rows:
                    cursor.executemany("INSERT INTO positions (symbol, quantity, available_quantity, average_cost, last_price, realized_pnl) VALUES (%s, %s, %s, %s, %s, %s)", rows)

    def record_decision(self, decision: Decision, trade_date: date) -> None:
        self.initialize()
        if decision.direction == Direction.WATCH and self._fetchone(
            "SELECT 1 FROM decisions WHERE trade_date=%s AND symbol=%s AND direction=%s LIMIT 1",
            (trade_date.isoformat(), decision.symbol, Direction.WATCH.value),
        ):
            return
        signal = decision.source_signal
        self._execute("""INSERT INTO decisions (trade_date, symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (trade_date.isoformat(), decision.symbol, decision.direction.value, str(decision.target_weight), int(decision.approved), _dumps(decision.reasons), signal.strategy_id if signal else None, str(signal.score) if signal else None, str(signal.confidence) if signal else None, str(signal.target_weight) if signal else None, _dumps(signal.evidence) if signal else None, _dumps(signal.objections) if signal else None, signal.explanation if signal else None, signal.version if signal else None))

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

    def load_decisions(self, trade_date: date) -> List[Decision]:
        self.initialize()
        rows = self._fetchall("SELECT symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version FROM decisions WHERE trade_date=%s ORDER BY id ASC", (trade_date.isoformat(),))
        return [_decision_from_row(row) for row in rows]

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        self.initialize()
        self._execute("INSERT INTO fills (trade_date, symbol, direction, quantity, price, fee, slippage, timestamp_value) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", ((trade_date or fill.timestamp.date()).isoformat(), fill.symbol, fill.direction.value, fill.quantity, str(fill.price), str(fill.fee), str(fill.slippage), _database_datetime(fill.timestamp)))

    def load_fills(self, trade_date: date) -> List[Fill]:
        self.initialize()
        return [_fill_from_row(row) for row in self._fetchall("SELECT symbol, direction, quantity, price, fee, slippage, timestamp_value FROM fills WHERE trade_date=%s ORDER BY id ASC", (trade_date.isoformat(),))]

    def count_fills(self, trade_date: date) -> int:
        self.initialize()
        return int(self._fetchone("SELECT COUNT(*) FROM fills WHERE trade_date=%s", (trade_date.isoformat(),))[0])

    def load_all_fills(self) -> List[Fill]:
        self.initialize()
        return [_fill_from_row(row) for row in self._fetchall("SELECT symbol, direction, quantity, price, fee, slippage, timestamp_value FROM fills ORDER BY timestamp_value ASC, id ASC")]

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

    def record_backtest_run(self, strategy_id: str, parameters: dict, metrics: dict, status: str) -> None:
        self.initialize()
        self._execute("INSERT INTO backtest_runs (strategy_id, parameters, metrics, status) VALUES (%s, %s, %s, %s)", (strategy_id, _dumps_obj(parameters), _dumps_obj(metrics), status))

    def load_backtest_runs(self, limit: int | None = 20) -> list[dict]:
        self.initialize()
        sql, params = "SELECT id, strategy_id, parameters, metrics, status, created_at FROM backtest_runs ORDER BY id DESC", ()
        if limit is not None:
            sql, params = sql + " LIMIT %s", (limit,)
        rows = self._fetchall(sql, params)
        return [{"id": int(row[0]), "strategy_id": row[1], "parameters": json.loads(row[2]), "metrics": json.loads(row[3]), "status": row[4], "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5]} for row in rows]

    def update_backtest_run_status(self, run_ids: list[int], status: str) -> int:
        self.initialize()
        ids = [int(item) for item in run_ids]
        if not ids:
            return 0
        placeholders = ",".join(["%s"] * len(ids))
        return self._execute(f"UPDATE backtest_runs SET status=%s WHERE id IN ({placeholders})", (status, *ids))

    def save_daily_report(self, report: dict) -> None:
        self.initialize()
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

    def load_daily_report(self, report_date: date | str) -> dict | None:
        self.initialize()
        key = report_date.isoformat() if isinstance(report_date, date) else str(report_date)
        row = self._fetchone("SELECT report_data FROM daily_reports WHERE report_date=%s", (key,))
        return json.loads(row[0]) if row else None

    def load_trading_calendar(self, year: int) -> dict[date, bool] | None:
        self.initialize()
        rows = self._fetchall(
            "SELECT trade_date, is_trading_day FROM trading_calendar WHERE trade_date >= %s AND trade_date < %s ORDER BY trade_date",
            (f"{int(year):04d}-01-01", f"{int(year) + 1:04d}-01-01"),
        )
        if not rows:
            return None
        return {_as_date(row[0]): bool(row[1]) for row in rows}

    def save_trading_calendar(self, year: int, trading_days: set[date], source: str, covered_until: date | None = None) -> int:
        self.initialize()
        start = date(int(year), 1, 1)
        end = covered_until or date(int(year), 12, 31)
        total = (end - start).days + 1
        from datetime import timedelta

        rows = [
            ((start + timedelta(days=index)).isoformat(), int((start + timedelta(days=index)) in trading_days), source)
            for index in range(total)
        ]
        self._executemany(
            "INSERT INTO trading_calendar (trade_date, is_trading_day, source) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE is_trading_day=VALUES(is_trading_day), source=VALUES(source), synced_at=CURRENT_TIMESTAMP",
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
        if self._fetchone("SELECT profile_id FROM strategy_profiles WHERE profile_id=%s", ("default",)):
            return
        profile = profile_from_config(config)
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
                profile.update(
                    {
                        "status": "draft",
                        "revision": row[6] or profile.get("revision") or 1,
                        "active_revision": row[3],
                        "pending_confirmation": True,
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
        self._execute("UPDATE strategy_profiles SET status=%s, revision=%s, profile_data=%s, draft_data=NULL, draft_revision=NULL, updated_at=CURRENT_TIMESTAMP WHERE profile_id=%s", ("active", revision, _dumps_obj(profile), str(profile_id)))
        self._execute("INSERT INTO strategy_change_log (profile_id, action, operator_name, before_data, after_data) VALUES (%s, %s, %s, %s, %s)", (str(profile_id), "confirm", operator, _dumps_obj(before), _dumps_obj(profile)))
        return profile

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


def _bar_from_row(row: tuple) -> Bar:
    return Bar(row[0], _as_datetime(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), Decimal(row[6]), Decimal(row[7]))


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
    return Fill(row[0], Direction(row[1]), int(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), _as_datetime(row[6]))


def _decision_from_row(row: tuple) -> Decision:
    signal = None
    if row[5]:
        signal = StrategySignal(row[5], row[0], Direction(row[1]), Decimal(row[6] or "0"), Decimal(row[7] or "0"), Decimal(row[8] or row[2]), _loads(row[9]), _loads(row[10]), row[11] or "", row[12] or "v1")
    return Decision(row[0], Direction(row[1]), Decimal(row[2]), bool(row[3]), _loads(row[4]), signal)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=isinstance(value, dict))


def _dumps_obj(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None) -> list[str]:
    return [str(item) for item in json.loads(value)] if value else []
