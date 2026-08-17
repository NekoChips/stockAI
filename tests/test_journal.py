import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from stock_ai_agent.journal import generate_daily_report
from stock_ai_agent.models import Decision, Direction, Fill, Portfolio, Position, StrategySignal


class JournalTests(unittest.TestCase):
    def test_daily_report_contains_chinese_sections_and_strategy_evidence(self):
        portfolio = Portfolio(Decimal("990000"), {"588170.SH": Position("588170.SH", 10000, 0, Decimal("1.00"), Decimal("1.10"))})
        signal = StrategySignal(
            "strategy_aggregator",
            "588170.SH",
            Direction.BUY,
            Decimal("2"),
            Decimal("0.6"),
            Decimal("0.20"),
            ["MACD 动能改善", "时间序列动量为正"],
            ["ATR 波动可控"],
            "多策略信号一致偏多。",
        )
        decision = Decision("588170.SH", Direction.BUY, Decimal("0.20"), True, ["风控通过"], signal)
        fill = Fill("588170.SH", Direction.BUY, 10000, Decimal("1.00"), Decimal("3"), Decimal("5"), datetime.now(timezone.utc))

        with tempfile.TemporaryDirectory() as tmp:
            path = generate_daily_report(date(2026, 8, 17), portfolio, [decision], [fill], tmp)
            content = path.read_text(encoding="utf-8")

        self.assertEqual(path.name, "daily_reports.md")
        self.assertIn("# 2026-08-17 A股模拟盘日报", content)
        self.assertIn("账户概览", content)
        self.assertIn("当前持仓", content)
        self.assertIn("今日操作", content)
        self.assertIn("执行逻辑与策略证据", content)
        self.assertIn("时间序列动量", content)

    def test_daily_report_replaces_same_date_and_appends_new_dates(self):
        portfolio = Portfolio(Decimal("1000000"))
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_daily_report(date(2026, 8, 17), portfolio, [], [], tmp)
            generate_daily_report(date(2026, 8, 17), portfolio, [], [], tmp)
            generate_daily_report(date(2026, 8, 18), portfolio, [], [], tmp)
            content = path.read_text(encoding="utf-8")

        self.assertEqual(content.count("# 2026-08-17 A股模拟盘日报"), 1)
        self.assertEqual(content.count("# 2026-08-18 A股模拟盘日报"), 1)


if __name__ == "__main__":
    unittest.main()
