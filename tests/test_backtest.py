import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from stock_ai_agent.backtest import optimize_strategy_parameters, run_simple_backtest
from stock_ai_agent.models import Bar


class BacktestTests(unittest.TestCase):
    def test_backtest_outputs_metrics_and_contributions(self):
        result = run_simple_backtest(
            [Decimal("1.00"), Decimal("1.10"), Decimal("1.05"), Decimal("1.20")],
            {"time_series_momentum": [Decimal("0.05"), Decimal("-0.01")]},
        )

        self.assertGreater(result.total_return, Decimal("0"))
        self.assertGreaterEqual(result.max_drawdown, Decimal("0"))
        self.assertGreater(result.win_rate, Decimal("0"))
        self.assertIn("time_series_momentum", result.strategy_contributions)

    def test_optimizer_selects_best_parameter_set_without_enabling_it(self):
        base = datetime(2026, 7, 1)
        bars = []
        for index in range(30):
            price = Decimal("1.00") + Decimal(index) * Decimal("0.01")
            bars.append(
                Bar(
                    symbol="588170.SH",
                    timestamp=base + timedelta(days=index),
                    open_price=price,
                    high_price=price,
                    low_price=price,
                    close_price=price,
                    volume=Decimal("100000"),
                )
            )

        result = optimize_strategy_parameters(
            {"588170.SH": bars},
            lookback_days=[3, 5],
            thresholds=[Decimal("0.01"), Decimal("0.03")],
            target_weights=[Decimal("0.30"), Decimal("0.60")],
        )

        self.assertGreater(len(result.candidates), 1)
        self.assertEqual(result.best.status, "待人工确认")
        self.assertIn("lookback_days", result.best.parameters)
        self.assertGreater(result.best.metrics.total_return, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
