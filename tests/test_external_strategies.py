import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Direction, FeatureSet, StrategyDataStatus
from stock_ai_agent.quant_strategies import (
    ExternalStrategyContext,
    FuturesPositionSentimentStrategy,
    LhbConsensusStrategy,
    LhbReverseInstitutionalStrategy,
    OverseasMarketSentimentStrategy,
    LhbFollowStarSeatsStrategy,
)
from stock_ai_agent.data.analysis_sources import fetch_lhb_data


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

    def test_missing_sector_uses_broad_market_as_the_comprehensive_sector(self):
        context = ExternalStrategyContext(
            overseas={"^IXIC": {"change_pct": "1.6"}, "^GSPC": {"change_pct": "0.5"}, "^DJI": {"change_pct": "0.3"}},
            sector="综合",
            sector_defaulted=True,
        )

        signal = OverseasMarketSentimentStrategy({}).evaluate("588170.SH", self.features, context)

        self.assertNotEqual(signal.data_status, StrategyDataStatus.UNAVAILABLE)

    def test_overseas_evidence_discloses_proxy_source(self):
        context = ExternalStrategyContext(
            overseas={
                "^IXIC": {"change_pct": "2.0", "source_symbol": "QQQ.US", "is_proxy": True},
                "^GSPC": {"change_pct": "0.5", "source_symbol": "SPY.US", "is_proxy": True},
                "^DJI": {"change_pct": "0.3", "source_symbol": "DIA.US", "is_proxy": True},
            },
            sector="综合",
            sector_defaulted=True,
        )
        signal = OverseasMarketSentimentStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertTrue(any("QQQ.US" in item and "代理" in item for item in signal.evidence))
        self.assertIn("综合", "；".join(signal.evidence))

    def test_lhb_reverse_requires_institutional_panic_and_gap_down(self):
        context = ExternalStrategyContext(lhb_records=[{"symbol": "588170.SH", "sell_seat_1": "机构专用", "sell_amount_1": "600", "sell_seat_2": "机构专用", "sell_amount_2": "600", "sell_seat_3": "机构专用", "sell_amount_3": "600"}], auction_gap_pct=Decimal("-3.2"))
        signal = LhbReverseInstitutionalStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)

    def test_lhb_reverse_can_use_summary_net_sell_without_seat_detail(self):
        context = ExternalStrategyContext(lhb_records=[{"symbol": "588170.SH", "seat_detail_available": False, "net_buy": "-1800"}], auction_gap_pct=Decimal("-3.2"))
        signal = LhbReverseInstitutionalStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)
        self.assertNotEqual(signal.data_status, StrategyDataStatus.UNAVAILABLE)

    def test_lhb_consensus_requires_star_and_institutional_buyers(self):
        context = ExternalStrategyContext(lhb_records=[{"symbol": "588170.SH", "buy_seat_1": "明星席位", "buy_amount_1": "1500", "buy_seat_2": "机构专用", "buy_amount_2": "1200"}], star_seats={"明星席位"})
        signal = LhbConsensusStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)

    def test_lhb_consensus_can_use_explicit_summary_fields_without_seat_detail(self):
        context = ExternalStrategyContext(
            lhb_records=[
                {
                    "symbol": "588170.SH",
                    "seat_detail_available": False,
                    "star_net_buy": "1500",
                    "institution_net_buy": "1200",
                }
            ]
        )
        signal = LhbConsensusStrategy({}).evaluate("588170.SH", self.features, context)
        self.assertEqual(signal.direction, Direction.BUY)

    def test_lhb_seat_strategy_is_unavailable_when_only_summary_data_exists(self):
        context = ExternalStrategyContext(
            lhb_records=[{"symbol": "588170.SH", "seat_detail_available": False, "net_buy": "1000"}],
            star_seats={"明星席位"},
        )

        signal = LhbFollowStarSeatsStrategy({}).evaluate("588170.SH", self.features, context)

        self.assertEqual(signal.direction, Direction.WATCH)
        self.assertEqual(signal.data_status, StrategyDataStatus.UNAVAILABLE)
        self.assertIn("席位明细", signal.data_status_reason)

    def test_lhb_adapter_normalizes_buy_and_sell_seat_details(self):
        class Frame:
            columns = ["代码", "名称", "上榜原因", "收盘价", "涨跌幅", "换手率", "成交额", "净买额"]

            def iterrows(self):
                return iter([(0, {"代码": "600000", "名称": "测试股票", "上榜原因": "日涨幅", "收盘价": 10, "涨跌幅": 2, "换手率": 3, "成交额": 1000, "净买额": 100})])

        class DetailFrame:
            columns = ["营业部名称", "买入金额", "卖出金额", "净额"]

            def __init__(self, rows):
                self.rows = rows

            def iterrows(self):
                return iter(list(enumerate(self.rows)))

        class FakeAk:
            def stock_lhb_detail_em(self, **kwargs):
                return Frame()

            def stock_lhb_stock_detail_em(self, symbol, date, flag):
                del symbol, date
                return DetailFrame(
                    [{"营业部名称": "明星席位", "买入金额": 1200, "卖出金额": 20, "净额": 1180}]
                    if flag == "买入"
                    else [{"营业部名称": "机构专用", "买入金额": 10, "卖出金额": 900, "净额": -890}]
                )

        rows = fetch_lhb_data(date(2026, 8, 25), ak_module=FakeAk())

        self.assertTrue(rows[0]["seat_detail_available"])
        self.assertEqual(rows[0]["buy_seat_1"], "明星席位")
        self.assertEqual(rows[0]["sell_seat_1"], "机构专用")


if __name__ == "__main__":
    unittest.main()
