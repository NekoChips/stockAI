import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Direction, FeatureSet
from stock_ai_agent.quant_strategies import (
    ExternalStrategyContext,
    FuturesPositionSentimentStrategy,
    LhbConsensusStrategy,
    LhbReverseInstitutionalStrategy,
    OverseasMarketSentimentStrategy,
)


class ExternalStrategyTests(unittest.TestCase):
    def setUp(self):
        self.features = FeatureSet("588170.SH", datetime(2026, 8, 24, tzinfo=timezone.utc), {"close": Decimal("1")})

    def test_futures_overheated_is_a_reduce_cap_not_directional_exit(self):
        context = ExternalStrategyContext(futures={"combined_net_ratio": "0.70"})
        signal = FuturesPositionSentimentStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.REDUCE)
        self.assertEqual(signal.score, Decimal("0"))
        self.assertEqual(signal.target_weight, Decimal("0.40"))

    def test_overseas_uses_external_market_only_as_a_share_signal(self):
        context = ExternalStrategyContext(overseas={"XLK": {"change_pct": "2.4"}, "^IXIC": {"change_pct": "1.6"}, "^GSPC": {"change_pct": "0.5"}, "^DJI": {"change_pct": "0.3"}, "KOSPI_IT": {"change_pct": "1.2"}}, sector="信息技术")
        signal = OverseasMarketSentimentStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)
        self.assertGreater(signal.score, Decimal("2"))

    def test_lhb_reverse_requires_institutional_panic_and_gap_down(self):
        context = ExternalStrategyContext(lhb_records=[{"symbol": "588170.SH", "sell_seat_1": "机构专用", "sell_amount_1": "600", "sell_seat_2": "机构专用", "sell_amount_2": "600", "sell_seat_3": "机构专用", "sell_amount_3": "600"}], auction_gap_pct=Decimal("-3.2"))
        signal = LhbReverseInstitutionalStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)

    def test_lhb_consensus_requires_star_and_institutional_buyers(self):
        context = ExternalStrategyContext(lhb_records=[{"symbol": "588170.SH", "buy_seat_1": "明星席位", "buy_amount_1": "1500", "buy_seat_2": "机构专用", "buy_amount_2": "1200"}], star_seats={"明星席位"})
        signal = LhbConsensusStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)


if __name__ == "__main__":
    unittest.main()
