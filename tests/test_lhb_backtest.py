import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_ai_agent.lhb_backtest import refresh_lhb_seat_profiles
from stock_ai_agent.models import Bar
from stock_ai_agent.storage.mock import MockMarketDataStore


class LhbBacktestTests(unittest.TestCase):
    def test_profile_uses_front_adjusted_t3_prices(self):
        store = MockMarketDataStore()
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        raw = [Bar("600000.SH", start + timedelta(days=index), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("1")) for index in range(4)]
        qfq = [Bar("600000.SH", start + timedelta(days=index), Decimal("10"), Decimal("10"), Decimal("10"), Decimal(str(10 + index)), Decimal("1")) for index in range(4)]
        store.save_price_tracks(raw, qfq)
        store.save_lhb_records([{"trade_date": "2026-08-01", "symbol": "600000.SH", "buy_seat_1": "测试席位"}])

        refresh_lhb_seat_profiles(store)

        self.assertEqual(store.load_seat_profile("测试席位")["t3_win_rate"], "1.0")


if __name__ == "__main__":
    unittest.main()
