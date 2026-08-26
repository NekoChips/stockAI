import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_ai_agent.config import InstrumentConfig, load_config
from stock_ai_agent.models import Direction, Portfolio, Position, Quote, StrategySignal
from stock_ai_agent.risk import RiskEngine
from stock_ai_agent.universe import Universe


def quote(symbol="588170.SH", minutes_old=0):
    fetched = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
    return Quote(
        symbol=symbol,
        name=symbol,
        timestamp=fetched - timedelta(minutes=minutes_old),
        latest_price=Decimal("1.00"),
        open_price=Decimal("1.00"),
        high_price=Decimal("1.02"),
        low_price=Decimal("0.98"),
        previous_close=Decimal("0.99"),
        volume=Decimal("1000000"),
        amount=Decimal("1000000"),
        change_percent=Decimal("1"),
        source="eastmoney_public",
        fetched_at=fetched,
        freshness_seconds=90,
    )


def signal(direction=Direction.BUY, target=Decimal("0.20"), symbol="588170.SH"):
    return StrategySignal("test", symbol, direction, Decimal("2"), Decimal("0.5"), target, ["中文证据"], [], "中文解释")


class RiskTests(unittest.TestCase):
    def setUp(self):
        config = load_config()
        self.engine = RiskEngine(config.risk, Universe.from_config([
            InstrumentConfig("588170.SH", "etf", "测试 ETF"),
            InstrumentConfig("588200.SH", "etf", "测试 ETF 2"),
        ]))

    def test_buy_order_respects_lot_size(self):
        result = self.engine.evaluate(signal(), Portfolio(Decimal("1000000")), quote())

        self.assertTrue(result.decision.approved)
        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.quantity % 100, 0)

    def test_rejects_stale_data(self):
        result = self.engine.evaluate(signal(), Portfolio(Decimal("1000000")), quote(minutes_old=5))

        self.assertFalse(result.decision.approved)
        self.assertIn("过期", result.decision.reasons[0])

    def test_rejects_symbol_outside_universe(self):
        result = self.engine.evaluate(signal(symbol="600519.SH"), Portfolio(Decimal("1000000")), quote("600519.SH"))

        self.assertFalse(result.decision.approved)
        self.assertIn("不在固定", result.decision.reasons[0])

    def test_rejects_when_t_plus_one_available_quantity_missing(self):
        portfolio = Portfolio(Decimal("100000"), {"588170.SH": Position("588170.SH", 1000, 0, Decimal("1.00"), Decimal("1.00"))})
        result = self.engine.evaluate(signal(Direction.REDUCE, Decimal("0.10")), portfolio, quote())

        self.assertFalse(result.decision.approved)
        self.assertIn("可卖数量不足", result.decision.reasons[0])

    def test_buy_respects_combined_portfolio_and_etf_exposure(self):
        portfolio = Portfolio(
            Decimal("400000"),
            {
                "588170.SH": Position("588170.SH", 600000, 600000, Decimal("1"), Decimal("1")),
            },
        )
        result = self.engine.evaluate(signal(target=Decimal("0.60"), symbol="588200.SH"), portfolio, quote("588200.SH"))

        self.assertFalse(result.decision.approved)
        self.assertIsNone(result.order)
        self.assertIn("总仓位", "；".join(result.decision.reasons))

    def test_max_drawdown_reduces_to_half_instead_of_exiting(self):
        portfolio = Portfolio(Decimal("20000"), {"588170.SH": Position("588170.SH", 40000, 40000, Decimal("1"), Decimal("1"))})
        result = self.engine.evaluate(signal(Direction.HOLD, Decimal("0.60")), portfolio, quote(), historical_peak=Decimal("100000"))

        self.assertTrue(result.decision.approved)
        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.direction, Direction.REDUCE)
        self.assertEqual(result.decision.target_weight, Decimal("0.30"))

    def test_disabled_instrument_rejects_buy_at_risk_boundary(self):
        config = load_config()
        engine = RiskEngine(
            config.risk,
            Universe.from_config([InstrumentConfig("588170.SH", "etf", "测试 ETF", trading_enabled=False)]),
        )

        result = engine.evaluate(signal(Direction.BUY), Portfolio(Decimal("1000000")), quote())

        self.assertFalse(result.decision.approved)
        self.assertIn("未启用交易", result.decision.reasons[0])

    def test_empty_position_neutral_signal_is_recorded_as_watch(self):
        result = self.engine.evaluate(signal(Direction.HOLD, Decimal("0.20")), Portfolio(Decimal("1000000")), quote())

        self.assertEqual(result.decision.direction, Direction.WATCH)
        self.assertIsNone(result.order)

    def test_held_position_neutral_signal_is_recorded_as_hold(self):
        portfolio = Portfolio(
            Decimal("1000000"),
            {"588170.SH": Position("588170.SH", 10000, 10000, Decimal("1.00"), Decimal("1.00"))},
        )
        result = self.engine.evaluate(signal(Direction.WATCH, Decimal("0")), portfolio, quote())

        self.assertEqual(result.decision.direction, Direction.HOLD)
        self.assertIsNone(result.order)


if __name__ == "__main__":
    unittest.main()
