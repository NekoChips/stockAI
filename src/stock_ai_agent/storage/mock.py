from __future__ import annotations

"""In-memory store for development and deterministic local validation.

It deliberately mirrors the production store surface without importing SQLite or
writing local market/account data.  A process restart resets it by design; use
the release MySQL configuration for persistent paper trading.
"""

from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal

from ..models import Bar, Decision, Direction, Fill, Portfolio, Position, Quote
from .mysql import _quote_ticks_to_minute_bars


class MockMarketDataStore:
    def __init__(self, *_ignored) -> None:
        self._bars: dict[tuple[str, str, str], Bar] = {}
        self._quotes: list[dict] = []
        self._watchlist: dict[str, dict[str, str]] = {}
        self._excluded: set[str] = set()
        self._catalog: dict[str, dict[str, str]] = {}
        self._catalog_synced_date = ""
        self._portfolio: Portfolio | None = None
        self._decisions: list[tuple[date, Decision]] = []
        self._fills: list[tuple[date, Fill]] = []
        self._snapshots: dict[date, Decimal] = {}
        self._backtests: list[dict] = []
        self._reports: dict[str, dict] = {}
        self._last_settle_date: date | None = None

    def initialize(self) -> None:
        return None

    def acquire_monitor_lock(self, name: str = "stockai_monitor") -> bool:
        return True

    def release_monitor_lock(self, name: str = "stockai_monitor") -> None:
        return None

    def save_bars(self, bars: list[Bar], interval: str = "daily", source: str = "unknown") -> int:
        for bar in bars:
            timestamp = datetime.combine(bar.timestamp, time.min) if isinstance(bar.timestamp, date) and not isinstance(bar.timestamp, datetime) else bar.timestamp
            normalized = Bar(bar.symbol, timestamp, bar.open_price, bar.high_price, bar.low_price, bar.close_price, bar.volume, bar.amount)
            self._bars[(normalized.symbol, interval, normalized.timestamp.isoformat())] = normalized
        return len(bars)

    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> list[Bar]:
        rows = sorted((bar for (item_symbol, item_interval, _), bar in self._bars.items() if item_symbol == symbol and item_interval == interval), key=lambda item: item.timestamp)
        return rows[-limit:] if limit is not None else rows

    def save_quotes(self, quotes: list[Quote]) -> int:
        for quote in quotes:
            timestamp = datetime.combine(quote.timestamp, time.min) if isinstance(quote.timestamp, date) and not isinstance(quote.timestamp, datetime) else quote.timestamp
            observed_at = datetime.combine(quote.fetched_at, time.min) if isinstance(quote.fetched_at, date) and not isinstance(quote.fetched_at, datetime) else quote.fetched_at
            row = {
                "trade_date": timestamp.date().isoformat(), "symbol": quote.symbol, "name": quote.name,
                "latest_price": quote.latest_price, "change_percent": quote.change_percent,
                "previous_close": quote.previous_close, "quoted_at": timestamp.isoformat(),
                "observed_at": observed_at.isoformat(), "source": quote.source,
            }
            self._quotes = [item for item in self._quotes if not (item["trade_date"] == row["trade_date"] and item["symbol"] == row["symbol"] and item["observed_at"] == row["observed_at"])]
            self._quotes.append(row)
        return len(quotes)

    def load_latest_quotes(self, symbols: list[str] | None = None) -> dict[str, dict]:
        allowed = set(symbols or [])
        latest: dict[str, dict] = {}
        for row in sorted(self._quotes, key=lambda item: item["observed_at"], reverse=True):
            if allowed and row["symbol"] not in allowed or row["symbol"] in latest:
                continue
            latest[row["symbol"]] = {key: value for key, value in row.items() if key != "trade_date"}
        return latest

    def load_quote_ticks(self, symbol: str, trade_date: date) -> list[dict]:
        return [{key: value for key, value in row.items() if key != "trade_date"} for row in sorted(self._quotes, key=lambda item: item["observed_at"]) if row["symbol"] == symbol and row["trade_date"] == trade_date.isoformat()]

    def prune_market_quotes(self, trade_date: date) -> int:
        old = [row for row in self._quotes if row["trade_date"] != trade_date.isoformat()]
        self.save_bars(_quote_ticks_to_minute_bars([{key: value for key, value in row.items() if key != "trade_date"} for row in old]), interval="minute", source="market_quotes")
        self._quotes = [row for row in self._quotes if row["trade_date"] == trade_date.isoformat()]
        return len(old)

    def load_watchlist_items(self) -> list[dict[str, str]]:
        return list(self._watchlist.values())

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        self._excluded.discard(symbol)
        self._watchlist[symbol] = {"symbol": symbol, "name": name, "asset_type": asset_type}

    def remove_watchlist_item(self, symbol: str) -> None:
        self._watchlist.pop(symbol, None)
        self._excluded.add(symbol)

    def restore_watchlist_item(self, symbol: str) -> None:
        self._excluded.discard(symbol)

    def load_removed_watchlist_symbols(self) -> set[str]:
        return set(self._excluded)

    def replace_instrument_catalog(self, items: list[dict[str, str]], synced_date: str, source: str) -> int:
        self._catalog = {str(item["symbol"]): {"symbol": str(item["symbol"]), "name": str(item["name"]), "asset_type": str(item["asset_type"])} for item in items}
        self._catalog_synced_date = synced_date
        return len(items)

    def search_instrument_catalog(self, query: str, limit: int = 12) -> list[dict[str, str]]:
        text = query.upper()
        rows = [item for item in self._catalog.values() if text in item["symbol"].upper() or text in item["name"].upper()]
        return sorted(rows, key=lambda item: (item["symbol"].upper() != text, item["name"]))[:limit]

    def instrument_catalog_status(self) -> dict[str, str | int]:
        return {"count": len(self._catalog), "synced_date": self._catalog_synced_date}

    def load_portfolio(self, initial_cash: Decimal) -> Portfolio:
        return deepcopy(self._portfolio) if self._portfolio is not None else Portfolio(initial_cash)

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self._portfolio = deepcopy(portfolio)

    def record_decision(self, decision: Decision, trade_date: date) -> None:
        if decision.direction == Direction.WATCH and any(day == trade_date and item.symbol == decision.symbol and item.direction == Direction.WATCH for day, item in self._decisions):
            return
        self._decisions.append((trade_date, deepcopy(decision)))

    def compact_watch_decisions(self) -> int:
        retained: list[tuple[date, Decision]] = []
        seen: set[tuple[date, str]] = set()
        removed = 0
        for day, decision in self._decisions:
            key = (day, decision.symbol)
            if decision.direction == Direction.WATCH and key in seen:
                removed += 1
                continue
            if decision.direction == Direction.WATCH:
                seen.add(key)
            retained.append((day, decision))
        self._decisions = retained
        return removed

    def load_decisions(self, trade_date: date) -> list[Decision]:
        return [deepcopy(item) for day, item in self._decisions if day == trade_date]

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        self._fills.append((trade_date or fill.timestamp.date(), deepcopy(fill)))

    def load_fills(self, trade_date: date) -> list[Fill]:
        return [deepcopy(item) for day, item in self._fills if day == trade_date]

    def count_fills(self, trade_date: date) -> int:
        return len(self.load_fills(trade_date))

    def load_all_fills(self) -> list[Fill]:
        return [deepcopy(item) for _, item in sorted(self._fills, key=lambda value: value[1].timestamp)]

    def record_portfolio_snapshot(self, snapshot_date: date, portfolio: Portfolio) -> None:
        self._snapshots[snapshot_date] = portfolio.total_asset()

    def load_portfolio_snapshots(self) -> list[tuple[date, Decimal]]:
        return sorted(self._snapshots.items())

    def record_backtest_run(self, strategy_id: str, parameters: dict, metrics: dict, status: str) -> None:
        self._backtests.append({"id": len(self._backtests) + 1, "strategy_id": strategy_id, "parameters": deepcopy(parameters), "metrics": deepcopy(metrics), "status": status, "created_at": datetime.now().isoformat()})

    def load_backtest_runs(self, limit: int | None = 20) -> list[dict]:
        rows = list(reversed(self._backtests))
        return deepcopy(rows if limit is None else rows[:limit])

    def update_backtest_run_status(self, run_ids: list[int], status: str) -> int:
        ids = set(run_ids)
        for item in self._backtests:
            if item["id"] in ids:
                item["status"] = status
        return len(ids & {item["id"] for item in self._backtests})

    def save_daily_report(self, report: dict) -> None:
        self._reports[str(report["report_date"])] = deepcopy(report)

    def load_daily_reports(self, limit: int = 60, offset: int = 0) -> list[dict]:
        rows = sorted(self._reports.values(), key=lambda item: item["report_date"], reverse=True)[offset:offset + limit]
        return [
            {
                "report_date": item["report_date"], "status": item.get("status", "已归档"), "summary": item.get("summary", ""),
                "total_asset": item.get("account", {}).get("total_asset", "0"),
                "daily_pnl": item.get("account", {}).get("daily_pnl", "0"),
                "daily_return": item.get("account", {}).get("daily_return", "0"),
            }
            for item in rows
        ]

    def load_daily_report(self, report_date: date | str) -> dict | None:
        value = self._reports.get(report_date.isoformat() if isinstance(report_date, date) else str(report_date))
        return deepcopy(value) if value else None

    def settle_t_plus_one(self, settle_date: date | None = None) -> bool:
        if settle_date and self._last_settle_date == settle_date:
            return False
        if self._portfolio:
            for position in self._portfolio.positions.values():
                position.available_quantity = position.quantity
        self._last_settle_date = settle_date
        return True
