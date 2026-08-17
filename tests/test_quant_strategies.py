import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Direction, FeatureSet
from stock_ai_agent.quant_strategies import (
    DrawdownControlStrategy,
    MeanReversionStrategy,
    QuantContext,
    RelativeStrengthRotationStrategy,
    TimeSeriesMomentumStrategy,
    VolatilityTargetStrategy,
)


def features(**overrides):
    values = {
        "close": Decimal("1.00"),
        "sma20": Decimal("1.00"),
        "bollinger_middle": Decimal("1.00"),
        "bollinger_z": Decimal("-1.5"),
        "atr_ratio": Decimal("0.02"),
    }
    values.update(overrides)
    return FeatureSet("588170.SH", datetime(2026, 8, 17, tzinfo=timezone.utc), values)


class QuantStrategyTests(unittest.TestCase):
    def test_time_series_momentum_positive(self):
        history = [Decimal("1.00")] * 21 + [Decimal("1.06")]
        context = QuantContext({"588170.SH": history}, {"588170.SH": Decimal("0")})

        signal = TimeSeriesMomentumStrategy(lookback_days=20).evaluate("588170.SH", features(), context)

        self.assertEqual(signal.direction, Direction.BUY)
        self.assertIn("动量", signal.explanation)

    def test_mean_reversion_buy_when_z_score_low(self):
        signal = MeanReversionStrategy().evaluate("588170.SH", features(bollinger_z=Decimal("-1.6")), QuantContext({}, {}))

        self.assertEqual(signal.direction, Direction.BUY)
        self.assertIn("z-score", signal.explanation)

    def test_relative_strength_prefers_stronger_etf(self):
        context = QuantContext(
            {
                "588170.SH": [Decimal("1.00")] * 21 + [Decimal("1.08")],
                "588200.SH": [Decimal("1.00")] * 21 + [Decimal("1.02")],
            },
            {},
        )

        signal = RelativeStrengthRotationStrategy(20).evaluate("588170.SH", features(), context)

        self.assertEqual(signal.direction, Direction.BUY)
        self.assertIn("强于", signal.explanation)

    def test_volatility_target_reduces_when_atr_high(self):
        signal = VolatilityTargetStrategy().evaluate("588170.SH", features(atr_ratio=Decimal("0.06")), QuantContext({}, {"588170.SH": Decimal("0.4")}))

        self.assertEqual(signal.direction, Direction.REDUCE)
        self.assertLessEqual(signal.target_weight, Decimal("0.20"))

    def test_drawdown_control_exits_when_stop_triggered(self):
        context = QuantContext({}, {"588170.SH": Decimal("0.4")}, {"588170.SH": Decimal("100")}, {"588170.SH": Decimal("90")})

        signal = DrawdownControlStrategy(stop=Decimal("0.08")).evaluate("588170.SH", features(), context)

        self.assertEqual(signal.direction, Direction.EXIT)
        self.assertIn("止损", signal.explanation)


if __name__ == "__main__":
    unittest.main()
