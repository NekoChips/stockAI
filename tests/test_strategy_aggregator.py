import unittest
from decimal import Decimal

from stock_ai_agent.models import Direction, StrategySignal
from stock_ai_agent.strategy import aggregate_signals


def signal(strategy_id, score, target, direction=Direction.BUY):
    return StrategySignal(
        strategy_id=strategy_id,
        symbol="588170.SH",
        direction=direction,
        score=Decimal(str(score)),
        confidence=Decimal("0.7"),
        target_weight=Decimal(str(target)),
        evidence=["支持证据"],
        objections=[] if score >= 0 else ["反对证据"],
        explanation="中文解释",
    )


class StrategyAggregatorTests(unittest.TestCase):
    def test_consistent_positive_signals_increase_confidence(self):
        result = aggregate_signals([signal("technical", 3, "0.40"), signal("time_series_momentum", 2, "0.40")])

        self.assertEqual(result.direction, Direction.BUY)
        self.assertEqual(result.target_weight, Decimal("0.40"))
        self.assertGreater(result.confidence, Decimal("0"))

    def test_conflicting_signals_are_conservative(self):
        result = aggregate_signals([signal("technical", 3, "0.60"), signal("mean_reversion", -2, "0")])

        self.assertEqual(result.direction, Direction.HOLD)
        self.assertLessEqual(result.target_weight, Decimal("0.20"))
        self.assertIn("冲突", result.explanation)

    def test_risk_penalty_can_only_reduce_weight(self):
        result = aggregate_signals([signal("technical", 3, "0.60"), signal("volatility_target", -1, "0.20", Direction.REDUCE)])

        self.assertLessEqual(result.target_weight, Decimal("0.20"))

    def test_neutral_drawdown_check_does_not_block_a_new_position(self):
        signals = [
            signal("technical_composite", 6, "0.60"),
            signal("time_series_momentum", 2, "0.40"),
            signal("drawdown_control", Decimal("0.5"), "1.00", Direction.HOLD),
        ]

        result = aggregate_signals(signals)

        self.assertEqual(result.direction, Direction.BUY)
        self.assertEqual(result.target_weight, Decimal("0.60"))

    def test_risk_cap_is_independent_of_signal_order(self):
        signals = [signal("technical_composite", 3, "0.60"), signal("volatility_target", -2, "0.20", Direction.REDUCE)]

        forward = aggregate_signals(signals)
        reverse = aggregate_signals(list(reversed(signals)))

        self.assertEqual(forward.target_weight, Decimal("0.20"))
        self.assertEqual(reverse.target_weight, Decimal("0.20"))


if __name__ == "__main__":
    unittest.main()
