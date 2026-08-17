import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_ai_agent.features import build_features, ema, macd, rsi, sma
from stock_ai_agent.models import Bar


def make_bars(count=40, start=Decimal("1.00"), step=Decimal("0.01")):
    base = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)
    bars = []
    for index in range(count):
        close = start + step * Decimal(index)
        bars.append(
            Bar(
                symbol="588170.SH",
                timestamp=base + timedelta(days=index),
                open_price=close - Decimal("0.005"),
                high_price=close + Decimal("0.020"),
                low_price=close - Decimal("0.020"),
                close_price=close,
                volume=Decimal("1000000") + Decimal(index * 10000),
            )
        )
    return bars


class FeatureTests(unittest.TestCase):
    def test_core_indicators_are_deterministic(self):
        closes = [Decimal(i) for i in range(1, 41)]

        self.assertEqual(sma(closes, 5), Decimal("38"))
        self.assertGreater(ema(closes, 12), ema(closes, 26))
        self.assertEqual(rsi(closes, 14), Decimal("100"))
        self.assertGreater(macd(closes)["macd"], Decimal("0"))
        accelerating = [Decimal(i) + Decimal(i * i) / Decimal("100") for i in range(1, 41)]
        self.assertGreater(macd(accelerating)["macd_histogram"], Decimal("0"))

    def test_build_features_contains_quant_inputs(self):
        features = build_features("588170.SH", make_bars())

        for key in ["sma5", "sma20", "ema12", "ema26", "macd_histogram", "rsi14", "bollinger_z", "atr14", "atr_ratio", "volume_ratio", "vwap"]:
            self.assertIn(key, features.values)
        self.assertTrue(features.is_complete)
        self.assertGreater(features.values["volume_ratio"], Decimal("1"))

    def test_missing_reasons_are_chinese_when_history_is_short(self):
        features = build_features("588170.SH", make_bars(count=5))

        self.assertFalse(features.is_complete)
        self.assertTrue(any("数据不足" in reason for reason in features.missing_reasons))


if __name__ == "__main__":
    unittest.main()
