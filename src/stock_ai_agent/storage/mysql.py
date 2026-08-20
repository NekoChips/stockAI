from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator, List

from ..config import MySQLConnectionConfig
from ..models import Bar, Decision, Direction, Fill, Portfolio, Position, StrategySignal


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

    def initialize(self) -> None:
        statements = [
            """CREATE TABLE IF NOT EXISTS bars (
                symbol VARCHAR(32) NOT NULL, interval_name VARCHAR(16) NOT NULL, timestamp_value VARCHAR(40) NOT NULL,
                open_price VARCHAR(40) NOT NULL, high_price VARCHAR(40) NOT NULL, low_price VARCHAR(40) NOT NULL,
                close_price VARCHAR(40) NOT NULL, volume VARCHAR(40) NOT NULL, amount VARCHAR(40) NOT NULL,
                source VARCHAR(64) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval_name, timestamp_value)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS account_state (
                id VARCHAR(32) PRIMARY KEY, cash VARCHAR(40) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS positions (
                symbol VARCHAR(32) PRIMARY KEY, quantity BIGINT NOT NULL, available_quantity BIGINT NOT NULL,
                average_cost VARCHAR(40) NOT NULL, last_price VARCHAR(40) NOT NULL, realized_pnl VARCHAR(40) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS decisions (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date VARCHAR(16) NOT NULL, symbol VARCHAR(32) NOT NULL,
                direction VARCHAR(16) NOT NULL, target_weight VARCHAR(40) NOT NULL, approved TINYINT NOT NULL,
                reasons TEXT NOT NULL, signal_strategy_id VARCHAR(128), signal_score VARCHAR(40),
                signal_confidence VARCHAR(40), signal_target_weight VARCHAR(40), signal_evidence TEXT,
                signal_objections TEXT, signal_explanation TEXT, signal_version VARCHAR(64),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_decisions_trade_date (trade_date)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS fills (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, trade_date VARCHAR(16) NOT NULL, symbol VARCHAR(32) NOT NULL,
                direction VARCHAR(16) NOT NULL, quantity BIGINT NOT NULL, price VARCHAR(40) NOT NULL,
                fee VARCHAR(40) NOT NULL, slippage VARCHAR(40) NOT NULL, timestamp_value VARCHAR(40) NOT NULL,
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
                source VARCHAR(64) NOT NULL, synced_date VARCHAR(16) NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_instrument_catalog_name (name)
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                snapshot_date VARCHAR(16) PRIMARY KEY, cash VARCHAR(40) NOT NULL, total_asset VARCHAR(40) NOT NULL,
                total_market_value VARCHAR(40) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
            """CREATE TABLE IF NOT EXISTS backtest_runs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY, strategy_id VARCHAR(128) NOT NULL, parameters TEXT NOT NULL,
                metrics TEXT NOT NULL, status VARCHAR(32) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4""",
        ]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def save_bars(self, bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        if not bars:
            return 0
        self.initialize()
        rows = [(bar.symbol, interval, bar.timestamp.isoformat(), str(bar.open_price), str(bar.high_price), str(bar.low_price), str(bar.close_price), str(bar.volume), str(bar.amount), source) for bar in bars]
        sql = """INSERT INTO bars (symbol, interval_name, timestamp_value, open_price, high_price, low_price, close_price, volume, amount, source)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON DUPLICATE KEY UPDATE open_price=VALUES(open_price), high_price=VALUES(high_price), low_price=VALUES(low_price), close_price=VALUES(close_price), volume=VALUES(volume), amount=VALUES(amount), source=VALUES(source), updated_at=CURRENT_TIMESTAMP"""
        self._executemany(sql, rows)
        return len(rows)

    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> List[Bar]:
        self.initialize()
        if limit is None:
            rows = self._fetchall("SELECT symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount FROM bars WHERE symbol=%s AND interval_name=%s ORDER BY timestamp_value ASC", (symbol, interval))
        else:
            rows = self._fetchall("SELECT * FROM (SELECT symbol, timestamp_value, open_price, high_price, low_price, close_price, volume, amount FROM bars WHERE symbol=%s AND interval_name=%s ORDER BY timestamp_value DESC LIMIT %s) AS recent ORDER BY timestamp_value ASC", (symbol, interval, limit))
        return [_bar_from_row(row) for row in rows]

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
        signal = decision.source_signal
        self._execute("""INSERT INTO decisions (trade_date, symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (trade_date.isoformat(), decision.symbol, decision.direction.value, str(decision.target_weight), int(decision.approved), _dumps(decision.reasons), signal.strategy_id if signal else None, str(signal.score) if signal else None, str(signal.confidence) if signal else None, str(signal.target_weight) if signal else None, _dumps(signal.evidence) if signal else None, _dumps(signal.objections) if signal else None, signal.explanation if signal else None, signal.version if signal else None))

    def load_decisions(self, trade_date: date) -> List[Decision]:
        self.initialize()
        rows = self._fetchall("SELECT symbol, direction, target_weight, approved, reasons, signal_strategy_id, signal_score, signal_confidence, signal_target_weight, signal_evidence, signal_objections, signal_explanation, signal_version FROM decisions WHERE trade_date=%s ORDER BY id ASC", (trade_date.isoformat(),))
        return [_decision_from_row(row) for row in rows]

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        self.initialize()
        self._execute("INSERT INTO fills (trade_date, symbol, direction, quantity, price, fee, slippage, timestamp_value) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", ((trade_date or fill.timestamp.date()).isoformat(), fill.symbol, fill.direction.value, fill.quantity, str(fill.price), str(fill.fee), str(fill.slippage), fill.timestamp.isoformat()))

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
        return [(date.fromisoformat(row[0]), Decimal(row[1])) for row in self._fetchall("SELECT snapshot_date, total_asset FROM portfolio_snapshots ORDER BY snapshot_date ASC")]

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
        connection = pymysql.connect(host=self.host, port=self.port, user=self.username, password=self.password, database=self.database, charset="utf8mb4", autocommit=False)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
    return Bar(row[0], datetime.fromisoformat(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), Decimal(row[6]), Decimal(row[7]))


def _fill_from_row(row: tuple) -> Fill:
    return Fill(row[0], Direction(row[1]), int(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), datetime.fromisoformat(row[6]))


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
