import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Direction, Fill, PaperOrder, Portfolio, Position, Quote


class ModelTests(unittest.TestCase):
    def test_quote_freshness_and_order_amount(self):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        quote = Quote(
            symbol="588170.SH",
            name="科创100ETF基金",
            timestamp=now,
            latest_price=Decimal("1.234"),
            open_price=Decimal("1.200"),
            high_price=Decimal("1.250"),
            low_price=Decimal("1.190"),
            previous_close=Decimal("1.198"),
            volume=Decimal("1000000"),
            amount=Decimal("1234000"),
            change_percent=Decimal("3.01"),
            source="eastmoney_public",
            fetched_at=now,
        )
        order = PaperOrder("588170.SH", Direction.BUY, 1000, quote.latest_price)

        self.assertTrue(quote.is_fresh)
        self.assertEqual(order.notional, Decimal("1234.00"))

    def test_portfolio_values_positions(self):
        portfolio = Portfolio(
            cash=Decimal("900000"),
            positions={
                "588170.SH": Position("588170.SH", quantity=10000, average_cost=Decimal("1.00"), last_price=Decimal("1.20"))
            },
        )

        self.assertEqual(portfolio.total_market_value(), Decimal("12000.00"))
        self.assertEqual(portfolio.total_asset(), Decimal("912000.00"))
        self.assertEqual(portfolio.position_weight("588170.SH"), Decimal("0.0131"))

    def test_fill_net_cash_change(self):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        buy = Fill("588170.SH", Direction.BUY, 1000, Decimal("1.20"), Decimal("0.36"), Decimal("0.60"), now)
        sell = Fill("588170.SH", Direction.REDUCE, 1000, Decimal("1.30"), Decimal("0.39"), Decimal("0.65"), now)

        self.assertEqual(buy.net_cash_change, Decimal("-1200.36"))
        self.assertEqual(sell.net_cash_change, Decimal("1299.61"))


if __name__ == "__main__":
    unittest.main()
