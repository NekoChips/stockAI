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
    build_dashboard_overview_payload,
    build_dashboard_payload,
    build_dashboard_performance_payload,
    build_dashboard_reports_payload,
    build_dashboard_report_payload,
    build_instrument_detail_payload,
    confirm_backtest_runs,
    remove_dashboard_watchlist_item,
    render_dashboard_html,
    search_watchlist_instruments,
    _send,
)
from stock_ai_agent.web_actions import confirm_dashboard_strategy_profile, save_dashboard_strategy_profile
from stock_ai_agent.web_dashboard import build_dashboard_strategies_payload


class WebDashboardTests(unittest.TestCase):
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

    def test_dashboard_html_references_local_api(self):
        html = render_dashboard_html()

        self.assertIn("StockAI · 策略执行台", html)
        self.assertIn("/api/dashboard", html)
        self.assertIn("/api/dashboard/overview", html)
        self.assertIn("/api/dashboard/performance", html)
        self.assertIn("/api/dashboard/calendar", html)
        self.assertIn("/api/dashboard/backtests", html)
        self.assertIn("/api/dashboard/reports", html)
        self.assertIn("instrumentDetailView", html)
        self.assertIn("/api/instruments/", html)
        self.assertNotIn("fetch('/api/dashboard' + performanceQuery())", html)
        self.assertIn("loadBacktests", html)
        self.assertIn("盈亏排行榜", html)
        self.assertIn("盈亏分析", html)
        self.assertIn("calendarGrid", html)
        self.assertIn("交易看板", html)
        self.assertIn("回测记录", html)
        self.assertIn("日报归档", html)
        self.assertIn("dailyReportView", html)
        self.assertIn("loadDailyReports", html)
        self.assertIn("loadMoreDailyReports", html)
        self.assertIn("dailyReportRows", html)
        self.assertIn("确认所选", html)
        self.assertIn("calendarPeriodPicker", html)
        self.assertIn("antd@5.29.3", html)
        self.assertIn("react@18.3.1", html)
        self.assertIn("dayjs@1.11.22/locale/zh-cn.js", html)
        self.assertIn("DatePicker", html)
        self.assertIn("ConfigProvider", html)
        self.assertIn("zhDatePickerLocale", html)
        self.assertIn("请选择月份", html)
        self.assertIn("shortMonths", html)
        self.assertIn("十一月", html)
        self.assertIn("calendar-period-popup", html)
        self.assertIn("calendarValueToggle", html)
        self.assertIn("看收益额", html)
        self.assertIn("ant-picker", html)
        self.assertIn("popupClassName", html)
        self.assertNotIn('<script src="https://unpkg.com/', html)
        self.assertIn("loadOptionalUiLibraries", html)
        self.assertLess(html.rfind("const initialDashboardLoad = load()"), html.rfind("loadOptionalUiLibraries"))
        self.assertIn('data-mode="monthly"', html)
        self.assertIn('data-mode="yearly"', html)
        self.assertIn("clamp(16px,3vw,48px)", html)
        self.assertIn("@media (max-width:1100px)", html)
        self.assertNotIn("收益率走势", html)
        self.assertNotIn('data-mode="daily"', html)
        self.assertNotIn("calendarValueTabs", html)
        self.assertNotIn("calendarPeriodSelect", html)
        self.assertNotIn("calendarPickerPanel", html)
        self.assertNotIn('class="picker-cell', html)
        self.assertNotIn("max-width: 920px", html)
        self.assertNotIn("周期收益率", html)
        self.assertNotIn("JSON.stringify(x.parameters)", html)
        self.assertNotIn("ticker-track", html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("refreshDashboard", html)
        self.assertIn("decisionTimeline", html)
        self.assertIn("chartLegend", html)
        self.assertIn("chartTooltip", html)
        self.assertIn("toggleChartSeries", html)
        self.assertIn("showChartPoint", html)
        self.assertIn("ResizeObserver", html)
        self.assertIn("lucide@", html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn(".decision-panel { grid-column:2; display:flex", html)
        self.assertIn("positions-scroll", html)
        self.assertIn("行情订阅已就绪", html)
        self.assertIn("align-items:stretch", html)
        self.assertIn(".decision-panel { grid-column:2; display:flex", html)
        self.assertIn(".positions-panel { grid-column:1; display:flex", html)
        self.assertIn("#positions { display:flex; flex:1", html)
        self.assertIn(".positions-footer { flex:none", html)
        self.assertIn(".calendar-total > div { display:flex", html)
        self.assertIn("添加标的", html)
        self.assertIn("instrumentDrawer", html)
        self.assertIn("/api/watchlist/search", html)
        self.assertIn("addSelectedInstrument", html)
        self.assertIn("removeWatchlistItem", html)
        self.assertIn("benchmarkStatus", html)
        self.assertIn("data-remove-symbol", html)
        self.assertIn("performanceRangeTabs", html)
        self.assertIn("benchmarkOutperformance", html)
        self.assertIn('grid-template-columns:max-content 256px', html)
        self.assertIn('grid-template-areas:"range picker" ". chart"', html)
        self.assertIn('#performanceRangeTabs { grid-area:range; }', html)
        self.assertIn('#chartTabs { grid-area:chart; justify-self:end; }', html)
        self.assertIn('.performance-range-picker .ant-picker { width:100%;', html)
        self.assertIn('const nextMode = button.dataset.mode, currentRange = performanceRange();', html)
        self.assertIn('performanceStart = currentRange.start;', html)
        self.assertIn("performanceRangeMode='custom'", html)
        self.assertNotIn("performanceRangeMode !== 'custom'", html)
        self.assertIn('@media (min-width:721px) and (max-width:1500px)', html)
        self.assertIn('.performance-panel .panel-head { display:grid; grid-template-columns:minmax(0,1fr); gap:14px; }', html)
        self.assertIn("dayFormat:'D'", html)
        self.assertNotIn("dayFormat:'D日'", html)
        self.assertIn("const disabledDate=current=>{if(!current)return false;const key=calendarMode", html)
        self.assertNotIn("optionSet=new Set(options)", html)
        self.assertLess(html.index('class="chart-wrap"'), html.index('id="benchmarkOutperformance"'))
        self.assertNotIn('onclick="removeWatchlistItem(', html)
        self.assertNotIn('onclick="toggleChartSeries(', html)
        self.assertNotIn('class="chart-summary"', html)

    def test_backtest_confirm_updates_selected_runs(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.record_backtest_run("momentum_grid", {"lookback_days": 5}, {"total_return": "0.05"}, "待人工确认")
            run_id = store.load_backtest_runs()[0]["id"]
            payload = confirm_backtest_runs(config, store, [run_id])

        self.assertEqual(payload["updated"], 1)
        self.assertEqual(payload["backtest_runs"][0]["status"], "已确认")


if __name__ == "__main__":
    unittest.main()
