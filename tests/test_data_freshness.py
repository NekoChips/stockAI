import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_ai_agent.models import Quote


class DataFreshnessTests(unittest.TestCase):
    def test_quote_freshness_blocks_stale_data(self):
        fetched_at = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        quote = Quote(
            symbol="588170.SH",
            name="科创100ETF基金",
            timestamp=fetched_at - timedelta(minutes=5),
            latest_price=Decimal("1.234"),
            open_price=Decimal("1.200"),
            high_price=Decimal("1.250"),
            low_price=Decimal("1.190"),
            previous_close=Decimal("1.198"),
            volume=Decimal("1000000"),
            amount=Decimal("1234000"),
            change_percent=Decimal("3.01"),
            source="eastmoney_public",
            fetched_at=fetched_at,
            freshness_seconds=90,
        )

        self.assertFalse(quote.is_fresh)


if __name__ == "__main__":
    unittest.main()
