from __future__ import annotations

"""In-memory store for development and deterministic local validation.

It deliberately mirrors the production store surface without importing SQLite or
writing local market/account data.  A process restart resets it by design; use
the release MySQL configuration for persistent paper trading.
"""

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from ..journal import (
    decision_position_context,
    decision_event_state,
    deduplicate_decision_timeline,
    make_business_event_key,
    normalize_daily_report,
    order_event_state,
)
from ..models import Bar, Decision, Direction, Fill, OrderStatus, PaperOrder, Portfolio, Position, Quote
from ..strategy_catalog import strategy_definitions
from ..strategy_runtime import profile_from_config
from .mysql import _quote_ticks_to_minute_bars


class MockMarketDataStore:
    def __init__(self, *_ignored) -> None:
        self._bars: dict[tuple[str, str, str], Bar] = {}
        self._price_tracks: dict[tuple[str, str, str], dict[str, Bar | Decimal]] = {}
        self._quotes: list[dict] = []
        self._quote_events: list[dict] = []
        self._watchlist: dict[str, dict[str, str]] = {}
        self._excluded: set[str] = set()
        self._catalog: dict[str, dict[str, str]] = {}
        self._catalog_synced_date = ""
        self._portfolio: Portfolio | None = None
        self._decisions: list[tuple[date, Decision]] = []
        self._fills: list[tuple[date, Fill]] = []
        self._orders: dict[str, PaperOrder] = {}
        self._decision_events: list[dict] = []
        self._futures_positions: list[dict] = []
        self._overseas_market_data: list[dict] = []
        self._data_task_status: dict[str, dict] = {}
        self._sector_mapping: dict[str, dict] = {}
        self._lhb_records: list[dict] = []
        self._seat_profiles: dict[str, dict] = {}
        self._quant_seats: dict[str, dict] = {}
        self._snapshots: dict[date, Decimal] = {}
        self._backtests: list[dict] = []
        self._reports: dict[str, dict] = {}
        self._last_settle_date: date | None = None
        self._trading_calendar: dict[tuple[str, int], dict[date, bool]] = {}
        self._strategy_definitions: list[dict] = []
        self._strategy_profiles: dict[str, dict] = {}
        self._strategy_drafts: dict[str, dict] = {}
        self._strategy_changes: list[dict] = []
        self._risk_active: dict | None = None
        self._risk_draft: dict | None = None

    def initialize(self) -> None:
        return None

    def ping(self) -> None:
        return None

    def last_quote_age_seconds(self) -> float | None:
        if not self._quotes:
            return None
        latest = max(datetime.fromisoformat(str(item["observed_at"])) for item in self._quotes)
        now = datetime.now(latest.tzinfo) if latest.tzinfo else datetime.now()
        return max(0.0, (now - latest).total_seconds())

    def acquire_monitor_lock(self, name: str = "stockai_monitor") -> bool:
        return True

    def release_monitor_lock(self, name: str = "stockai_monitor") -> None:
        return None

    def save_bars(self, bars: list[Bar], interval: str = "daily", source: str = "unknown") -> int:
        for bar in bars:
            timestamp = datetime.combine(bar.timestamp, time.min) if isinstance(bar.timestamp, date) and not isinstance(bar.timestamp, datetime) else bar.timestamp
            normalized = Bar(bar.symbol, timestamp, bar.open_price, bar.high_price, bar.low_price, bar.close_price, bar.volume, bar.amount, bar.price_mode, bar.adjustment_factor)
            self._bars[(normalized.symbol, interval, normalized.timestamp.isoformat())] = normalized
        return len(bars)

    def save_price_tracks(self, raw_bars: list[Bar], qfq_bars: list[Bar], interval: str = "daily", source: str = "unknown") -> int:
        raw_by_time = {item.timestamp: item for item in raw_bars}
        qfq_by_time = {item.timestamp: item for item in qfq_bars}
        for timestamp in sorted(set(raw_by_time) | set(qfq_by_time)):
            raw, qfq = raw_by_time.get(timestamp), qfq_by_time.get(timestamp)
            reference = qfq or raw
            if reference is None:
                continue
            factor = (qfq.close_price / raw.close_price).quantize(Decimal("0.00000001")) if raw and qfq and raw.close_price else Decimal("1")
            self._price_tracks[(reference.symbol, interval, timestamp.isoformat())] = {"raw": raw or reference, "qfq": qfq or reference, "factor": factor}
        self.save_bars(qfq_bars or raw_bars, interval, source)
        return len(qfq_bars or raw_bars)

    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None, start: date | None = None, end: date | None = None, price_mode: str = "qfq") -> list[Bar]:
        tracked = [track.get(price_mode) for (item_symbol, item_interval, _), track in self._price_tracks.items() if item_symbol == symbol and item_interval == interval]
        rows = sorted((bar for bar in tracked if isinstance(bar, Bar)), key=lambda item: item.timestamp) if tracked else sorted((bar for (item_symbol, item_interval, _), bar in self._bars.items() if item_symbol == symbol and item_interval == interval), key=lambda item: item.timestamp)
        if start is not None:
            rows = [bar for bar in rows if bar.timestamp.date() >= start]
        if end is not None:
            rows = [bar for bar in rows if bar.timestamp.date() <= end]
        return rows[-limit:] if limit is not None else rows

    def load_bars_batch(self, symbols: list[str], interval: str = "daily", limit: int | None = None, start: date | None = None, end: date | None = None, price_mode: str = "qfq") -> dict[str, list[Bar]]:
        return {symbol: self.load_bars(symbol, interval=interval, limit=limit, start=start, end=end, price_mode=price_mode) for symbol in symbols}

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
            self._quote_events = [item for item in self._quote_events if not (item["trade_date"] == row["trade_date"] and item["symbol"] == row["symbol"] and item["observed_at"] == row["observed_at"])]
            self._quote_events.append(dict(row))
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
        cutoff = trade_date - timedelta(days=7)
        self._quote_events = [row for row in self._quote_events if date.fromisoformat(row["trade_date"]) >= cutoff]
        return len(old)

    def load_watchlist_items(self) -> list[dict[str, str]]:
        return list(self._watchlist.values())

    def ensure_watchlist_defaults(self, instruments) -> None:
        for item in instruments:
            if item.symbol in self._excluded or item.symbol in self._watchlist:
                continue
            self._watchlist[item.symbol] = {
                "symbol": item.symbol,
                "name": item.name,
                "asset_type": item.asset_type,
                "lifecycle_status": item.lifecycle_status,
                "trading_enabled": int(bool(item.trading_enabled)),
            }

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        self._excluded.discard(symbol)
        self._watchlist[symbol] = {"symbol": symbol, "name": name, "asset_type": asset_type, "lifecycle_status": "observing", "trading_enabled": 0}

    def remove_watchlist_item(self, symbol: str) -> None:
        self._watchlist.pop(symbol, None)
        self._excluded.add(symbol)

    def set_watchlist_trading_enabled(self, symbol: str, enabled: bool) -> None:
        if symbol not in self._watchlist:
            raise ValueError(f"标的 {symbol} 不在手动观察池中。")
        self._watchlist[symbol]["trading_enabled"] = int(bool(enabled))
        self._watchlist[symbol]["lifecycle_status"] = "trading_enabled" if enabled else "observing"

    def update_watchlist_lifecycle(self, symbol: str, status: str, dormant_since: date | None = None) -> None:
        if symbol in self._watchlist:
            self._watchlist[symbol]["lifecycle_status"] = status
            self._watchlist[symbol]["dormant_since"] = dormant_since.isoformat() if dormant_since else ""

    def load_recent_decisions(self, symbol: str, limit: int = 20) -> list[Decision]:
        return [deepcopy(item) for _, item in reversed(self._decisions) if item.symbol == symbol][:limit]

    def has_pending_orders(self, symbol: str) -> bool:
        return bool(self.load_open_orders(symbol))

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

    def record_decision(self, decision: Decision, trade_date: date, portfolio: Portfolio | None = None) -> None:
        updated = False
        for index, (day, previous) in enumerate(self._decisions):
            if day != trade_date or previous.symbol != decision.symbol:
                continue
            reasons = list(dict.fromkeys([*previous.reasons, *decision.reasons]))[-20:]
            self._decisions[index] = (
                day,
                Decision(
                    decision.symbol,
                    decision.direction,
                    decision.target_weight,
                    decision.approved,
                    reasons,
                    decision.source_signal or previous.source_signal,
                ),
            )
            updated = True
            break
        if not updated:
            self._decisions.append((trade_date, deepcopy(decision)))
        previous_event = next(
            (
                item
                for item in reversed(self._decision_events)
                if item["trade_date"] == trade_date.isoformat()
                and item["phase"] == "decision"
                and item["symbol"] == decision.symbol
            ),
            None,
        )
        previous_state = (
            str(previous_event.get("direction")),
            str(previous_event.get("target_weight")),
            bool(previous_event.get("approved")),
            str(previous_event.get("strategy_id") or ""),
        ) if previous_event else None
        if previous_state == decision_event_state(decision):
            return
        position_quantity, position_weight, position_state = decision_position_context(portfolio, decision.symbol)
        self._decision_events.append(
            {
                "trade_date": trade_date.isoformat(),
                "symbol": decision.symbol,
                "event_at": datetime.now().isoformat(),
                "phase": "decision",
                "direction": decision.direction.value,
                "approved": decision.approved,
                "target_weight": str(decision.target_weight),
                "position_quantity": position_quantity,
                "position_weight": str(position_weight),
                "position_state": position_state,
                "reasons": list(decision.reasons),
                "strategy_id": decision.source_signal.strategy_id if decision.source_signal else "",
                "event_key": make_business_event_key(
                    "decision", trade_date, decision.symbol, decision_event_state(decision), len(self._decision_events)
                ),
            }
        )

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

    def save_order(self, order: PaperOrder, trade_date: date | None = None) -> PaperOrder:
        self._orders[order.order_id] = deepcopy(order)
        happened = order.updated_at or order.created_at
        day = trade_date or happened.date()
        previous_event = next(
            (item for item in reversed(self._decision_events) if item["phase"] == "order" and item.get("order_id") == order.order_id),
            None,
        )
        previous_state = (
            str(previous_event.get("direction")),
            str(previous_event.get("status")),
            int(previous_event.get("filled_quantity") or 0),
        ) if previous_event else None
        if previous_state != order_event_state(order):
            self._decision_events.append(
                {
                    "trade_date": day.isoformat(),
                    "symbol": order.symbol,
                    "event_at": happened.isoformat(),
                    "phase": "order",
                    "direction": order.direction.value,
                    "status": order.status.value,
                    "filled_quantity": order.filled_quantity,
                    "order_id": order.order_id,
                    "reasons": [order.reason or order.rejected_reason] if (order.reason or order.rejected_reason) else [],
                    "event_key": make_business_event_key(
                        "order", day, order.symbol, order_event_state(order), len(self._decision_events)
                    ),
                }
            )
        return deepcopy(order)

    def load_open_orders(self, symbol: str | None = None) -> list[PaperOrder]:
        active = {OrderStatus.CREATED, OrderStatus.APPROVED, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
        return [deepcopy(item) for item in self._orders.values() if item.status in active and (symbol is None or item.symbol == symbol)]

    def load_orders(self, limit: int = 100) -> list[PaperOrder]:
        return [deepcopy(item) for item in sorted(self._orders.values(), key=lambda item: item.updated_at or item.created_at, reverse=True)[:limit]]

    def count_symbol_operations(self, trade_date: date, symbol: str) -> int:
        terminal = {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED}
        return sum(1 for item in self._orders.values() if item.symbol == symbol and item.status in terminal and (item.updated_at or item.created_at).date() == trade_date)

    def load_decision_events(self, trade_date: date, symbol: str | None = None) -> list[dict]:
        return [deepcopy(item) for item in self._decision_events if item["trade_date"] == trade_date.isoformat() and (symbol is None or item["symbol"] == symbol)]

    def compact_decision_events(self, trade_date: date | None = None) -> int:
        target = trade_date.isoformat() if trade_date else None
        selected = [item for item in self._decision_events if target is None or item["trade_date"] == target]
        retained = deduplicate_decision_timeline(selected)
        retained_keys = {str(item.get("event_key") or "") for item in retained}
        before = len(selected)
        if target is None:
            self._decision_events = retained
        else:
            self._decision_events = [
                item for item in self._decision_events
                if item["trade_date"] != target or str(item.get("event_key") or "") in retained_keys
            ]
        return before - len(retained)

    def purge_decision_events(
        self,
        as_of: date | None = None,
        decision_retention_days: int = 30,
        order_retention_days: int = 730,
    ) -> int:
        reference = as_of or date.today()
        cutoffs = {
            "decision": reference - timedelta(days=decision_retention_days),
            "order": reference - timedelta(days=order_retention_days),
        }
        before = len(self._decision_events)
        self._decision_events = [
            item for item in self._decision_events
            if date.fromisoformat(str(item["trade_date"])) >= cutoffs.get(str(item.get("phase")), reference)
        ]
        return before - len(self._decision_events)

    def save_futures_positions(self, rows: list[dict]) -> int:
        for row in rows:
            self._futures_positions = [item for item in self._futures_positions if not (item.get("trade_date") == row.get("trade_date") and item.get("contract") == row.get("contract"))]
            self._futures_positions.append(deepcopy(row))
        return len(rows)

    def load_latest_futures_position(self, contract: str = "IC") -> dict | None:
        rows = [item for item in self._futures_positions if item.get("contract") == contract]
        return deepcopy(max(rows, key=lambda item: str(item.get("trade_date")))) if rows else None

    def save_overseas_market_data(self, rows: list[dict]) -> int:
        for row in rows:
            self._overseas_market_data = [item for item in self._overseas_market_data if not (item.get("market") == row.get("market") and item.get("symbol") == row.get("symbol") and item.get("trade_date") == row.get("trade_date"))]
            self._overseas_market_data.append(deepcopy(row))
        return len(rows)

    def save_data_task_status(self, task_name, trade_date, status, success_count, failure_count, error_summary, started_at, finished_at) -> None:
        self._data_task_status[task_name] = {
            "task_name": task_name,
            "trade_date": str(trade_date),
            "status": status,
            "success_count": int(success_count),
            "failure_count": int(failure_count),
            "error_summary": error_summary,
            "started_at": started_at.isoformat() if hasattr(started_at, "isoformat") else str(started_at),
            "finished_at": finished_at.isoformat() if hasattr(finished_at, "isoformat") else str(finished_at),
        }

    def load_data_task_status(self, task_name: str | None = None) -> list[dict]:
        rows = list(self._data_task_status.values())
        if task_name:
            rows = [row for row in rows if row["task_name"] == task_name]
        return deepcopy(rows)

    def load_latest_overseas_data(self, market: str | None = None) -> list[dict]:
        rows = [item for item in self._overseas_market_data if market is None or item.get("market") == market]
        latest: dict[str, dict] = {}
        for row in sorted(rows, key=lambda item: str(item.get("trade_date")), reverse=True):
            latest.setdefault(str(row.get("symbol")), deepcopy(row))
        return list(latest.values())

    def save_sector_mapping(self, symbol: str, sector: str, source: str = "manual") -> None:
        self._sector_mapping[symbol] = {"symbol": symbol, "sector": sector, "source": source}

    def load_instrument_sector(self, symbol: str) -> str | None:
        return self._sector_mapping.get(symbol, {}).get("sector")

    def load_sector_mappings(self, symbol: str | None = None) -> list[dict]:
        rows = list(self._sector_mapping.values())
        if symbol:
            rows = [row for row in rows if row.get("symbol") == symbol]
        return deepcopy(rows)

    def save_lhb_records(self, rows: list[dict]) -> int:
        for row in rows:
            self._lhb_records = [item for item in self._lhb_records if not (item.get("trade_date") == row.get("trade_date") and item.get("symbol") == row.get("symbol"))]
            self._lhb_records.append(deepcopy(row))
        return len(rows)

    def load_lhb_records(self, start: date | None = None, end: date | None = None, symbol: str | None = None) -> list[dict]:
        return [deepcopy(item) for item in self._lhb_records if (symbol is None or item.get("symbol") == symbol) and (start is None or str(item.get("trade_date")) >= start.isoformat()) and (end is None or str(item.get("trade_date")) <= end.isoformat())]

    def save_seat_profile(self, row: dict) -> None:
        self._seat_profiles[str(row["seat_name"])] = deepcopy(row)

    def load_seat_profile(self, seat_name: str) -> dict | None:
        return deepcopy(self._seat_profiles.get(seat_name))

    def save_quant_seats(self, rows: list[dict]) -> int:
        self._quant_seats.update({str(item["seat_name"]): deepcopy(item) for item in rows})
        return len(rows)

    def load_quant_seats(self) -> list[dict]:
        return [deepcopy(item) for item in self._quant_seats.values() if item.get("is_active", True)]

    def load_fills(self, trade_date: date) -> list[Fill]:
        return [deepcopy(item) for day, item in self._fills if day == trade_date]

    def count_fills(self, trade_date: date, symbol: str | None = None) -> int:
        fills = self.load_fills(trade_date)
        return len([item for item in fills if symbol is None or item.symbol == symbol])

    def load_all_fills(self) -> list[Fill]:
        return [deepcopy(item) for _, item in sorted(self._fills, key=lambda value: value[1].timestamp)]

    def record_portfolio_snapshot(self, snapshot_date: date, portfolio: Portfolio) -> None:
        self._snapshots[snapshot_date] = portfolio.total_asset()

    def load_portfolio_snapshots(self) -> list[tuple[date, Decimal]]:
        return sorted(self._snapshots.items())

    def record_backtest_run(self, strategy_id: str, parameters: dict, metrics: dict, status: str, strategy_profile_id: str = "default") -> None:
        self._backtests.append({"id": len(self._backtests) + 1, "strategy_id": strategy_id, "strategy_profile_id": strategy_profile_id, "parameters": deepcopy(parameters), "metrics": deepcopy(metrics), "status": status, "created_at": datetime.now().isoformat()})

    def load_backtest_runs(self, limit: int | None = 20) -> list[dict]:
        rows = list(reversed(self._backtests))
        return deepcopy(rows if limit is None else rows[:limit])

    def update_backtest_run_status(self, run_ids: list[int], status: str) -> int:
        ids = set(run_ids)
        confirmed_at = datetime.now().isoformat()
        for item in self._backtests:
            if item["id"] in ids:
                item["status"] = status
                item["confirmed_at"] = confirmed_at
        return len(ids & {item["id"] for item in self._backtests})

    def mark_backtest_runs_applied(self, run_ids: list[int]) -> int:
        ids = set(run_ids)
        count = 0
        for item in self._backtests:
            if item["id"] in ids:
                item["status"] = "已应用"
                item["applied_at"] = datetime.now().isoformat()
                count += 1
        return count

    def save_daily_report(self, report: dict) -> None:
        self._reports[str(report["report_date"])] = deepcopy(normalize_daily_report(report))

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
        return deepcopy(normalize_daily_report(value)) if value else None

    def load_trading_calendar(self, year: int, market: str = "CN") -> dict[date, bool] | None:
        rows = self._trading_calendar.get((market.upper(), int(year)))
        return deepcopy(rows) if rows is not None else None

    def save_trading_calendar(self, year: int, trading_days: set[date], source: str, covered_until: date | None = None, market: str = "CN") -> int:
        from datetime import timedelta

        start = date(int(year), 1, 1)
        end = covered_until or date(int(year), 12, 31)
        total = (end - start).days + 1
        self._trading_calendar[(market.upper(), int(year))] = {
            start + timedelta(days=index): start + timedelta(days=index) in trading_days
            for index in range(total)
        }
        return total

    def ensure_strategy_defaults(self, config) -> None:
        if not self._strategy_definitions:
            self._strategy_definitions = strategy_definitions()
        if "default" not in self._strategy_profiles:
            self._strategy_profiles["default"] = profile_from_config(config, asset_type="etf")
        elif int(self._strategy_profiles["default"].get("config_schema_version", 1)) < 2 and "default" not in self._strategy_drafts:
            self._strategy_drafts["default"] = profile_from_config(config, asset_type="etf") | {
                "status": "draft",
                "pending_confirmation": True,
                "migration_note": "旧默认策略已按新基线生成草稿，等待人工确认。",
            }

    def load_active_strategy_profile(self, symbol: str, asset_type: str) -> dict | None:
        for profile in self._strategy_profiles.values():
            if profile.get("status") == "active" and profile.get("scope_type") == "symbol" and profile.get("scope_value") == symbol:
                return deepcopy(profile)
        for profile in self._strategy_profiles.values():
            if profile.get("status") == "active" and profile.get("scope_type") == "asset_type" and profile.get("scope_value") == asset_type:
                return deepcopy(profile)
        profile = self._strategy_profiles.get("default")
        if profile and profile.get("status") == "active":
            return deepcopy(profile)
        return None

    def load_strategy_center(self, config) -> dict:
        self.ensure_strategy_defaults(config)
        profiles = []
        for profile_id, profile in self._strategy_profiles.items():
            draft = self._strategy_drafts.get(profile_id)
            if draft:
                item = deepcopy(draft)
                item.update({
                    "active_revision": profile.get("revision"),
                    "pending_confirmation": True,
                    "draft_diff": _profile_diff(profile, draft),
                })
                profiles.append(item)
            else:
                profiles.append(deepcopy(profile))
        for profile_id, profile in self._strategy_drafts.items():
            if profile_id not in self._strategy_profiles:
                profiles.append(deepcopy(profile))
        return {
            "definitions": deepcopy(self._strategy_definitions),
            "profiles": profiles,
            "changes": deepcopy(self._strategy_changes[-50:]),
        }

    def save_strategy_profile(self, profile: dict, operator: str = "web") -> dict:
        profile_id = str(profile.get("profile_id") or profile.get("scope_value") or "default")
        previous = deepcopy(self._strategy_profiles.get(profile_id))
        saved = deepcopy(profile)
        saved.update({"profile_id": profile_id, "status": "draft", "revision": int((previous or {}).get("revision", 0)) + 1})
        if previous and previous.get("status") == "active":
            self._strategy_drafts[profile_id] = saved
        else:
            self._strategy_profiles[profile_id] = saved
        self._strategy_changes.append({"profile_id": profile_id, "action": "save", "operator": operator, "before": previous, "after": deepcopy(saved), "created_at": datetime.now().isoformat()})
        return deepcopy(saved)

    def confirm_strategy_profile(self, profile_id: str, operator: str = "web") -> dict:
        key = str(profile_id)
        profile = self._strategy_drafts.pop(key, None) or self._strategy_profiles.get(key)
        if not profile:
            raise ValueError("策略组合不存在。")
        previous = deepcopy(profile)
        profile["status"] = "active"
        profile["confirmed_by"] = operator
        profile["confirmed_at"] = datetime.now().isoformat()
        profile["effective_monitor_round"] = "next"
        self._strategy_profiles[key] = profile
        self._strategy_changes.append({"profile_id": str(profile_id), "action": "confirm", "operator": operator, "before": previous, "after": deepcopy(profile), "created_at": datetime.now().isoformat()})
        return deepcopy(profile)

    def apply_pending_strategy_profiles(self, operator: str = "monitor") -> list[dict]:
        applied = []
        for profile_id, draft in list(self._strategy_drafts.items()):
            if not draft.get("pending_activation"):
                continue
            previous = deepcopy(self._strategy_profiles.get(profile_id))
            profile = self._strategy_drafts.pop(profile_id)
            profile.update({
                "status": "active",
                "pending_activation": False,
                "confirmed_by": operator,
                "confirmed_at": datetime.now().isoformat(),
                "effective_monitor_round": "current",
            })
            self._strategy_profiles[profile_id] = profile
            self._strategy_changes.append({
                "profile_id": profile_id,
                "action": "apply_backtest",
                "operator": operator,
                "before": previous,
                "after": deepcopy(profile),
                "created_at": datetime.now().isoformat(),
            })
            applied.append({"profile_id": profile_id, "source_backtest_id": profile.get("source_backtest_id")})
        return applied

    def discard_strategy_draft(self, profile_id: str, operator: str = "web") -> None:
        key = str(profile_id)
        draft = self._strategy_drafts.pop(key, None)
        if draft is None and self._strategy_profiles.get(key, {}).get("status") == "draft":
            draft = self._strategy_profiles.pop(key)
        if draft is None:
            raise ValueError("没有可撤销的策略草稿。")
        self._strategy_changes.append({"profile_id": key, "action": "discard_draft", "operator": operator, "before": deepcopy(draft), "after": None, "created_at": datetime.now().isoformat()})

    def load_active_risk_config(self) -> dict | None:
        return deepcopy(self._risk_active)

    def load_risk_config_draft(self) -> dict | None:
        return deepcopy(self._risk_draft)

    def save_risk_config_draft(self, payload: dict, operator: str = "web") -> dict:
        self._risk_draft = {**deepcopy(payload), "status": "draft", "pending_confirmation": True, "operator": operator}
        return deepcopy(self._risk_draft)

    def confirm_risk_config(self, operator: str = "web") -> dict:
        if not self._risk_draft:
            raise ValueError("没有待确认的风险配置草稿。")
        self._risk_active = {**deepcopy(self._risk_draft), "status": "active", "pending_confirmation": False, "operator": operator}
        self._risk_draft = None
        return deepcopy(self._risk_active)

    def settle_t_plus_one(self, settle_date: date | None = None) -> bool:
        if settle_date and self._last_settle_date == settle_date:
            return False
        if self._portfolio:
            for position in self._portfolio.positions.values():
                position.available_quantity = position.quantity
        self._last_settle_date = settle_date
        return True


def _profile_diff(active: dict, draft: dict) -> list[dict]:
    """Small, presentation-ready diff for the confirmation UI; no rollback payload."""
    ignored = {"status", "revision", "updated_at", "confirmed_at", "confirmed_by", "effective_monitor_round", "pending_activation", "pending_confirmation", "source_backtest_id", "source_backtest_parameters"}
    changes = []
    for key in sorted((set(active) | set(draft)) - ignored):
        before, after = active.get(key), draft.get(key)
        if before != after:
            changes.append({"field": key, "before": before, "after": after})
    return changes
