import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.data.biying import BiyingAPIAdapter, BiyingAPIError, parse_bars_response, parse_quote_response


class BiyingAdapterTests(unittest.TestCase):
    def test_parse_fund_realtime_quote(self):
        text = (
            '[{"dm":"588170","name":"科创半导体ETF华夏","p":"1.065","o":"1.018",'
            '"h":"1.071","l":"1.015","yc":"1.021","pc":"4.31","v":"45942103",'
            '"cje":"4810354175.0","t":"2026-08-17 11:30:10"}]'
        )
        fetched_at = datetime(2026, 8, 17, 3, 30, 30, tzinfo=timezone.utc)

        quote = parse_quote_response(text, "588170.SH", fetched_at)

        self.assertEqual(quote.source, "biying_api")
        self.assertEqual(quote.latest_price, Decimal("1.065"))
        self.assertEqual(quote.previous_close, Decimal("1.021"))
        self.assertEqual(quote.change_percent, Decimal("4.31"))
        self.assertTrue(quote.is_fresh)

    def test_parse_history_bars_response(self):
        text = (
            '[{"t":"2026-08-14","o":"1.000","h":"1.030","l":"0.990","c":"1.020","v":"10000","a":"10150.00"},'
            '{"t":"2026-08-17","o":"1.020","h":"1.060","l":"1.010","c":"1.050","v":"12000","a":"12480.00"}]'
        )

        bars = parse_bars_response(text, "588170.SH")

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[1].close_price, Decimal("1.050"))
        self.assertEqual(bars[1].amount, Decimal("12480.00"))

    def test_missing_licence_explains_configuration(self):
        old = os.environ.pop("BIYING_API_LICENCE", None)
        try:
            adapter = BiyingAPIAdapter({"licence": "", "licence_env": "BIYING_API_LICENCE"})
            with self.assertRaises(BiyingAPIError) as ctx:
                adapter.get_quote("588170.SH")
        finally:
            if old is not None:
                os.environ["BIYING_API_LICENCE"] = old

        self.assertIn("BIYING_API_LICENCE", str(ctx.exception))

    def test_url_paths_are_configurable(self):
        adapter = BiyingAPIAdapter(
            {
                "licence": "demo",
                "base_url": "https://example.test",
                "fund_realtime_path": "/custom/fund/{code}/{licence}",
            }
        )

        self.assertEqual(adapter.fund_realtime_path, "/custom/fund/{code}/{licence}")


if __name__ == "__main__":
    unittest.main()
