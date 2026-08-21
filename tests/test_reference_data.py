import tempfile
import unittest
from datetime import date
from pathlib import Path

from stock_ai_agent.config import load_config
from stock_ai_agent.models import Bar
from stock_ai_agent.reference_data import sync_benchmark_history, sync_instrument_catalog
from stock_ai_agent.storage.mock import MockMarketDataStore as SQLiteMarketDataStore


class FakeReferenceAdapter:
    def __init__(self):
        self.calls = []

    def list_instruments(self):
        return [
            {"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "stock"},
            {"symbol": "510300.SH", "name": "沪深300ETF", "asset_type": "etf"},
        ]

    def get_index_bars(self, symbol, _akshare_symbol, start, end):
        self.calls.append({"symbol": symbol, "start": start, "end": end})
        from datetime import datetime
        from decimal import Decimal

        return [
            Bar(symbol, datetime(2026, 1, 5), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("1")),
            Bar(symbol, datetime(2026, 1, 6), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("101"), Decimal("1")),
        ]


class ReferenceDataTests(unittest.TestCase):
    def test_syncs_daily_catalog_and_benchmarks_to_store(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "reference.sqlite3")
            adapter = FakeReferenceAdapter()
            catalog_count = sync_instrument_catalog(config, store, adapter, "2026-08-19")
            benchmark_counts = sync_benchmark_history(config, store, adapter)

            catalog = store.search_instrument_catalog("茅台")
            benchmark_bars = store.load_bars("000001.SH")

        self.assertEqual(catalog_count, 2)
        self.assertEqual(catalog[0]["symbol"], "600519.SH")
        self.assertEqual(len(benchmark_counts), len(config.benchmarks))
        self.assertEqual(len(benchmark_bars), 2)

    def test_benchmark_sync_requests_only_dates_after_latest_stored_bar(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "reference.sqlite3")
            adapter = FakeReferenceAdapter()
            sync_benchmark_history(config, store, adapter, as_of=date(2026, 1, 6))
            adapter.calls.clear()

            sync_benchmark_history(config, store, adapter, as_of=date(2026, 1, 6))

        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
