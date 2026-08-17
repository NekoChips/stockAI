import unittest
from decimal import Decimal

from stock_ai_agent.models import Direction, PaperOrder, Portfolio, Position
from stock_ai_agent.paper_broker import PaperBroker, PaperBrokerError


class PaperBrokerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
