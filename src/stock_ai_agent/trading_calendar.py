from __future__ import annotations

import logging
from datetime import date
from typing import Any


logger = logging.getLogger(__name__)

try:
    import exchange_calendars as _exchange_calendars
except ImportError:  # pragma: no cover - development mock environment
    _exchange_calendars = None


CALENDAR_CODES = {"CN": "XSHG", "US": "XNYS", "KR": "XKRX"}


class UnifiedTradingCalendar:
    """Database-backed CN/US/KR calendar using exchange_calendars as source."""

    def __init__(self, store: Any | None = None) -> None:
        self.store = store

    def is_trading_day(self, value: date, market: str = "CN") -> bool:
        market = market.upper()
        stored = self.store.load_trading_calendar(value.year, market=market) if self.store and hasattr(self.store, "load_trading_calendar") else None
        if stored is not None:
            return bool(stored.get(value, False))
        fetched = self._load(value.year, market)
        if fetched is not None:
            return value in fetched
        return value.weekday() < 5

    def _load(self, year: int, market: str) -> set[date] | None:
        try:
            if _exchange_calendars is None:
                raise RuntimeError("exchange_calendars 未安装")
            calendar = _exchange_calendars.get_calendar(CALENDAR_CODES[market])
            sessions = calendar.sessions_in_range(f"{year}-01-01", f"{year}-12-31")
            dates = {session.date() for session in sessions}
            if self.store and hasattr(self.store, "save_trading_calendar"):
                self.store.save_trading_calendar(year, dates, "exchange_calendars", market=market)
            return dates
        except Exception as exc:  # noqa: BLE001 - optional external calendar source
            logger.warning("%s 交易日历加载失败，暂按工作日回退：%s", market, exc)
            return None


class AShareTradingCalendar:
    """Backward-compatible A-share facade over the unified calendar."""

    def __init__(self, store: Any | None = None) -> None:
        self._calendar = UnifiedTradingCalendar(store)

    def is_trading_day(self, value: date) -> bool:
        return self._calendar.is_trading_day(value, "CN")
