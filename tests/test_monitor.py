import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from stock_ai_agent.config import load_config
from stock_ai_agent.models import Bar, Direction, Quote, StrategySignal
from stock_ai_agent.monitor import RealTimePaperTradingMonitor, is_post_close_report_time, is_trading_time
from stock_ai_agent.storage.sqlite import SQLiteMarketDataStore


class MockQuoteProvider:
    def get_quote(self, symbol):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        return Quote(
            symbol=symbol,
            name=symbol,
            timestamp=now,
            latest_price=Decimal("1.00"),
            open_price=Decimal("0.98"),
            high_price=Decimal("1.01"),
            low_price=Decimal("0.97"),
            previous_close=Decimal("0.98"),
            volume=Decimal("2000000"),
            amount=Decimal("2000000"),
            change_percent=Decimal("2.04"),
            source="mock",
            fetched_at=now,
        )


def bars(symbol):
    base = datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)
    result = []
    for index in range(45):
        close = Decimal("1.00") + Decimal(index) * Decimal("0.002")
        result.append(
            Bar(
                symbol=symbol,
                timestamp=base + timedelta(days=index),
                open_price=close,
                high_price=close + Decimal("0.01"),
                low_price=close - Decimal("0.01"),
                close_price=close,
                volume=Decimal("1000000") + Decimal(index * 1000),
                amount=Decimal("1000000"),
            )
        )
    return result


def buy_signal(symbol="588170.SH"):
    return StrategySignal(
        "aggregate",
        symbol,
        Direction.BUY,
        Decimal("3"),
        Decimal("0.8"),
        Decimal("0.20"),
        ["测试聚合信号：趋势、动量、量能均支持买入"],
        [],
        "测试聚合信号建议买入。",
    )


class MonitorTests(unittest.TestCase):
    def test_trading_time_helpers(self):
        tz = ZoneInfo("Asia/Shanghai")
        self.assertTrue(is_trading_time(datetime(2026, 8, 17, 10, 0, tzinfo=tz)))
        self.assertFalse(is_trading_time(datetime(2026, 8, 17, 12, 0, tzinfo=tz)))
        self.assertTrue(is_post_close_report_time(datetime(2026, 8, 17, 15, 5, tzinfo=tz), "15:05"))

    def test_iteration_executes_and_persists_paper_fill(self):
        config = load_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol), source="mock")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.aggregate_signals", side_effect=lambda signals, weights: buy_signal(next(iter(signals)).symbol)):
                result = monitor.run_iteration(trade_now)
            loaded = store.load_portfolio(config.paper_account.initial_cash)
            fills = store.load_fills(trade_now.date())

        self.assertEqual(result.status, "traded")
        self.assertGreaterEqual(len(result.decisions), 1)
        self.assertGreaterEqual(len(fills), 1)
        self.assertLess(loaded.cash, config.paper_account.initial_cash)

    def test_iteration_skips_outside_market_hours(self):
        config = load_config()
        closed_now = datetime(2026, 8, 17, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            result = monitor.run_iteration(closed_now)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.fills, [])

    def test_iteration_reports_missing_history_instead_of_silently_skipping(self):
        config = load_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            result = monitor.run_iteration(trade_now)

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.decisions, [])
        self.assertTrue(any("588170.SH" in warning for warning in result.warnings))

    def test_iteration_does_not_evaluate_strategy_with_insufficient_history(self):
        config = load_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol)[:10], source="mock")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.aggregate_signals") as aggregate:
                result = monitor.run_iteration(trade_now)

        aggregate.assert_not_called()
        self.assertEqual(result.status, "degraded")
        self.assertTrue(all("至少需要" in warning for warning in result.warnings))

    def test_post_close_report_uses_persisted_daily_records(self):
        config = load_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol), source="mock")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.aggregate_signals", side_effect=lambda signals, weights: buy_signal(next(iter(signals)).symbol)):
                monitor.run_iteration(trade_now)
            report = monitor.generate_post_close_report(trade_now.date())
            stored = store.load_daily_report(trade_now.date())

        self.assertEqual(report["report_date"], "2026-08-17")
        self.assertEqual(stored["report_date"], "2026-08-17")
        self.assertGreaterEqual(len(stored["fills"]), 1)

    def test_monitor_initializes_missing_watchlist_history_before_trading(self):
        config = load_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        class HistoryProvider:
            last_source = "mock_history"

            def get_bars(self, symbol, **kwargs):
                return bars(symbol)

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider(), HistoryProvider())
            with patch("stock_ai_agent.monitor.sync_instrument_catalog", return_value=2), patch(
                "stock_ai_agent.monitor.sync_benchmark_history", return_value={}
            ), patch("stock_ai_agent.monitor.aggregate_signals", side_effect=lambda signals, weights: buy_signal(next(iter(signals)).symbol)):
                monitor.run_forever(max_iterations=1, on_update=lambda result: setattr(self, "startup_result", result), ignore_market_hours=True, now_fn=lambda: trade_now)

            counts = [len(store.load_bars(item.symbol)) for item in config.universe]

        self.assertTrue(all(count >= 35 for count in counts))
        self.assertEqual(self.startup_result.status, "traded")

    def test_monitor_does_not_trade_when_startup_history_is_still_insufficient(self):
        config = load_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        class FailingHistoryProvider:
            def get_bars(self, symbol, **kwargs):
                raise ConnectionError("历史源暂不可用")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider(), FailingHistoryProvider())
            updates = []
            with patch("stock_ai_agent.monitor.sync_instrument_catalog", return_value=2), patch(
                "stock_ai_agent.monitor.sync_benchmark_history", side_effect=ConnectionError("指数源暂不可用")
            ):
                monitor.run_forever(max_iterations=1, on_update=updates.append, ignore_market_hours=True, now_fn=lambda: trade_now)

            fills = store.load_fills(trade_now.date())

        self.assertEqual(updates[0].status, "initializing")
        self.assertEqual(updates[0].decisions, [])
        self.assertEqual(fills, [])
        self.assertTrue(any("历史 K 线未就绪" in warning for warning in updates[0].warnings))

    def test_post_close_report_is_archived_even_when_history_initialization_fails(self):
        config = load_config()
        close_now = datetime(2026, 8, 17, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

        class FailingHistoryProvider:
            def get_bars(self, symbol, **kwargs):
                raise ConnectionError("历史源暂不可用")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider(), FailingHistoryProvider())
            updates = []
            monitor.run_forever(max_iterations=1, on_update=updates.append, now_fn=lambda: close_now)
            report = store.load_daily_report(close_now.date())

        self.assertEqual(updates[0].status, "reported")
        self.assertIsNotNone(report)
        self.assertEqual(report["fills"], [])
        self.assertTrue(any("未进入策略执行阶段" in note for note in report["system_notes"]))


if __name__ == "__main__":
    unittest.main()
