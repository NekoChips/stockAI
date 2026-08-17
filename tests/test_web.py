import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.config import load_config
from stock_ai_agent.models import Portfolio, Position
from stock_ai_agent.storage.sqlite import SQLiteMarketDataStore
from stock_ai_agent.web import build_dashboard_payload, confirm_backtest_runs, render_dashboard_html


class WebDashboardTests(unittest.TestCase):
    def test_dashboard_payload_contains_core_sections(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "dashboard.sqlite3")
            store.save_portfolio(Portfolio(Decimal("990000"), {"588170.SH": Position("588170.SH", 10000, 10000, Decimal("1.00"), Decimal("1.10"))}))
            store.record_portfolio_snapshot(date(2026, 8, 17), store.load_portfolio(config.paper_account.initial_cash))
            store.record_backtest_run("momentum_grid", {"lookback_days": 5}, {"total_return": "0.05"}, "待人工确认")
            payload = build_dashboard_payload(config, store, as_of=date(2026, 8, 17))

        self.assertIn("portfolio", payload)
        self.assertIn("period_returns", payload)
        self.assertIn("profit_leaderboard", payload)
        self.assertIn("profit_calendar", payload)
        self.assertEqual(payload["equity_curve"][0]["day"], "2026-01-01")
        self.assertEqual(payload["profit_calendar"]["daily"][0]["period"], "2026-01-01")
        self.assertGreater(len(payload["benchmark_comparison"]), 100)
        series = {item["series"] for item in payload["benchmark_comparison"]}
        self.assertIn("AI-Agent", series)
        for benchmark in config.benchmarks:
            self.assertIn(benchmark.name, series)
        self.assertEqual(payload["backtest_runs"][0]["status"], "待人工确认")
        json.dumps(payload, ensure_ascii=False)

    def test_dashboard_html_references_local_api(self):
        html = render_dashboard_html()

        self.assertIn("AI-Agent 实时交易驾驶舱", html)
        self.assertIn("/api/dashboard", html)
        self.assertIn("盈亏排行榜", html)
        self.assertIn("盈亏分析", html)
        self.assertIn("calendarGrid", html)
        self.assertIn("交易看板", html)
        self.assertIn("回测记录", html)
        self.assertIn("批量确认", html)
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
        self.assertIn('data-mode="monthly"', html)
        self.assertIn('data-mode="yearly"', html)
        self.assertIn("clamp(10px, 2vw, 28px)", html)
        self.assertIn("@media (min-width: 1280px)", html)
        self.assertNotIn("收益率走势", html)
        self.assertNotIn('data-mode="daily"', html)
        self.assertNotIn("calendarValueTabs", html)
        self.assertNotIn("calendarPeriodSelect", html)
        self.assertNotIn("calendarPickerPanel", html)
        self.assertNotIn('class="picker-cell', html)
        self.assertNotIn("max-width: 920px", html)
        self.assertNotIn("周期收益率", html)
        self.assertNotIn("JSON.stringify(x.parameters)", html)

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
