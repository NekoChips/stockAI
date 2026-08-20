from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import List

from ..models import Bar, Decision, Direction, Fill, Portfolio, Position, StrategySignal


class SQLiteMarketDataStore:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bars (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open_price TEXT NOT NULL,
                    high_price TEXT NOT NULL,
                    low_price TEXT NOT NULL,
                    close_price TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (symbol, interval, timestamp)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS account_state (
                    id TEXT PRIMARY KEY,
                    cash TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    available_quantity INTEGER NOT NULL,
                    average_cost TEXT NOT NULL,
                    last_price TEXT NOT NULL,
                    realized_pnl TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    target_weight TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    reasons TEXT NOT NULL,
                    signal_strategy_id TEXT,
                    signal_score TEXT,
                    signal_confidence TEXT,
                    signal_target_weight TEXT,
                    signal_evidence TEXT,
                    signal_objections TEXT,
                    signal_explanation TEXT,
                    signal_version TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    slippage TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_items (
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist_exclusions (
                    symbol TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS instrument_catalog (
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    synced_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_instrument_catalog_name ON instrument_catalog(name)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    snapshot_date TEXT PRIMARY KEY,
                    cash TEXT NOT NULL,
                    total_asset TEXT NOT NULL,
                    total_market_value TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save_bars(self, bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        if not bars:
            return 0
        self.initialize()
        rows = [
            (
                bar.symbol,
                interval,
                bar.timestamp.isoformat(),
                str(bar.open_price),
                str(bar.high_price),
                str(bar.low_price),
                str(bar.close_price),
                str(bar.volume),
                str(bar.amount),
                source,
            )
            for bar in bars
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO bars (
                    symbol, interval, timestamp, open_price, high_price, low_price,
                    close_price, volume, amount, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, timestamp) DO UPDATE SET
                    open_price=excluded.open_price,
                    high_price=excluded.high_price,
                    low_price=excluded.low_price,
                    close_price=excluded.close_price,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                rows,
            )
        return len(rows)

    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> List[Bar]:
        self.initialize()
        sql = (
            "SELECT symbol, timestamp, open_price, high_price, low_price, close_price, volume, amount "
            "FROM bars WHERE symbol = ? AND interval = ? ORDER BY timestamp ASC"
        )
        params: list[object] = [symbol, interval]
        if limit is not None:
            sql = (
                "SELECT * FROM ("
                "SELECT symbol, timestamp, open_price, high_price, low_price, close_price, volume, amount "
                "FROM bars WHERE symbol = ? AND interval = ? ORDER BY timestamp DESC LIMIT ?"
                ") ORDER BY timestamp ASC"
            )
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            Bar(
                symbol=row[0],
                timestamp=datetime.fromisoformat(row[1]),
                open_price=Decimal(row[2]),
                high_price=Decimal(row[3]),
                low_price=Decimal(row[4]),
                close_price=Decimal(row[5]),
                volume=Decimal(row[6]),
                amount=Decimal(row[7]),
            )
            for row in rows
        ]

    def load_watchlist_items(self) -> list[dict[str, str]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, name, asset_type FROM watchlist_items ORDER BY created_at ASC, symbol ASC"
            ).fetchall()
        return [{"symbol": row[0], "name": row[1], "asset_type": row[2]} for row in rows]

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist_exclusions WHERE symbol = ?", (symbol,))
            conn.execute(
                """
                INSERT INTO watchlist_items (symbol, name, asset_type)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name=excluded.name,
                    asset_type=excluded.asset_type,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (symbol, name, asset_type),
            )

    def remove_watchlist_item(self, symbol: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist_items WHERE symbol = ?", (symbol,))
            conn.execute(
                "INSERT OR IGNORE INTO watchlist_exclusions (symbol) VALUES (?)",
                (symbol,),
            )

    def restore_watchlist_item(self, symbol: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist_exclusions WHERE symbol = ?", (symbol,))

    def load_removed_watchlist_symbols(self) -> set[str]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute("SELECT symbol FROM watchlist_exclusions").fetchall()
        return {str(row[0]) for row in rows}

    def replace_instrument_catalog(self, items: list[dict[str, str]], synced_date: str, source: str) -> int:
        if not items:
            return 0
        self.initialize()
        rows = [
            (str(item["symbol"]), str(item["name"]), str(item["asset_type"]), source, synced_date)
            for item in items
        ]
        with self._connect() as conn:
            conn.execute("DELETE FROM instrument_catalog")
            conn.executemany(
                """
                INSERT INTO instrument_catalog (symbol, name, asset_type, source, synced_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.execute(
                """
                INSERT INTO metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                """,
                ("instrument_catalog_synced_date", synced_date),
            )
        return len(rows)

    def search_instrument_catalog(self, query: str, limit: int = 12) -> list[dict[str, str]]:
        self.initialize()
        text = str(query).strip().upper()
        if not text:
            return []
        pattern = f"%{text}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, name, asset_type
                FROM instrument_catalog
                WHERE UPPER(symbol) LIKE ? OR UPPER(name) LIKE ?
                ORDER BY CASE WHEN UPPER(symbol) = ? THEN 0 ELSE 1 END, name ASC
                LIMIT ?
                """,
                (pattern, pattern, text, int(limit)),
            ).fetchall()
        return [{"symbol": row[0], "name": row[1], "asset_type": row[2]} for row in rows]

    def instrument_catalog_status(self) -> dict[str, str | int]:
        self.initialize()
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM instrument_catalog").fetchone()[0]
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("instrument_catalog_synced_date",)).fetchone()
        return {"count": int(count), "synced_date": row[0] if row else ""}

    def load_portfolio(self, initial_cash: Decimal) -> Portfolio:
        self.initialize()
        with self._connect() as conn:
            account_row = conn.execute("SELECT cash FROM account_state WHERE id = ?", ("paper",)).fetchone()
            position_rows = conn.execute(
                """
                SELECT symbol, quantity, available_quantity, average_cost, last_price, realized_pnl
                FROM positions
                ORDER BY symbol ASC
                """
            ).fetchall()
        portfolio = Portfolio(Decimal(account_row[0]) if account_row else initial_cash)
        for row in position_rows:
            portfolio.positions[row[0]] = Position(
                symbol=row[0],
                quantity=int(row[1]),
                available_quantity=int(row[2]),
                average_cost=Decimal(row[3]),
                last_price=Decimal(row[4]),
                realized_pnl=Decimal(row[5]),
            )
        return portfolio

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO account_state (id, cash)
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET cash=excluded.cash, updated_at=CURRENT_TIMESTAMP
                """,
                ("paper", str(portfolio.cash)),
            )
            conn.execute("DELETE FROM positions")
            conn.executemany(
                """
                INSERT INTO positions (
                    symbol, quantity, available_quantity, average_cost, last_price, realized_pnl
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        position.symbol,
                        position.quantity,
                        position.available_quantity,
                        str(position.average_cost),
                        str(position.last_price),
                        str(position.realized_pnl),
                    )
                    for position in portfolio.positions.values()
                ],
            )

    def record_decision(self, decision: Decision, trade_date: date) -> None:
        self.initialize()
        signal = decision.source_signal
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions (
                    trade_date, symbol, direction, target_weight, approved, reasons,
                    signal_strategy_id, signal_score, signal_confidence, signal_target_weight,
                    signal_evidence, signal_objections, signal_explanation, signal_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_date.isoformat(),
                    decision.symbol,
                    decision.direction.value,
                    str(decision.target_weight),
                    1 if decision.approved else 0,
                    _json_dumps(decision.reasons),
                    signal.strategy_id if signal else None,
                    str(signal.score) if signal else None,
                    str(signal.confidence) if signal else None,
                    str(signal.target_weight) if signal else None,
                    _json_dumps(signal.evidence) if signal else None,
                    _json_dumps(signal.objections) if signal else None,
                    signal.explanation if signal else None,
                    signal.version if signal else None,
                ),
            )

    def load_decisions(self, trade_date: date) -> List[Decision]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, direction, target_weight, approved, reasons,
                       signal_strategy_id, signal_score, signal_confidence, signal_target_weight,
                       signal_evidence, signal_objections, signal_explanation, signal_version
                FROM decisions
                WHERE trade_date = ?
                ORDER BY id ASC
                """,
                (trade_date.isoformat(),),
            ).fetchall()
        return [_decision_from_row(row) for row in rows]

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        self.initialize()
        trade_date = trade_date or fill.timestamp.date()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fills (
                    trade_date, symbol, direction, quantity, price, fee, slippage, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_date.isoformat(),
                    fill.symbol,
                    fill.direction.value,
                    fill.quantity,
                    str(fill.price),
                    str(fill.fee),
                    str(fill.slippage),
                    fill.timestamp.isoformat(),
                ),
            )

    def load_fills(self, trade_date: date) -> List[Fill]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, direction, quantity, price, fee, slippage, timestamp
                FROM fills
                WHERE trade_date = ?
                ORDER BY id ASC
                """,
                (trade_date.isoformat(),),
            ).fetchall()
        return [
            Fill(
                symbol=row[0],
                direction=Direction(row[1]),
                quantity=int(row[2]),
                price=Decimal(row[3]),
                fee=Decimal(row[4]),
                slippage=Decimal(row[5]),
                timestamp=datetime.fromisoformat(row[6]),
            )
            for row in rows
        ]

    def count_fills(self, trade_date: date) -> int:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM fills WHERE trade_date = ?", (trade_date.isoformat(),)).fetchone()
        return int(row[0])

    def load_all_fills(self) -> List[Fill]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, direction, quantity, price, fee, slippage, timestamp
                FROM fills
                ORDER BY timestamp ASC, id ASC
                """
            ).fetchall()
        return [
            Fill(
                symbol=row[0],
                direction=Direction(row[1]),
                quantity=int(row[2]),
                price=Decimal(row[3]),
                fee=Decimal(row[4]),
                slippage=Decimal(row[5]),
                timestamp=datetime.fromisoformat(row[6]),
            )
            for row in rows
        ]

    def record_portfolio_snapshot(self, snapshot_date: date, portfolio: Portfolio) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_date, cash, total_asset, total_market_value
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    cash=excluded.cash,
                    total_asset=excluded.total_asset,
                    total_market_value=excluded.total_market_value,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    snapshot_date.isoformat(),
                    str(portfolio.cash),
                    str(portfolio.total_asset()),
                    str(portfolio.total_market_value()),
                ),
            )

    def load_portfolio_snapshots(self) -> list[tuple[date, Decimal]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_date, total_asset FROM portfolio_snapshots ORDER BY snapshot_date ASC"
            ).fetchall()
        return [(date.fromisoformat(row[0]), Decimal(row[1])) for row in rows]

    def record_backtest_run(self, strategy_id: str, parameters: dict, metrics: dict, status: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs (strategy_id, parameters, metrics, status)
                VALUES (?, ?, ?, ?)
                """,
                (strategy_id, _json_dumps_obj(parameters), _json_dumps_obj(metrics), status),
            )

    def load_backtest_runs(self, limit: int | None = 20) -> list[dict]:
        self.initialize()
        sql = "SELECT id, strategy_id, parameters, metrics, status, created_at FROM backtest_runs ORDER BY id DESC"
        params: list[object] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": int(row[0]),
                "strategy_id": row[1],
                "parameters": json.loads(row[2]),
                "metrics": json.loads(row[3]),
                "status": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def update_backtest_run_status(self, run_ids: list[int], status: str) -> int:
        self.initialize()
        ids = [int(item) for item in run_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE backtest_runs SET status = ? WHERE id IN ({placeholders})",
                [status, *ids],
            )
            return int(cursor.rowcount)

    def settle_t_plus_one(self, settle_date: date | None = None) -> bool:
        self.initialize()
        with self._connect() as conn:
            if settle_date is not None:
                row = conn.execute("SELECT value FROM metadata WHERE key = ?", ("last_settle_date",)).fetchone()
                if row and row[0] == settle_date.isoformat():
                    return False
            conn.execute("UPDATE positions SET available_quantity = quantity, updated_at = CURRENT_TIMESTAMP")
            if settle_date is not None:
                conn.execute(
                    """
                    INSERT INTO metadata (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                    """,
                    ("last_settle_date", settle_date.isoformat()),
                )
        return True

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database)


def _json_dumps(value: list[str]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_dumps_obj(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None) -> list[str]:
    if not value:
        return []
    return [str(item) for item in json.loads(value)]


def _decision_from_row(row: tuple) -> Decision:
    symbol = row[0]
    direction = Direction(row[1])
    signal = None
    if row[5]:
        signal = StrategySignal(
            strategy_id=row[5],
            symbol=symbol,
            direction=direction,
            score=Decimal(row[6] or "0"),
            confidence=Decimal(row[7] or "0"),
            target_weight=Decimal(row[8] or row[2]),
            evidence=_json_loads(row[9]),
            objections=_json_loads(row[10]),
            explanation=row[11] or "",
            version=row[12] or "v1",
        )
    return Decision(
        symbol=symbol,
        direction=direction,
        target_weight=Decimal(row[2]),
        approved=bool(row[3]),
        reasons=_json_loads(row[4]),
        source_signal=signal,
    )
