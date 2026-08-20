import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from stock_ai_agent.journal import build_daily_report
from stock_ai_agent.models import Decision, Direction, Fill, Portfolio, Position, StrategySignal


class JournalTests(unittest.TestCase):
    def test_daily_report_is_structured_and_contains_strategy_evidence(self):
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

        report = build_daily_report(
            date(2026, 8, 17),
            portfolio,
            [decision],
            [fill],
            previous_total_asset=Decimal("1000000"),
        )

        self.assertEqual(report["report_date"], "2026-08-17")
        self.assertEqual(report["status"], "已归档")
        self.assertEqual(report["account"]["daily_pnl"], "1000.00")
        self.assertEqual(report["positions"][0]["symbol"], "588170.SH")
        self.assertEqual(report["fills"][0]["direction"], "买入")
        self.assertTrue(any("时间序列动量" in item for item in report["decisions"][0]["evidence"]))
        self.assertIn("买入", report["summary"])

    def test_empty_daily_report_explains_that_no_trade_was_executed(self):
        portfolio = Portfolio(Decimal("1000000"))
        report = build_daily_report(date(2026, 8, 17), portfolio, [], [])

        self.assertEqual(report["positions"], [])
        self.assertEqual(report["fills"], [])
        self.assertEqual(report["decisions"], [])
        self.assertIn("没有模拟成交", report["summary"])


if __name__ == "__main__":
    unittest.main()
