import unittest
from datetime import datetime, timezone
from decimal import Decimal

from stock_ai_agent.data.eastmoney import EastmoneyPublicAdapter, eastmoney_secid, parse_kline_response, parse_quote_response


class EastmoneyAdapterTests(unittest.TestCase):
    def test_symbol_to_secid(self):
        self.assertEqual(eastmoney_secid("588170.SH"), "1.588170")
        self.assertEqual(eastmoney_secid("000001.SZ"), "0.000001")

    def test_parse_jsonp_quote_response(self):
        text = (
            'callback({"rc":0,"data":{"f57":"588170","f58":"科创100ETF基金",'
            '"f43":1234,"f46":1200,"f44":1250,"f45":1190,"f60":1198,'
            '"f47":1000000,"f48":1234000,"f170":301,"f86":"20260817093015",'
            '"f19":1233,"f39":1235}});'
        )
        fetched_at = datetime(2026, 8, 17, 1, 30, 30, tzinfo=timezone.utc)

        quote = parse_quote_response(text, "588170.SH", fetched_at=fetched_at)

        self.assertEqual(quote.symbol, "588170.SH")
        self.assertEqual(quote.name, "科创100ETF基金")
        self.assertEqual(quote.latest_price, Decimal("1.234"))
        self.assertEqual(quote.open_price, Decimal("1.200"))
        self.assertEqual(quote.change_percent, Decimal("3.01"))
        self.assertEqual(quote.source, "eastmoney_public")
        self.assertTrue(quote.is_fresh)
        self.assertEqual(quote.bid_price, Decimal("1.233"))
        self.assertEqual(quote.ask_price, Decimal("1.235"))

    def test_parse_historical_daily_kline_response(self):
        text = (
            'callback({"rc":0,"data":{"code":"588170","market":1,'
            '"klines":["2026-08-14,1.000,1.020,1.030,0.990,10000,10150.00,4.00,2.00,0.020,1.50",'
            '"2026-08-17,1.020,1.050,1.060,1.010,12000,12480.00,4.90,2.94,0.030,1.80"]}});'
        )

        bars = parse_kline_response(text, "588170.SH")

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].symbol, "588170.SH")
        self.assertEqual(bars[0].open_price, Decimal("1.000"))
        self.assertEqual(bars[1].close_price, Decimal("1.050"))
        self.assertEqual(bars[1].volume, Decimal("12000"))
        self.assertEqual(bars[1].amount, Decimal("12480.00"))

    def test_parse_epoch_quote_timestamp(self):
        text = (
            '{"rc":0,"data":{"f57":"588170","f58":"科创半导体ETF华夏",'
            '"f43":1065,"f46":1018,"f44":1071,"f45":1015,"f60":1021,'
            '"f47":45942103,"f48":4810354175.0,"f170":431,"f86":1786937610}}'
        )
        fetched_at = datetime(2026, 8, 17, 11, 33, 40, tzinfo=timezone.utc)

        quote = parse_quote_response(text, "588170.SH", fetched_at=fetched_at)

        self.assertEqual(quote.timestamp.year, 2026)
        self.assertEqual(quote.timestamp.tzinfo.key, "Asia/Shanghai")

    def test_index_history_uses_public_kline_endpoint(self):
        adapter = EastmoneyPublicAdapter()
        adapter.get_bars = lambda symbol, interval, start, end, adjust: [symbol, interval, start, end, adjust]

        bars = adapter.get_index_bars("000001.SH", "000001", start="20260101", end="20261231")

        self.assertEqual(bars, ["000001.SH", "daily", "20260101", "20261231", "none"])

    def test_index_history_accepts_shared_provider_keyword(self):
        adapter = EastmoneyPublicAdapter()
        adapter.get_bars = lambda symbol, interval, start, end, adjust: [symbol, interval, start, end, adjust]

        bars = adapter.get_index_bars(
            "000001.SH",
            akshare_symbol="000001",
            start="20260101",
            end="20261231",
        )

        self.assertEqual(bars[0], "000001.SH")


if __name__ == "__main__":
    unittest.main()
