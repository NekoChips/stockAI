import unittest
from decimal import Decimal

from stock_ai_agent.backtest import BacktestResult
from stock_ai_agent.learning import propose_parameter_changes, summarize_learning


class LearningTests(unittest.TestCase):
    def test_learning_summary_and_proposals_require_manual_confirmation(self):
        backtest = BacktestResult(
            total_return=Decimal("0.05"),
            max_drawdown=Decimal("0.03"),
            win_rate=Decimal("0.60"),
            profit_loss_ratio=Decimal("1.8"),
            turnover=Decimal("0.4"),
            max_consecutive_losses=2,
            strategy_contributions={"mean_reversion": Decimal("-0.02")},
        )

        summary = summarize_learning(backtest.strategy_contributions, backtest)
        proposals = propose_parameter_changes(backtest.strategy_contributions, backtest)

        self.assertIn("策略学习总结", summary)
        self.assertEqual(proposals[0].status, "待人工确认")
        self.assertIn("降低", proposals[0].suggestion)


if __name__ == "__main__":
    unittest.main()
