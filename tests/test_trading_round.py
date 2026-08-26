import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Direction, OrderStatus, PaperOrder, Portfolio, Quote
from stock_ai_agent.paper_broker import PaperBroker
from stock_ai_agent.trading_round import execute_order_state_machine


class OrderStoreSpy:
    def __init__(self):
        self.orders = []

    def save_order(self, order, trade_date=None):
        self.orders.append(order)


class TradingRoundTests(unittest.TestCase):
    def test_shared_executor_persists_every_order_transition(self):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        quote = Quote(
            "588170.SH", "测试 ETF", now, Decimal("1.00"), Decimal("1.00"), Decimal("1.01"),
            Decimal("0.99"), Decimal("1.00"), Decimal("1000"), Decimal("1000"), Decimal("0"),
            "mock", now,
        )
        broker = PaperBroker(Portfolio(Decimal("100000")), Decimal("0.0003"), Decimal("0"))
        store = OrderStoreSpy()
        order = PaperOrder("588170.SH", Direction.BUY, 100, Decimal("1.00"), asset_type="etf")

        fill = execute_order_state_machine(broker, order, quote, store=store)

        self.assertEqual(fill.quantity, 100)
        self.assertEqual(
            [item.status for item in store.orders],
            [OrderStatus.CREATED, OrderStatus.APPROVED, OrderStatus.SUBMITTED, OrderStatus.FILLED],
        )
        self.assertEqual(broker.orders[-1].status, OrderStatus.FILLED)


if __name__ == "__main__":
    unittest.main()
