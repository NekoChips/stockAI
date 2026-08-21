import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.app import run_once_from_store, sync_history
from stock_ai_agent.config import load_config
from stock_ai_agent.models import Bar, Quote
from stock_ai_agent.storage.sqlite import SQLiteMarketDataStore


class MockHistoryAdapter:
    def __init__(self):
        self.calls = []

    def get_bars(self, symbol, interval="daily", start="20240101", end="20500101", adjust="qfq"):
        self.calls.append({"symbol": symbol, "start": start, "end": end})
        base = datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)
        return [
            Bar(
                symbol=symbol,
                timestamp=base + timedelta(days=index),
                open_price=Decimal("1.00") + Decimal(index) * Decimal("0.01"),
                high_price=Decimal("1.03") + Decimal(index) * Decimal("0.01"),
                low_price=Decimal("0.99") + Decimal(index) * Decimal("0.01"),
                close_price=Decimal("1.00") + Decimal(index) * Decimal("0.01"),
                volume=Decimal("10000") + Decimal(index),
                amount=Decimal("10000") + Decimal(index),
            )
            for index in range(40)
        ]


class MockQuoteProvider:
    def get_quote(self, symbol):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        return Quote(
            symbol=symbol,
            name=symbol,
            timestamp=now,
            latest_price=Decimal("1.39"),
            open_price=Decimal("1.30"),
            high_price=Decimal("1.41"),
            low_price=Decimal("1.28"),
            previous_close=Decimal("1.29"),
            volume=Decimal("2000000"),
            amount=Decimal("2780000"),
            change_percent=Decimal("7.75"),
            source="eastmoney_public",
            fetched_at=now,
        )


class AppHistoryTests(unittest.TestCase):
    def test_sync_history_saves_configured_universe_to_store(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "market.sqlite3")
            counts = sync_history(config, store, MockHistoryAdapter())

            self.assertEqual(counts["588170.SH"], 40)
            self.assertEqual(counts["588200.SH"], 40)
            self.assertEqual(len(store.load_bars("588170.SH")), 40)

    def test_run_once_can_load_history_from_store(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "market.sqlite3")
            sync_history(config, store, MockHistoryAdapter())
            result = run_once_from_store(config, store, MockQuoteProvider())

            self.assertGreaterEqual(len(result.decisions), 1)
            self.assertEqual(result.report["status"], "临时运行")
            self.assertIsNone(store.load_daily_report(result.report["report_date"]))

    def test_sync_history_only_requests_dates_missing_from_database(self):
        config = load_config()
        adapter = MockHistoryAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "market.sqlite3")
            existing = MockHistoryAdapter().get_bars("588170.SH")
            store.save_bars(existing, source="mock")

            sync_history(config, store, adapter, as_of=date(2026, 8, 21))

        first_call = next(call for call in adapter.calls if call["symbol"] == "588170.SH")
        self.assertEqual(first_call["start"], "20260810")
        self.assertEqual(first_call["end"], "20260821")


if __name__ == "__main__":
    unittest.main()
