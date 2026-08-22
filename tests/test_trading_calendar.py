import unittest
from datetime import date
from unittest.mock import patch

from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.trading_calendar import AShareTradingCalendar


class TradingCalendarTests(unittest.TestCase):
    def test_calendar_reads_database_without_remote_request(self):
        store = MockMarketDataStore()
        store.save_trading_calendar(2026, {date(2026, 8, 21)}, "test")
        calendar = AShareTradingCalendar(store)

        with patch("stock_ai_agent.trading_calendar._akshare") as akshare:
            self.assertTrue(calendar.is_trading_day(date(2026, 8, 21)))
            self.assertFalse(calendar.is_trading_day(date(2026, 8, 22)))
            akshare.tool_trade_date_hist_sina.assert_not_called()

    def test_missing_year_is_fetched_and_persisted(self):
        store = MockMarketDataStore()
        calendar = AShareTradingCalendar(store)

        class Frame:
            class _Iloc:
                def tolist(self):
                    return ["2026-08-21"]

                def __getitem__(self, _key):
                    return self

            iloc = _Iloc()

        with patch("stock_ai_agent.trading_calendar._akshare") as akshare:
            akshare.tool_trade_date_hist_sina.return_value = Frame()
            self.assertTrue(calendar.is_trading_day(date(2026, 8, 21)))

        self.assertIn(date(2026, 8, 21), store.load_trading_calendar(2026))


if __name__ == "__main__":
    unittest.main()
