import unittest
from datetime import date
from datetime import datetime
from unittest.mock import patch

from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.trading_calendar import AShareTradingCalendar


class TradingCalendarTests(unittest.TestCase):
    def test_calendar_reads_database_without_remote_request(self):
        store = MockMarketDataStore()
        store.save_trading_calendar(2026, {date(2026, 8, 21)}, "test")
        calendar = AShareTradingCalendar(store)

        with patch("stock_ai_agent.trading_calendar._exchange_calendars") as calendars:
            self.assertTrue(calendar.is_trading_day(date(2026, 8, 21)))
            self.assertFalse(calendar.is_trading_day(date(2026, 8, 22)))
            calendars.get_calendar.assert_not_called()

    def test_missing_year_is_fetched_and_persisted(self):
        store = MockMarketDataStore()
        calendar = AShareTradingCalendar(store)

        with patch("stock_ai_agent.trading_calendar._exchange_calendars") as calendars:
            calendars.get_calendar.return_value.sessions_in_range.return_value = [datetime(2026, 8, 21)]
            self.assertTrue(calendar.is_trading_day(date(2026, 8, 21)))

        self.assertIn(date(2026, 8, 21), store.load_trading_calendar(2026))


if __name__ == "__main__":
    unittest.main()
