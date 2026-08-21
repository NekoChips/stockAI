from __future__ import annotations

import logging
from datetime import date


logger = logging.getLogger(__name__)


class AShareTradingCalendar:
    """Cache the official A-share calendar returned by AKShare for this process."""

    def __init__(self) -> None:
        self._dates: set[date] | None = None
        self._load_failed = False

    def is_trading_day(self, value: date) -> bool:
        if self._dates is None and not self._load_failed:
            self._load()
        if self._dates is not None:
            return value in self._dates
        # A provider outage must not cause a trading process crash. Weekend
        # filtering remains a conservative fallback and is clearly logged.
        return value.weekday() < 5

    def _load(self) -> None:
        try:
            import akshare as ak

            frame = ak.tool_trade_date_hist_sina()
            values = frame.iloc[:, 0].tolist()
            self._dates = {date.fromisoformat(str(item)[:10]) for item in values}
        except Exception as exc:  # noqa: BLE001 - optional external calendar source
            self._load_failed = True
            logger.warning("A 股交易日历加载失败，暂按工作日回退：%s", exc)
