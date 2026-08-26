import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from stock_ai_agent.data.external_market import ExternalMarketSpec, sync_external_market_data
from stock_ai_agent.models import ExternalDailyBar
from stock_ai_agent.storage.mock import MockMarketDataStore


class FakeExternalAdapter:
    def __init__(self, bars=None, failures=None):
        self.bars = bars or {}
        self.failures = set(failures or [])
        self.calls = []

    def get_external_daily_bars(self, source_symbol, start, end, count=None):
        self.calls.append((source_symbol, start, end, count))
        if source_symbol in self.failures:
            raise RuntimeError(f"{source_symbol} unsupported")
        return self.bars.get(source_symbol, [])


def external_bars(symbol, first="100", second="103"):
    return [
        ExternalDailyBar(symbol, datetime(2026, 8, 24, tzinfo=timezone.utc), Decimal(first)),
        ExternalDailyBar(symbol, datetime(2026, 8, 25, tzinfo=timezone.utc), Decimal(second)),
    ]


class ExternalMarketSyncTests(unittest.TestCase):
    def test_alpha_feed_row_uses_canonical_symbol_and_source_symbol(self):
        store = MockMarketDataStore()
        adapter = FakeExternalAdapter({"XLK.US": external_bars("XLK.US")})
        specs = [ExternalMarketSpec("US", "XLK", "信息技术 ETF", ("XLK.US",))]

        result = sync_external_market_data(
            store,
            adapter,
            specs,
            as_of=date(2026, 8, 26),
            now_fn=lambda: datetime(2026, 8, 26, 9, 5, tzinfo=timezone.utc),
        )

        row = store.load_latest_overseas_data()[0]
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(row["symbol"], "XLK")
        self.assertEqual(row["source_symbol"], "XLK.US")
        self.assertEqual(row["change_pct"], "3.00")
        self.assertFalse(row["is_proxy"])
        self.assertEqual(row["data_status"], "ready")

    def test_index_falls_back_to_proxy_without_repeating_successful_source(self):
        store = MockMarketDataStore()
        adapter = FakeExternalAdapter(
            {"QQQ.US": external_bars("QQQ.US", "200", "204")},
            failures={"IXIC.US"},
        )
        specs = [ExternalMarketSpec("US", "^IXIC", "纳斯达克", ("IXIC.US", "QQQ.US"), proxy_symbols=("QQQ.US",))]

        sync_external_market_data(
            store,
            adapter,
            specs,
            as_of=date(2026, 8, 26),
            now_fn=lambda: datetime(2026, 8, 26, 9, 5, tzinfo=timezone.utc),
        )

        row = store.load_latest_overseas_data()[0]
        self.assertEqual([call[0] for call in adapter.calls], ["IXIC.US", "QQQ.US"])
        self.assertEqual(row["symbol"], "^IXIC")
        self.assertTrue(row["is_proxy"])

    def test_one_symbol_failure_does_not_block_other_symbols(self):
        store = MockMarketDataStore()
        adapter = FakeExternalAdapter(
            {"XLK.US": external_bars("XLK.US")},
            failures={"XLV.US"},
        )
        specs = [
            ExternalMarketSpec("US", "XLK", "信息技术 ETF", ("XLK.US",)),
            ExternalMarketSpec("US", "XLV", "医药卫生 ETF", ("XLV.US",)),
        ]

        result = sync_external_market_data(store, adapter, specs, as_of=date(2026, 8, 26))

        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(store.load_latest_overseas_data()[0]["symbol"], "XLK")

    def test_same_day_database_cache_avoids_duplicate_alpha_feed_calls(self):
        store = MockMarketDataStore()
        adapter = FakeExternalAdapter({"XLK.US": external_bars("XLK.US")})
        specs = [ExternalMarketSpec("US", "XLK", "信息技术 ETF", ("XLK.US",))]
        now = lambda: datetime(2026, 8, 26, 9, 5, tzinfo=timezone.utc)

        sync_external_market_data(store, adapter, specs, as_of=date(2026, 8, 26), now_fn=now)
        result = sync_external_market_data(store, adapter, specs, as_of=date(2026, 8, 26), now_fn=now)

        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(result["skipped_count"], 1)

    def test_unsupported_source_is_short_term_cached(self):
        store = MockMarketDataStore()
        adapter = FakeExternalAdapter(failures={"UNKNOWN.US"})
        specs = [ExternalMarketSpec("US", "UNKNOWN", "未知标的", ("UNKNOWN.US",))]

        first = sync_external_market_data(store, adapter, specs, as_of=date(2026, 8, 26))
        second = sync_external_market_data(store, adapter, specs, as_of=date(2026, 8, 26))

        self.assertEqual(first["failure_count"], 1)
        self.assertEqual(second["failure_count"], 1)
        self.assertEqual(len(adapter.calls), 1)


if __name__ == "__main__":
    unittest.main()
