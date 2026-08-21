import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Bar, Quote
from stock_ai_agent.storage.mock import MockMarketDataStore


class MockStorageTests(unittest.TestCase):
    def test_development_store_has_no_filesystem_state_and_preserves_runtime_data(self):
        store = MockMarketDataStore()
        bar = Bar("588170.SH", datetime(2026, 8, 20, tzinfo=timezone.utc), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1.05"), Decimal("100"))
        quote = Quote("588170.SH", "科创100ETF基金", datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc), Decimal("1.06"), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1"), Decimal("100"), Decimal("100"), Decimal("6"), "mock", datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc))

        self.assertEqual(store.save_bars([bar]), 1)
        self.assertEqual(store.save_quotes([quote]), 1)
        self.assertEqual(store.load_bars("588170.SH"), [bar])
        self.assertEqual(store.load_latest_quotes()["588170.SH"]["latest_price"], Decimal("1.06"))

    def test_prune_archives_previous_trade_day_quotes_as_minute_bars(self):
        store = MockMarketDataStore()
        quote = Quote("588170.SH", "科创100ETF基金", datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc), Decimal("1.06"), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1"), Decimal("100"), Decimal("100"), Decimal("6"), "mock", datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc))
        store.save_quotes([quote])

        self.assertEqual(store.prune_market_quotes(date(2026, 8, 21)), 1)
        self.assertEqual(len(store.load_bars("588170.SH", interval="minute")), 1)


if __name__ == "__main__":
    unittest.main()
