import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Direction, FeatureSet
from stock_ai_agent.strategy import StrategyContext, TechnicalCompositeStrategy


def feature_set(**overrides):
    values = {
        "close": Decimal("1.30"),
        "sma20": Decimal("1.10"),
        "ema12": Decimal("1.25"),
        "ema26": Decimal("1.15"),
        "macd": Decimal("0.03"),
        "macd_histogram": Decimal("0.01"),
        "rsi14": Decimal("62"),
        "bollinger_z": Decimal("0.8"),
        "atr_ratio": Decimal("0.02"),
        "volume_ratio": Decimal("1.4"),
    }
    values.update(overrides)
    return FeatureSet("588170.SH", datetime(2026, 8, 17, tzinfo=timezone.utc), values)


class TechnicalStrategyTests(unittest.TestCase):
    def test_buy_when_indicators_confirm(self):
        signal = TechnicalCompositeStrategy().evaluate(feature_set())

        self.assertEqual(signal.direction, Direction.BUY)
        self.assertEqual(signal.target_weight, Decimal("0.60"))
        self.assertIn("多指标", signal.explanation)
        self.assertTrue(any("MACD" in item for item in signal.evidence))

    def test_add_when_existing_position_and_score_improves(self):
        signal = TechnicalCompositeStrategy().evaluate(
            feature_set(),
            StrategyContext({"588170.SH": Decimal("0.20")}),
        )

        self.assertEqual(signal.direction, Direction.ADD)

    def test_reduce_when_overheated(self):
        signal = TechnicalCompositeStrategy().evaluate(
            feature_set(rsi14=Decimal("80"), bollinger_z=Decimal("2.4"), macd_histogram=Decimal("-0.01")),
            StrategyContext({"588170.SH": Decimal("0.40")}),
        )

        self.assertEqual(signal.direction, Direction.REDUCE)
        self.assertTrue(any("过热" in item for item in signal.objections))

    def test_exit_when_trend_breaks(self):
        signal = TechnicalCompositeStrategy().evaluate(
            feature_set(close=Decimal("1.00"), sma20=Decimal("1.10"), ema12=Decimal("1.05"), ema26=Decimal("1.12"), macd_histogram=Decimal("-0.03")),
            StrategyContext({"588170.SH": Decimal("0.40")}),
        )

        self.assertEqual(signal.direction, Direction.EXIT)

    def test_watch_when_data_missing(self):
        features = FeatureSet("588170.SH", datetime(2026, 8, 17, tzinfo=timezone.utc), {}, ["MACD 数据不足"])
        signal = TechnicalCompositeStrategy().evaluate(features)

        self.assertEqual(signal.direction, Direction.WATCH)
        self.assertIn("数据不足", signal.explanation)


if __name__ == "__main__":
    unittest.main()
