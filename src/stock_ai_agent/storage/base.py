from __future__ import annotations

from datetime import date
from typing import List, Protocol

from ..models import Bar, Quote


class MarketDataStore(Protocol):
    def initialize(self) -> None:
        ...

    def save_bars(self, bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        ...

    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> List[Bar]:
        ...

    def save_quotes(self, quotes: List[Quote]) -> int:
        ...

    def load_latest_quotes(self, symbols: list[str] | None = None) -> dict[str, dict]:
        ...

    def load_quote_ticks(self, symbol: str, trade_date: date) -> list[dict]:
        ...

    def prune_market_quotes(self, trade_date: date) -> int:
        ...

    def compact_watch_decisions(self) -> int:
        ...

    def load_watchlist_items(self) -> list[dict[str, str]]:
        ...

    def add_watchlist_item(self, symbol: str, name: str, asset_type: str) -> None:
        ...

    def remove_watchlist_item(self, symbol: str) -> None:
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
