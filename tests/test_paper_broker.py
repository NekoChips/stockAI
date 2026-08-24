import unittest
from decimal import Decimal

from stock_ai_agent.models import Direction, OrderStatus, PaperOrder, Portfolio, Position, Quote
from stock_ai_agent.paper_broker import PaperBroker, PaperBrokerError


class PaperBrokerTests(unittest.TestCase):
    def _quote(self, *, symbol="588170.SH", bid="0.99", ask="1.01", volume="100000"):
        now = __import__("datetime").datetime(2026, 8, 24, 10, 0, tzinfo=__import__("datetime").timezone.utc)
        return Quote(
            symbol, "测试 ETF", now, Decimal("1.00"), Decimal("1"), Decimal("1.02"), Decimal("0.98"),
            Decimal("1"), Decimal(volume), Decimal("100000"), Decimal("0"), "mock", now,
            bid_price=Decimal(bid), ask_price=Decimal(ask),
        )

    def test_order_moves_through_submit_partial_and_filled_states(self):
        portfolio = Portfolio(Decimal("100000"))
        broker = PaperBroker(portfolio, Decimal("0"), Decimal("0"))
        order = broker.submit(broker.approve(broker.create(PaperOrder("588170.SH", Direction.BUY, 300, Decimal("1.00"), order_id="o-1"))))

        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        first = broker.try_fill(order, self._quote(), max_fill_quantity=100)
        self.assertEqual(first.order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(first.fill.quantity, 100)
        final = broker.try_fill(first.order, self._quote(), max_fill_quantity=200)
        self.assertEqual(final.order.status, OrderStatus.FILLED)
        self.assertEqual(portfolio.positions["588170.SH"].quantity, 300)

    def test_buy_uses_ask_and_stock_sell_includes_stamp_duty_and_minimum_commission(self):
        portfolio = Portfolio(Decimal("100000"), {"600000.SH": Position("600000.SH", 100, 100, Decimal("1"), Decimal("1"))})
        broker = PaperBroker(portfolio, Decimal("0.0001"), Decimal("0"), min_commission=Decimal("5"), stock_sell_stamp_tax=Decimal("0.0005"))
        buy = broker.execute(PaperOrder("588170.SH", Direction.BUY, 100, Decimal("1"), asset_type="etf"), self._quote(ask="1.02"))
        sell = broker.execute(PaperOrder("600000.SH", Direction.EXIT, 100, Decimal("1"), asset_type="stock"), self._quote(symbol="600000.SH", bid="0.98"))

        self.assertEqual(buy.price, Decimal("1.0200"))
        self.assertEqual(buy.fee, Decimal("5.00"))
        self.assertEqual(sell.price, Decimal("0.9800"))
        self.assertEqual(sell.fee, Decimal("5.05"))
    def test_open_and_add_position_updates_cash_and_cost(self):
        portfolio = Portfolio(Decimal("100000"))
        broker = PaperBroker(portfolio, Decimal("0.0003"), Decimal("0.0005"))

        broker.execute(PaperOrder("588170.SH", Direction.BUY, 10000, Decimal("1.00")))
        broker.execute(PaperOrder("588170.SH", Direction.ADD, 10000, Decimal("1.10")))

        self.assertEqual(portfolio.positions["588170.SH"].quantity, 20000)
        self.assertLess(portfolio.cash, Decimal("100000"))

    def test_reduce_position_realizes_pnl(self):
        portfolio = Portfolio(Decimal("100000"), {"588170.SH": Position("588170.SH", 10000, 10000, Decimal("1.00"), Decimal("1.20"))})
        broker = PaperBroker(portfolio, Decimal("0.0003"), Decimal("0.0005"))

        fill = broker.execute(PaperOrder("588170.SH", Direction.REDUCE, 5000, Decimal("1.20")))

        self.assertGreater(fill.net_cash_change, Decimal("0"))
        self.assertEqual(portfolio.positions["588170.SH"].quantity, 5000)
        self.assertGreater(portfolio.positions["588170.SH"].realized_pnl, Decimal("0"))

    def test_rejects_unavailable_quantity(self):
        portfolio = Portfolio(Decimal("100000"), {"588170.SH": Position("588170.SH", 10000, 0, Decimal("1.00"), Decimal("1.20"))})
        broker = PaperBroker(portfolio, Decimal("0.0003"), Decimal("0.0005"))

        with self.assertRaises(PaperBrokerError):
            broker.execute(PaperOrder("588170.SH", Direction.EXIT, 10000, Decimal("1.20")))

    def test_rejects_quote_outside_daily_price_band(self):
        portfolio = Portfolio(Decimal("100000"))
        broker = PaperBroker(portfolio, Decimal("0"), Decimal("0"))

        with self.assertRaises(PaperBrokerError):
            broker.execute(PaperOrder("588170.SH", Direction.BUY, 100, Decimal("1.00")), self._quote(ask="1.11"))

    def test_rejects_quote_for_a_different_instrument(self):
        broker = PaperBroker(Portfolio(Decimal("100000")), Decimal("0"), Decimal("0"))
        attempt = broker.try_fill(
            broker.submit(broker.approve(broker.create(PaperOrder("588170.SH", Direction.BUY, 100, Decimal("1"))))),
            self._quote(symbol="588200.SH"),
        )
        self.assertEqual(attempt.order.status, OrderStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()
