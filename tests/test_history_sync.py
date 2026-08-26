import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.config import InstrumentConfig, load_config
from stock_ai_agent.history_sync import sync_watchlist_history
from stock_ai_agent.models import Bar
from stock_ai_agent.storage.mock import MockMarketDataStore


class HistoryAdapter:
    def __init__(self):
        self.calls = []

    def get_bars(self, symbol, interval="daily", start="20240101", end="20500101", adjust="qfq"):
        self.calls.append((symbol, adjust, start, end))
        base = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
        return [
            Bar(symbol, base + timedelta(days=index), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1"), Decimal("100"))
            for index in range(40)
        ]


class HistorySyncTests(unittest.TestCase):
    def test_shared_service_persists_qfq_and_raw_tracks(self):
        config = replace(load_config(), universe=[InstrumentConfig("588170.SH", "etf", "测试 ETF")])
        adapter = HistoryAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            store = MockMarketDataStore(Path(tmp) / "history.mock")
            result = sync_watchlist_history(config, store, adapter, as_of=date(2026, 8, 20))

            self.assertEqual(result.synced_count, 1)
            self.assertEqual(len(store.load_bars("588170.SH", price_mode="qfq")), 40)
            self.assertEqual(len(store.load_bars("588170.SH", price_mode="raw")), 40)
            self.assertEqual({call[1] for call in adapter.calls}, {"qfq", ""})

    def test_force_refresh_can_be_restricted_to_incomplete_symbols(self):
        config = replace(load_config(), universe=[InstrumentConfig("588170.SH", "etf", "测试 ETF")])
        adapter = HistoryAdapter()
        store = MockMarketDataStore()
        store.save_bars(adapter.get_bars("588170.SH"), source="mock")

        result = sync_watchlist_history(config, store, adapter, force=False, only_incomplete=True, as_of=date(2026, 8, 20))

        self.assertEqual(result.attempted, 0)
        self.assertEqual(len(adapter.calls), 1)


if __name__ == "__main__":
    unittest.main()
