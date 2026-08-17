import unittest
from datetime import date
from decimal import Decimal

from stock_ai_agent.analytics import (
    build_benchmark_comparison,
    build_profit_calendar,
    build_profit_leaderboard,
    compute_period_returns,
    fill_daily_snapshots,
)
from stock_ai_agent.models import Bar, Fill, Direction, Portfolio, Position


def bar(symbol, day, close):
    from datetime import datetime

    return Bar(
        symbol=symbol,
        timestamp=datetime(day.year, day.month, day.day),
        open_price=Decimal(close),
        high_price=Decimal(close),
        low_price=Decimal(close),
        close_price=Decimal(close),
        volume=Decimal("1"),
        amount=Decimal("1"),
    )


class AnalyticsTests(unittest.TestCase):
    def test_fill_daily_snapshots_starts_from_2026_and_carries_forward(self):
        filled = fill_daily_snapshots(
            [(date(2026, 1, 3), Decimal("1001000"))],
            date(2026, 1, 1),
            date(2026, 1, 5),
            Decimal("1000000"),
        )

        self.assertEqual(filled[0], (date(2026, 1, 1), Decimal("1000000")))
        self.assertEqual(filled[1], (date(2026, 1, 2), Decimal("1000000")))
        self.assertEqual(filled[-1], (date(2026, 1, 5), Decimal("1001000")))

    def test_period_returns_support_daily_weekly_monthly_yearly(self):
        snapshots = [
            (date(2026, 8, 17), Decimal("1000000")),
            (date(2026, 8, 18), Decimal("1010000")),
            (date(2026, 8, 24), Decimal("1030000")),
            (date(2026, 9, 1), Decimal("990000")),
        ]

        result = compute_period_returns(snapshots)

        self.assertEqual(result["daily"][-1].return_rate, Decimal("-0.038835"))
        self.assertEqual(result["weekly"][-1].period, "2026-W36")
        self.assertEqual(result["monthly"][-1].period, "2026-09")
        self.assertEqual(result["yearly"][-1].period, "2026")

    def test_benchmark_comparison_normalizes_agent_and_indices(self):
        snapshots = [(date(2026, 8, 17), Decimal("100")), (date(2026, 8, 18), Decimal("110"))]
        benchmarks = {
            "000001.SH": [bar("000001.SH", date(2026, 8, 17), "3000"), bar("000001.SH", date(2026, 8, 18), "3030")]
        }

        result = build_benchmark_comparison(snapshots, benchmarks, {"000001.SH": "上证指数"})

        self.assertEqual(result[0].series, "AI-Agent")
        self.assertEqual(result[-1].series, "上证指数")
        self.assertEqual(result[-1].return_rate, Decimal("0.010000"))

    def test_profit_leaderboard_includes_amount_holding_days_and_rate(self):
        portfolio = Portfolio(
            Decimal("900000"),
            {"588170.SH": Position("588170.SH", 10000, 10000, Decimal("1.00"), Decimal("1.10"), Decimal("120"))},
        )
        fills = [
            Fill("588170.SH", Direction.BUY, 10000, Decimal("1.00"), Decimal("3"), Decimal("5"), bar("x", date(2026, 8, 17), "1").timestamp),
        ]

        rows = build_profit_leaderboard(portfolio, fills, {"588170.SH": "科创100ETF基金"}, as_of=date(2026, 8, 20))

        self.assertEqual(rows[0].symbol, "588170.SH")
        self.assertEqual(rows[0].profit_amount, Decimal("1120.00"))
        self.assertEqual(rows[0].holding_days, 4)
        self.assertEqual(rows[0].return_rate, Decimal("0.112000"))

    def test_profit_calendar_groups_daily_monthly_yearly_pnl(self):
        snapshots = [
            (date(2026, 8, 17), Decimal("1000000")),
            (date(2026, 8, 18), Decimal("1005000")),
            (date(2026, 9, 1), Decimal("995000")),
        ]

        calendar = build_profit_calendar(snapshots)

        self.assertEqual(calendar["daily"][-1].pnl, Decimal("-10000.00"))
        self.assertEqual(calendar["monthly"][-1].period, "2026-09")
        self.assertEqual(calendar["yearly"][0].pnl, Decimal("-5000.00"))


if __name__ == "__main__":
    unittest.main()
