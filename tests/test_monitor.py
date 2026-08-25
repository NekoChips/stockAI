import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from stock_ai_agent.config import InstrumentConfig, load_config
from stock_ai_agent.models import Bar, Decision, Direction, FeatureSet, Quote, StrategySignal
from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.monitor import RealTimePaperTradingMonitor, is_post_close_report_time, is_trading_time
from stock_ai_agent.storage.mock import MockMarketDataStore as SQLiteMarketDataStore


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


def configured_config():
    return replace(
        load_config(),
        universe=[
            InstrumentConfig("588170.SH", "etf", "测试 ETF"),
            InstrumentConfig("588200.SH", "etf", "测试 ETF 2"),
        ],
    )


class MonitorTests(unittest.TestCase):
    def test_trading_time_helpers(self):
        tz = ZoneInfo("Asia/Shanghai")
        self.assertTrue(is_trading_time(datetime(2026, 8, 17, 10, 0, tzinfo=tz)))
        self.assertFalse(is_trading_time(datetime(2026, 8, 17, 12, 0, tzinfo=tz)))
        self.assertTrue(is_post_close_report_time(datetime(2026, 8, 17, 15, 5, tzinfo=tz), "15:05"))

    def test_market_holidays_are_not_treated_as_trading_days(self):
        tz = ZoneInfo("Asia/Shanghai")
        holiday = datetime(2026, 10, 1, 10, 0, tzinfo=tz)

        self.assertFalse(is_trading_time(holiday, lambda value: False))
        self.assertFalse(is_post_close_report_time(holiday.replace(hour=15, minute=5), "15:05", lambda value: False))

    def test_non_trading_hours_sleep_until_next_market_boundary(self):
        config = configured_config()
        tz = ZoneInfo("Asia/Shanghai")
        monitor = RealTimePaperTradingMonitor(config, MockMarketDataStore(), MockQuoteProvider())

        self.assertEqual(monitor._sleep_seconds(datetime(2026, 8, 17, 8, 0, tzinfo=tz)), 3900)
        self.assertEqual(monitor._sleep_seconds(datetime(2026, 8, 17, 12, 0, tzinfo=tz)), 3600)
        self.assertEqual(monitor._sleep_seconds(datetime(2026, 8, 17, 15, 10, tzinfo=tz)), 3 * 60 * 60 + 50 * 60)

    def test_non_trading_day_sleep_skips_to_next_trading_day(self):
        config = configured_config()
        tz = ZoneInfo("Asia/Shanghai")
        monitor = RealTimePaperTradingMonitor(
            config,
            MockMarketDataStore(),
            MockQuoteProvider(),
            trading_day_checker=lambda value: value.weekday() < 5 and value != date(2026, 8, 18),
        )

        seconds = monitor._sleep_seconds(datetime(2026, 8, 17, 15, 30, tzinfo=tz))

        self.assertEqual(seconds, 3 * 60 * 60 + 30 * 60)

    def test_iteration_executes_and_persists_paper_fill(self):
        config = configured_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol), source="mock")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.aggregate_signals", side_effect=lambda signals, weights, aggregator=None: buy_signal(next(iter(signals)).symbol)):
                result = monitor.run_iteration(trade_now)
            loaded = store.load_portfolio(config.paper_account.initial_cash)
            fills = store.load_fills(trade_now.date())

        self.assertEqual(result.status, "traded")
        self.assertGreaterEqual(len(result.decisions), 1)
        self.assertGreaterEqual(len(fills), 1)
        self.assertLess(loaded.cash, config.paper_account.initial_cash)

    def test_bullish_real_strategy_pipeline_opens_a_position_from_cash(self):
        config = configured_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        store = MockMarketDataStore()
        for item in config.universe:
            store.save_bars(bars(item.symbol), source="mock")
        bullish = {
            "close": Decimal("1.10"), "sma20": Decimal("1.00"), "ema12": Decimal("1.08"), "ema26": Decimal("1.02"),
            "macd": Decimal("0.02"), "macd_histogram": Decimal("0.01"), "rsi14": Decimal("60"),
            "bollinger_z": Decimal("0.5"), "atr_ratio": Decimal("0.02"), "volume_ratio": Decimal("1.5"),
        }
        with patch("stock_ai_agent.monitor.build_features", side_effect=lambda symbol, *_: FeatureSet(symbol, trade_now, bullish)):
            result = RealTimePaperTradingMonitor(config, store, MockQuoteProvider()).run_iteration(trade_now)

        self.assertGreaterEqual(len(result.fills), 1)
        self.assertTrue(any(decision.direction in {Direction.BUY, Direction.ADD} for decision in result.decisions))

    def test_iteration_skips_outside_market_hours(self):
        config = configured_config()
        closed_now = datetime(2026, 8, 17, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            result = monitor.run_iteration(closed_now)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.fills, [])

    def test_monitor_applies_confirmed_backtest_before_next_iteration(self):
        config = configured_config()
        store = SQLiteMarketDataStore()
        store.ensure_strategy_defaults(config)
        store.record_backtest_run(
            "momentum_grid", {"lookback_days": 5}, {"total_return": "0.05"}, "待人工确认", "default"
        )
        run_id = store.load_backtest_runs()[0]["id"]
        from stock_ai_agent.web_actions import confirm_backtest_runs

        confirm_backtest_runs(config, store, [run_id])
        monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
        result = monitor.run_iteration(datetime(2026, 8, 17, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")))

        self.assertEqual(result.status, "skipped")
        self.assertEqual(store.load_backtest_runs()[0]["status"], "已应用")

    def test_monitor_prunes_previous_intraday_quotes_once_before_a_new_trading_day(self):
        pre_open = datetime(2026, 8, 17, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        class CountingStore(SQLiteMarketDataStore):
            def __init__(self, database):
                super().__init__(database)
                self.pruned_dates = []

            def prune_market_quotes(self, trade_date):
                self.pruned_dates.append(trade_date)
                return super().prune_market_quotes(trade_date)

        with tempfile.TemporaryDirectory() as tmp:
            store = CountingStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(load_config(), store, MockQuoteProvider())
            monitor.run_iteration(pre_open)
            monitor.run_iteration(pre_open)

        self.assertEqual(store.pruned_dates, [])

    def test_iteration_reports_missing_history_instead_of_silently_skipping(self):
        config = configured_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            result = monitor.run_iteration(trade_now)

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.decisions, [])
        self.assertTrue(any("588170.SH" in warning for warning in result.warnings))

    def test_iteration_does_not_evaluate_strategy_with_insufficient_history(self):
        config = configured_config()
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
        config = configured_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol), source="mock")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.aggregate_signals", side_effect=lambda signals, weights, aggregator=None: buy_signal(next(iter(signals)).symbol)):
                monitor.run_iteration(trade_now)
            report = monitor.generate_post_close_report(trade_now.date())
            stored = store.load_daily_report(trade_now.date())

        self.assertEqual(report["report_date"], "2026-08-17")
        self.assertEqual(stored["report_date"], "2026-08-17")
        self.assertGreaterEqual(len(stored["fills"]), 1)

    def test_post_close_report_moves_watchlist_to_dormant_after_repeated_watch_decisions(self):
        config = configured_config()
        report_date = date(2026, 8, 17)
        symbol = config.universe[0].symbol
        store = MockMarketDataStore()
        store.add_watchlist_item(symbol, config.universe[0].name, config.universe[0].asset_type)
        for offset in range(20):
            store.record_decision(
                Decision(symbol, Direction.WATCH, Decimal("0"), True, ["测试观望"]),
                report_date - timedelta(days=offset + 1),
            )

        monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
        report = monitor.generate_post_close_report(report_date)

        self.assertEqual(report["report_date"], report_date.isoformat())
        self.assertEqual(store.load_watchlist_items()[0]["lifecycle_status"], "dormant")

    def test_monitor_initializes_missing_watchlist_history_before_trading(self):
        config = configured_config()
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
            ), patch("stock_ai_agent.monitor.aggregate_signals", side_effect=lambda signals, weights, aggregator=None: buy_signal(next(iter(signals)).symbol)):
                monitor.run_forever(max_iterations=1, on_update=lambda result: setattr(self, "startup_result", result), ignore_market_hours=True, now_fn=lambda: trade_now)

            counts = [len(store.load_bars(item.symbol)) for item in config.universe]

        self.assertTrue(all(count >= 35 for count in counts))
        self.assertEqual(self.startup_result.status, "traded")

    def test_initialization_reuses_sufficient_database_history_without_remote_kline_call(self):
        config = configured_config()
        trade_now = datetime(2026, 8, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        class CountingHistoryProvider:
            def __init__(self):
                self.calls = []

            def get_bars(self, symbol, **kwargs):
                self.calls.append((symbol, kwargs))
                return bars(symbol)

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol), source="mock")
            history = CountingHistoryProvider()
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider(), history)
            with patch("stock_ai_agent.monitor.sync_instrument_catalog", return_value=2), patch(
                "stock_ai_agent.monitor.sync_benchmark_history", return_value={}
            ):
                ready, warnings = monitor.initialize_trading_data(trade_now.date())

        self.assertTrue(ready)
        self.assertEqual(warnings, [])
        self.assertEqual(history.calls, [])

    def test_intraday_daily_reference_sync_does_not_refresh_kline_history(self):
        config = configured_config()

        class InlineThread:
            def __init__(self, target, args=(), daemon=False):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.Thread", InlineThread), patch.object(
                monitor, "_sync_catalog_in_background"
            ) as catalog_sync, patch.object(monitor, "_sync_reference_data_in_background") as history_sync:
                monitor._sync_daily_reference_data(date(2026, 8, 17))

        catalog_sync.assert_called_once()
        history_sync.assert_not_called()

    def test_startup_benchmark_sync_stops_at_previous_weekday(self):
        config = configured_config()

        class InlineThread:
            def __init__(self, target, args=(), daemon=False):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            for item in config.universe:
                store.save_bars(bars(item.symbol), source="mock")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            with patch("stock_ai_agent.monitor.Thread", InlineThread), patch(
                "stock_ai_agent.monitor.sync_instrument_catalog", return_value=2
            ), patch("stock_ai_agent.monitor.sync_benchmark_history", return_value={}) as sync_benchmarks:
                monitor.initialize_trading_data(date(2026, 8, 17))

        self.assertEqual(sync_benchmarks.call_args.kwargs["as_of"], date(2026, 8, 14))

    def test_post_close_starts_incremental_history_sync(self):
        config = configured_config()
        close_now = datetime(2026, 8, 17, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

        class InlineThread:
            def __init__(self, target, args=(), daemon=False):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider())
            updates = []
            with patch("stock_ai_agent.monitor.Thread", InlineThread), patch.object(
                monitor, "_sync_reference_data_in_background"
            ) as history_sync:
                monitor.run_forever(max_iterations=1, on_update=updates.append, now_fn=lambda: close_now)

        self.assertEqual(updates[0].status, "reported")
        history_sync.assert_called_once_with(close_now.date(), True)

    def test_monitor_does_not_trade_when_startup_history_is_still_insufficient(self):
        config = configured_config()
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
        config = configured_config()
        close_now = datetime(2026, 8, 17, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))

        class FailingHistoryProvider:
            def get_bars(self, symbol, **kwargs):
                raise ConnectionError("历史源暂不可用")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "monitor.sqlite3")
            monitor = RealTimePaperTradingMonitor(config, store, MockQuoteProvider(), FailingHistoryProvider())
            updates = []
            with patch.object(monitor, "_sync_reference_data_in_background"):
                monitor.run_forever(max_iterations=1, on_update=updates.append, now_fn=lambda: close_now)
            report = store.load_daily_report(close_now.date())

        self.assertEqual(updates[0].status, "reported")
        self.assertIsNotNone(report)
        self.assertEqual(report["fills"], [])
        self.assertTrue(any("未进入策略执行阶段" in note for note in report["system_notes"]))


if __name__ == "__main__":
    unittest.main()
