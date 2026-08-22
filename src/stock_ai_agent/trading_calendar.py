from __future__ import annotations

import logging
from datetime import date
from typing import Any


logger = logging.getLogger(__name__)

try:
    import akshare as _akshare
except ImportError:  # pragma: no cover - depends on the selected runtime image
    _akshare = None


class AShareTradingCalendar:
    """Read the official calendar from persistence and refresh missing years."""

    def __init__(self, store: Any | None = None) -> None:
        self.store = store

    def is_trading_day(self, value: date) -> bool:
        stored = self.store.load_trading_calendar(value.year) if self.store and hasattr(self.store, "load_trading_calendar") else None
        if stored is not None:
            if value in stored:
                return bool(stored[value])
            # AKShare normally returns dates through today, not future holidays.
            # Dates beyond the persisted coverage use the conservative weekday fallback.
            return value.weekday() < 5
        fetched = self._load(value.year)
        if fetched is not None:
            return value in fetched
        # A provider outage must not cause a trading process crash. Weekend
        # filtering remains a conservative fallback and is clearly logged.
        return value.weekday() < 5

    def _load(self, year: int) -> set[date] | None:
        try:
            if _akshare is None:
                raise RuntimeError("akshare 未安装")
            frame = _akshare.tool_trade_date_hist_sina()
            values = frame.iloc[:, 0].tolist()
            all_dates = {date.fromisoformat(str(item)[:10]) for item in values}
            dates = {item for item in all_dates if item.year == year}
            if self.store and hasattr(self.store, "save_trading_calendar"):
                covered_until = max(dates) if dates else None
                self.store.save_trading_calendar(year, dates, "akshare", covered_until=covered_until)
            return dates
        except Exception as exc:  # noqa: BLE001 - optional external calendar source
            logger.warning("A 股交易日历加载失败，暂按工作日回退：%s", exc)
            return None
