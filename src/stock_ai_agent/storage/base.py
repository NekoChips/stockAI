from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, List, Protocol

from ..models import Bar, Decision, Fill, PaperOrder, Portfolio, Quote


class MarketDataStore(Protocol):
    def initialize(self) -> None:
        ...

    def save_watchlist_price_tracks(
        self,
        raw_bars: List[Bar],
        qfq_bars: List[Bar],
        interval: str = "daily",
        source: str = "unknown",
    ) -> int:
        ...

    def load_watchlist_bars(
        self,
        symbol: str,
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
        price_mode: str = "qfq",
    ) -> List[Bar]:
        ...

    def load_watchlist_bars_batch(
        self,
        symbols: list[str],
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
        price_mode: str = "qfq",
    ) -> dict[str, List[Bar]]:
        ...

    def save_index_price_tracks(self, bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        ...

    def load_index_bars(
        self,
        symbol: str,
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> List[Bar]:
        ...

    def load_index_bars_batch(
        self,
        symbols: list[str],
        interval: str = "daily",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, List[Bar]]:
        ...

    def save_intraday_bars(self, bars: List[Bar], interval: str = "1m", source: str = "unknown") -> int:
        ...

    def load_intraday_bars(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> List[Bar]:
        ...

    def ping(self) -> None:
        ...

    def last_quote_age_seconds(self) -> float | None:
        ...

    # Portfolio, decisions, orders, and fills form the execution contract used
    # by both one-shot simulations and the realtime monitor.
    def load_portfolio(self, initial_cash: Decimal) -> Portfolio:
        ...

    def save_portfolio(self, portfolio: Portfolio) -> None:
        ...

    def record_decision(self, decision: Decision, trade_date: date, portfolio: Portfolio | None = None) -> None:
        ...

    def load_decisions(self, trade_date: date) -> list[Decision]:
        ...

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        ...

    def load_fills(self, trade_date: date) -> list[Fill]:
        ...

    def count_fills(self, trade_date: date, symbol: str | None = None) -> int:
        ...

    def save_order(self, order: PaperOrder, trade_date: date | None = None) -> PaperOrder:
        ...

    def load_open_orders(self, symbol: str | None = None) -> list[PaperOrder]:
        ...

    def count_symbol_operations(self, trade_date: date, symbol: str) -> int:
        ...

    def load_portfolio_snapshots(self) -> list[tuple[date, Decimal]]:
        ...

    def settle_t_plus_one(self, settle_date: date | None = None) -> bool:
        ...

    def acquire_monitor_lock(self, name: str = "stockai_monitor") -> bool:
        ...

    def release_monitor_lock(self, name: str = "stockai_monitor") -> None:
        ...

    def save_quotes(self, quotes: List[Quote]) -> int:
        ...

    def load_latest_quotes(self, symbols: list[str] | None = None) -> dict[str, dict]:
        ...

    def load_quote_ticks(self, symbol: str, trade_date: date) -> list[dict]:
        ...

    def save_overseas_market_data(self, rows: list[dict]) -> int:
        ...

    def load_latest_overseas_data(self, market: str | None = None) -> list[dict]:
        ...

    def save_data_task_status(
        self,
        task_name: str,
        trade_date: date,
        status: str,
        success_count: int,
        failure_count: int,
        error_summary: str,
        started_at: Any,
        finished_at: Any,
    ) -> None:
        ...

    def load_data_task_status(self, task_name: str | None = None) -> list[dict]:
        ...

    def save_sector_mapping(self, symbol: str, sector: str, source: str = "manual") -> None:
        ...

    def load_instrument_sector(self, symbol: str) -> str | None:
        ...

    def load_sector_mappings(self, symbol: str | None = None) -> list[dict]:
        ...

    def save_lhb_records(self, rows: list[dict]) -> int:
        ...

    def load_lhb_records(self, start: date | None = None, end: date | None = None, symbol: str | None = None) -> list[dict]:
        ...

    def prune_market_quotes(self, trade_date: date) -> int:
        ...

    def compact_watch_decisions(self) -> int:
        ...

    def compact_decision_events(self, trade_date: date | None = None) -> int:
        """Remove consecutive duplicate business events for one day or all days."""
        ...

    def purge_decision_events(
        self,
        as_of: date | None = None,
        decision_retention_days: int = 30,
        order_retention_days: int = 730,
    ) -> int:
        """Delete expired business events by phase in bounded maintenance work."""
        ...

    def load_watchlist_items(self) -> list[dict[str, str]]:
        ...

    def ensure_watchlist_defaults(self, instruments: list[Any]) -> None:
        ...

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        ...

    def set_watchlist_trading_enabled(self, symbol: str, enabled: bool) -> None:
        ...

    def remove_watchlist_item(self, symbol: str) -> None:
        ...

    def has_pending_orders(self, symbol: str) -> bool:
        ...

    def load_removed_watchlist_symbols(self) -> set[str]:
        ...

    def replace_instrument_catalog(self, items: list[dict[str, str]], synced_date: str, source: str) -> int:
        ...

    def search_instrument_catalog(self, query: str, limit: int = 12) -> list[dict[str, str]]:
        ...

    def save_daily_report(self, report: dict) -> None:
        ...

    def load_daily_reports(self, limit: int = 60, offset: int = 0) -> list[dict]:
        ...

    def load_daily_report(self, report_date: date | str) -> dict | None:
        ...

    def load_trading_calendar(self, year: int, market: str = "CN") -> dict[date, bool] | None:
        ...

    def save_trading_calendar(self, year: int, trading_days: set[date], source: str, covered_until: date | None = None, market: str = "CN") -> int:
        ...

    def ensure_strategy_defaults(self, config: Any) -> None:
        ...

    def load_active_strategy_profile(self, symbol: str, asset_type: str) -> dict | None:
        ...

    def load_strategy_center(self, config: Any) -> dict:
        ...

    def save_strategy_profile(self, profile: dict, operator: str = "web") -> dict:
        ...

    def confirm_strategy_profile(self, profile_id: str, operator: str = "web") -> dict:
        ...

    def apply_pending_strategy_profiles(self, operator: str = "monitor") -> list[dict[str, Any]]:
        ...

    def mark_backtest_runs_applied(self, run_ids: list[int]) -> int:
        ...

    def load_active_risk_config(self) -> dict | None:
        ...

    def load_risk_config_draft(self) -> dict | None:
        ...

    def save_risk_config_draft(self, payload: dict, operator: str = "web") -> dict:
        ...

    def confirm_risk_config(self, operator: str = "web") -> dict:
        ...
