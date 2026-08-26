import gzip
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.config import InstrumentConfig, load_config
from stock_ai_agent.models import Bar, Direction, Fill, Portfolio, Position, Quote
from stock_ai_agent.storage.mock import MockMarketDataStore as SQLiteMarketDataStore
from stock_ai_agent.web import (
    add_dashboard_watchlist_item,
    build_dashboard_backtests_payload,
    build_dashboard_calendar_payload,
    build_dashboard_data_health_payload,
    build_dashboard_lhb_raw_payload,
    build_dashboard_lhb_records_payload,
    build_dashboard_overview_payload,
    build_dashboard_payload,
    build_dashboard_performance_payload,
    build_dashboard_reports_payload,
    build_dashboard_sectors_payload,
    build_strategy_readiness_payload,
    build_dashboard_report_payload,
    build_instrument_detail_payload,
    confirm_backtest_runs,
    remove_dashboard_watchlist_item,
    search_watchlist_instruments,
    _send,
)
from stock_ai_agent.web_actions import confirm_dashboard_strategy_profile, save_dashboard_strategy_profile
from stock_ai_agent.web_actions import set_dashboard_watchlist_trading
from stock_ai_agent.web_dashboard import build_dashboard_strategies_payload


class WebDashboardTests(unittest.TestCase):
    def test_reference_data_payloads_expose_sector_and_lhb_raw_records(self):
        store = SQLiteMarketDataStore()
        store.save_sector_mapping("588170.SH", "信息技术", source="test")
        store.save_lhb_records([{"trade_date": "2026-08-26", "symbol": "588170.SH", "net_buy": "100", "raw_data": {"代码": "588170"}, "seat_detail_available": False}])

        sectors = build_dashboard_sectors_payload(store, "588170.SH")
        records = build_dashboard_lhb_records_payload(store, date(2026, 8, 26), "588170.SH")
        raw = build_dashboard_lhb_raw_payload(store, "2026-08-26|588170.SH")

        self.assertEqual(sectors["sectors"][0]["sector"], "信息技术")
        self.assertEqual(records["records"][0]["symbol"], "588170.SH")
        self.assertEqual(raw["raw"]["代码"], "588170")

    def test_strategy_readiness_reports_comprehensive_sector_and_data_health(self):
        config = replace(load_config(), universe=[InstrumentConfig("588170.SH", "etf", "科创100ETF基金")])
        store = SQLiteMarketDataStore()
        store.add_watchlist_item("588170.SH", "科创100ETF基金", "etf")
        store.save_data_task_status("external_us_daily", date(2026, 8, 26), "degraded", 10, 3, "QQQ 失败", __import__("datetime").datetime.now(), __import__("datetime").datetime.now())
        store.save_overseas_market_data([
            {"market": "US", "symbol": "^IXIC", "source_symbol": "QQQ.US", "is_proxy": True, "trade_date": "2026-08-25", "name": "纳斯达克", "prev_close": "100", "close_price": "101", "change_pct": "1", "source": "alphafeed", "data_status": "ready", "fetched_at": "2026-08-26T09:05:00+00:00"},
            {"market": "US", "symbol": "^GSPC", "source_symbol": "SPY.US", "is_proxy": True, "trade_date": "2026-08-25", "name": "标普500", "prev_close": "100", "close_price": "101", "change_pct": "1", "source": "alphafeed", "data_status": "ready", "fetched_at": "2026-08-26T09:05:00+00:00"},
            {"market": "US", "symbol": "^DJI", "source_symbol": "DIA.US", "is_proxy": True, "trade_date": "2026-08-25", "name": "道琼斯", "prev_close": "100", "close_price": "101", "change_pct": "1", "source": "alphafeed", "data_status": "ready", "fetched_at": "2026-08-26T09:05:00+00:00"},
        ])

        readiness = build_strategy_readiness_payload(config, store, "588170.SH", date(2026, 8, 26))
        health = build_dashboard_data_health_payload(config, store, date(2026, 8, 26))

        self.assertEqual(readiness["sector"]["value"], "综合")
        self.assertTrue(readiness["sector"]["defaulted"])
        self.assertEqual(len(health["tasks"]), 1)
    def test_new_strategy_profile_gets_server_generated_id(self):
        config = load_config()
        store = SQLiteMarketDataStore()

        saved = save_dashboard_strategy_profile(
            config,
            store,
            {
                "name_zh": "自动生成 ID 的组合",
                "name_en": "Generated Profile",
                "scope_type": "asset_type",
                "scope_value": "etf",
                "enabled": ["mean_reversion"],
                "weights": {"mean_reversion": "1"},
            },
        )

        profile_id = saved["saved_profile_id"]
        self.assertTrue(profile_id.startswith("profile_"))
        self.assertIn(profile_id, {item["profile_id"] for item in saved["strategies"]["profiles"]})

    def test_strategy_center_persists_draft_and_confirmation(self):
        config = load_config()
        store = SQLiteMarketDataStore()

        saved = save_dashboard_strategy_profile(
            config,
            store,
            {
                "profile_id": "588170.SH",
                "name_zh": "科创100组合",
                "name_en": "STAR 100 Profile",
                "scope_type": "symbol",
                "scope_value": "588170.SH",
                "enabled": ["mean_reversion"],
                "weights": {"mean_reversion": "1"},
            },
        )

        self.assertEqual(saved["strategies"]["profiles"][-1]["status"], "draft")
        confirmed = confirm_dashboard_strategy_profile(config, store, "588170.SH")
        self.assertEqual(
            next(item for item in confirmed["strategies"]["profiles"] if item["profile_id"] == "588170.SH")["status"],
            "active",
        )
        self.assertTrue(build_dashboard_strategies_payload(config, store)["strategies"]["definitions"])

    def test_instrument_detail_uses_persisted_ticks_bars_and_trade_markers(self):
        config = replace(load_config(), universe=[InstrumentConfig("588170.SH", "etf", "科创100ETF基金")])
        quote_time = date(2026, 8, 17)
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "detail.sqlite3")
            store.save_bars([
                Bar("588170.SH", date(2026, 8, day), Decimal("1"), Decimal("1.2"), Decimal("0.9"), Decimal("1.1") + Decimal(day) / Decimal("100"), Decimal("100"))
                for day in range(3, 18)
            ])
            store.save_quotes([
                Quote("588170.SH", "科创100ETF基金", __import__("datetime").datetime(2026, 8, 17, 9, 31), Decimal("1.21"), Decimal("1"), Decimal("1.22"), Decimal("1"), Decimal("1.2"), Decimal("1"), Decimal("1"), Decimal("1"), "mock", __import__("datetime").datetime(2026, 8, 17, 9, 31)),
                Quote("588170.SH", "科创100ETF基金", __import__("datetime").datetime(2026, 8, 17, 9, 36), Decimal("1.25"), Decimal("1"), Decimal("1.26"), Decimal("1"), Decimal("1.2"), Decimal("1"), Decimal("1"), Decimal("2"), "mock", __import__("datetime").datetime(2026, 8, 17, 9, 36)),
            ])
            store.save_bars([
                Bar("588170.SH", __import__("datetime").datetime(2026, 8, 14, 9, 31), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1.05"), Decimal("100")),
                Bar("588170.SH", __import__("datetime").datetime(2026, 8, 14, 9, 32), Decimal("1.05"), Decimal("1.2"), Decimal("1"), Decimal("1.15"), Decimal("100")),
            ], interval="minute", source="market_quotes")
            store.record_fill(Fill("588170.SH", Direction.BUY, 1000, Decimal("1.22"), Decimal("1"), Decimal("0"), __import__("datetime").datetime(2026, 8, 17, 9, 35)))
            payload = build_instrument_detail_payload(config, store, "588170.SH", as_of=quote_time)

        self.assertEqual(payload["instrument"]["symbol"], "588170.SH")
        self.assertEqual(len(payload["intraday"]["ticks"]), 2)
        self.assertEqual(
            [item["time"].date() for item in payload["five_day"]],
            [date(2026, 8, 14), date(2026, 8, 14), date(2026, 8, 17), date(2026, 8, 17)],
        )
        self.assertEqual(len(payload["minute_bars"]["5m"]), 2)
        self.assertEqual(payload["trade_markers"][0]["direction"], "买入")
    def test_send_compresses_large_response_when_client_accepts_gzip(self):
        class Writer:
            def __init__(self):
                self.body = b""

            def write(self, body):
                self.body = body

        class Handler:
            headers = {"Accept-Encoding": "gzip, deflate"}

            def __init__(self):
                self.wfile = Writer()
                self.response_headers = {}

            def send_response(self, status):
                self.status = status

            def send_header(self, name, value):
                self.response_headers[name] = value

            def end_headers(self):
                pass

        handler = Handler()
        body = ("看板数据" * 1000).encode("utf-8")

        _send(handler, "application/json; charset=utf-8", body)

        self.assertEqual(handler.response_headers["Content-Encoding"], "gzip")
        self.assertEqual(handler.response_headers["Vary"], "Accept-Encoding")
        self.assertEqual(gzip.decompress(handler.wfile.body), body)

    def test_send_ignores_client_disconnect(self):
        class BrokenPipeWriter:
            def write(self, body):
                raise BrokenPipeError(32, "Broken pipe")

        class Handler:
            wfile = BrokenPipeWriter()

            def send_response(self, status):
                self.status = status

            def send_header(self, name, value):
                pass

            def end_headers(self):
                pass

        _send(Handler(), "application/json; charset=utf-8", b"{}")

    def test_catalog_resolves_code_name_and_removal_updates_dashboard(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.replace_instrument_catalog(
                [{"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "stock"}],
                "2026-08-19",
                "akshare",
            )
            results = search_watchlist_instruments(config, store, "600519")
            added = add_dashboard_watchlist_item(
                config,
                store,
                {"symbol": "600519.SH", "name": "", "asset_type": "stock"},
            )
            removed = remove_dashboard_watchlist_item(config, store, "600519.SH")

        self.assertEqual(results, [{"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "stock"}])
        self.assertIn("600519.SH", {item["symbol"] for item in added["dashboard"]["watchlist"]})
        self.assertNotIn("600519.SH", {item["symbol"] for item in removed["watchlist"]})

    def test_removing_default_watchlist_item_hides_it_without_changing_config(self):
        config = replace(load_config(), universe=[InstrumentConfig("588170.SH", "etf", "科创100ETF基金")])
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            removed = remove_dashboard_watchlist_item(config, store, "588170.SH")

        self.assertNotIn("588170.SH", {item["symbol"] for item in removed["watchlist"]})
        self.assertIn("588170.SH", {item.symbol for item in config.universe})

    def test_watchlist_search_and_addition_are_persisted_in_dashboard(self):
        class SearchProvider:
            def search_instruments(self, query, limit=12):
                self.query = query
                return [{"symbol": "510300.SH", "name": "沪深300ETF", "asset_type": "etf"}]

        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            provider = SearchProvider()
            results = search_watchlist_instruments(config, store, "沪深", provider)
            added = add_dashboard_watchlist_item(
                config,
                store,
                {"symbol": "510300.SH", "name": "沪深300ETF", "asset_type": "etf"},
            )

        self.assertEqual(provider.query, "沪深")
        self.assertEqual(results[0]["symbol"], "510300.SH")
        self.assertEqual(added["item"]["symbol"], "510300.SH")
        self.assertIn("510300.SH", {item["symbol"] for item in added["dashboard"]["watchlist"]})
        self.assertEqual(
            search_watchlist_instruments(config, store, "600519"),
            [{"symbol": "600519.SH", "name": "名称待目录同步", "asset_type": "stock"}],
        )
        with self.assertRaises(ValueError):
            add_dashboard_watchlist_item(
                config,
                SQLiteMarketDataStore(Path(tmp) / "invalid.sqlite3"),
                {"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "etf"},
            )

    def test_dashboard_payload_contains_core_sections(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            class CountingStore(SQLiteMarketDataStore):
                snapshot_loads = 0

                def load_portfolio_snapshots(self):
                    self.snapshot_loads += 1
                    return super().load_portfolio_snapshots()

            store = CountingStore(Path(tmp) / "dashboard.sqlite3")
            store.save_portfolio(Portfolio(Decimal("990000"), {"588170.SH": Position("588170.SH", 10000, 10000, Decimal("1.00"), Decimal("1.10"))}))
            store.save_quotes([Quote("588170.SH", "科创100ETF基金", date(2026, 8, 17), Decimal("1.10"), Decimal("1"), Decimal("1.11"), Decimal("0.99"), Decimal("1.08"), Decimal("1"), Decimal("1"), Decimal("1.85"), "mock", date(2026, 8, 17))])
            store.record_portfolio_snapshot(date(2026, 8, 17), store.load_portfolio(config.paper_account.initial_cash))
            store.record_backtest_run("momentum_grid", {"lookback_days": 5}, {"total_return": "0.05"}, "待人工确认")
            payload = build_dashboard_payload(config, store, as_of=date(2026, 8, 17))

        self.assertIn("portfolio", payload)
        self.assertIn("period_returns", payload)
        self.assertIn("profit_leaderboard", payload)
        self.assertEqual(payload["market_quotes"]["588170.SH"]["change_percent"], "1.85")
        self.assertIn("profit_calendar", payload)
        self.assertEqual(payload["equity_curve"][0]["day"], "2026-01-01")
        self.assertEqual(payload["profit_calendar"]["daily"][0]["period"], "2026-01-01")
        self.assertEqual({item["series"] for item in payload["benchmark_comparison"]}, {"AI-Agent"})
        self.assertTrue(all(item["state"] == "待同步" for item in payload["benchmark_status"]))
        series = {item["series"] for item in payload["benchmark_comparison"]}
        self.assertIn("AI-Agent", series)
        self.assertEqual(payload["backtest_runs"][0]["status"], "待人工确认")
        self.assertEqual(store.snapshot_loads, 1)
        json.dumps(payload, ensure_ascii=False)

    def test_dashboard_section_payloads_have_independent_boundaries(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.record_portfolio_snapshot(date(2026, 8, 17), Portfolio(Decimal("1000000")))
            store.record_backtest_run("momentum_grid", {"lookback_days": 5}, {"total_return": "0.05"}, "待人工确认")

            overview = build_dashboard_overview_payload(config, store, as_of=date(2026, 8, 17))
            performance = build_dashboard_performance_payload(config, store, as_of=date(2026, 8, 17))
            calendar = build_dashboard_calendar_payload(config, store, as_of=date(2026, 8, 17))
            backtests = build_dashboard_backtests_payload(store)

        self.assertIn("portfolio", overview)
        self.assertIn("watchlist", overview)
        self.assertIn("pending_backtest_count", overview)
        self.assertIn("daily_return", overview)
        self.assertNotIn("period_returns", overview)
        self.assertNotIn("benchmark_comparison", overview)
        self.assertIn("benchmark_comparison", performance)
        self.assertNotIn("portfolio", performance)
        self.assertEqual(set(calendar), {"profit_calendar"})
        self.assertEqual(set(backtests), {"backtest_runs"})

    def test_daily_report_archive_has_summary_and_detail_boundaries(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.save_daily_report({
                "report_date": "2026-08-17", "status": "已归档", "summary": "今日无模拟成交。",
                "account": {"total_asset": "1000000.00", "daily_pnl": "0.00", "daily_return": "0"},
                "positions": [], "fills": [], "decisions": [],
            })
            archive = build_dashboard_reports_payload(store)
            detail = build_dashboard_report_payload(store, date(2026, 8, 17))

        self.assertEqual(set(archive), {"daily_reports"})
        self.assertNotIn("positions", archive["daily_reports"][0])
        self.assertEqual(detail["daily_report"]["report_date"], "2026-08-17")

    def test_dashboard_performance_interval_is_normalized_from_selected_start(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.record_portfolio_snapshot(date(2026, 8, 1), Portfolio(Decimal("100")))
            store.record_portfolio_snapshot(date(2026, 8, 2), Portfolio(Decimal("108")))
            store.save_bars(
                [
                    Bar("000001.SH", date(2026, 8, 1), Decimal("3000"), Decimal("3000"), Decimal("3000"), Decimal("3000"), Decimal("1")),
                    Bar("000001.SH", date(2026, 8, 2), Decimal("3030"), Decimal("3030"), Decimal("3030"), Decimal("3030"), Decimal("1")),
                ]
            )
            payload = build_dashboard_payload(
                config,
                store,
                as_of=date(2026, 8, 2),
                performance_start=date(2026, 8, 1),
                performance_end=date(2026, 8, 2),
            )

        agent_points = [item for item in payload["benchmark_comparison"] if item["series"] == "AI-Agent"]
        self.assertEqual(payload["performance_range"], {"start_date": "2026-08-01", "end_date": "2026-08-02"})
        self.assertEqual(agent_points[0]["return_rate"], "0.000000")
        self.assertEqual(agent_points[-1]["return_rate"], "0.080000")
        self.assertEqual(payload["benchmark_outperformance"][0]["difference"], "0.070000")

    def test_legacy_dashboard_renderer_is_removed(self):
        from stock_ai_agent import web_assets

        self.assertFalse(hasattr(web_assets, "render_dashboard_html"))

    def test_backtest_confirm_updates_selected_runs(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.record_backtest_run("momentum_grid", {"lookback_days": 5}, {"total_return": "0.05"}, "待人工确认")
            run_id = store.load_backtest_runs()[0]["id"]
            payload = confirm_backtest_runs(config, store, [run_id])

        self.assertEqual(payload["updated"], 1)
        self.assertEqual(payload["backtest_runs"][0]["status"], "待下一轮生效")
        profile = next(item for item in store.load_strategy_center(config)["profiles"] if item["profile_id"] == "default")
        self.assertTrue(profile["pending_activation"])
        self.assertEqual(profile["source_backtest_id"], run_id)

    def test_confirmed_backtest_is_applied_by_next_monitor_round(self):
        config = load_config()
        store = SQLiteMarketDataStore()
        store.ensure_strategy_defaults(config)
        store.record_backtest_run(
            "momentum_grid",
            {"lookback_days": 5, "threshold": "0.04", "target_weight": "0.40"},
            {"total_return": "0.05"},
            "待人工确认",
        )
        run_id = store.load_backtest_runs()[0]["id"]

        confirm_backtest_runs(config, store, [run_id])
        applied = store.apply_pending_strategy_profiles()
        self.assertEqual(applied[0]["profile_id"], "default")
        self.assertEqual(store.load_active_strategy_profile("588170.SH", "etf")["quant"]["lookback_days"], 5)
        store.mark_backtest_runs_applied([run_id])
        self.assertEqual(store.load_backtest_runs()[0]["status"], "已应用")

    def test_batch_backtest_confirmation_keeps_only_best_candidate_per_profile(self):
        config = load_config()
        store = SQLiteMarketDataStore()
        store.record_backtest_run(
            "momentum_grid", {"lookback_days": 5}, {"total_return": "0.05", "max_drawdown": "0.02"}, "待人工确认", "default"
        )
        store.record_backtest_run(
            "momentum_grid", {"lookback_days": 10}, {"total_return": "0.12", "max_drawdown": "0.02"}, "待人工确认", "default"
        )
        runs = store.load_backtest_runs(limit=None)
        payload = confirm_backtest_runs(config, store, [item["id"] for item in runs])
        statuses = {item["parameters"]["lookback_days"]: item["status"] for item in payload["backtest_runs"]}

        self.assertEqual(payload["queued"], 1)
        self.assertEqual(payload["rejected"], 1)
        self.assertEqual(statuses[10], "待下一轮生效")
        self.assertEqual(statuses[5], "已拒绝")

    def test_configured_watchlist_items_are_persisted_and_can_change_trading_permission(self):
        config = replace(
            load_config(),
            universe=[InstrumentConfig("588170.SH", "etf", "科创100ETF基金", trading_enabled=True)],
        )
        store = SQLiteMarketDataStore()

        overview = build_dashboard_overview_payload(config, store)
        self.assertEqual(store.load_watchlist_items()[0]["symbol"], "588170.SH")
        self.assertTrue(overview["watchlist"][0]["trading_enabled"])

        set_dashboard_watchlist_trading(config, store, "588170.SH", False)
        updated = build_dashboard_overview_payload(config, store)
        self.assertFalse(updated["watchlist"][0]["trading_enabled"])


if __name__ == "__main__":
    unittest.main()
