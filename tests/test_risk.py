import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_ai_agent.config import load_config
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
        self.engine = RiskEngine(config.risk, Universe.from_config(config.universe))

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

    def test_buy_respects_combined_portfolio_exposure(self):
        portfolio = Portfolio(
            Decimal("400000"),
            {
                "588170.SH": Position("588170.SH", 600000, 600000, Decimal("1"), Decimal("1")),
            },
        )
        result = self.engine.evaluate(signal(target=Decimal("0.60"), symbol="588200.SH"), portfolio, quote("588200.SH"))

        self.assertTrue(result.decision.approved)
        self.assertIsNotNone(result.order)
        self.assertLessEqual(
            (portfolio.total_market_value() + result.order.notional) / portfolio.total_asset(),
            Decimal("0.90"),
        )


if __name__ == "__main__":
    unittest.main()
