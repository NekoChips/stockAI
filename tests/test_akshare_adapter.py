import unittest
import builtins
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from stock_ai_agent.data.akshare_provider import AKShareAdapter, AKShareError, parse_bars_table, parse_quote_table


class FakeAKShare:
    def fund_etf_spot_em(self):
        return [
            {
                "代码": "588170",
                "名称": "科创半导体ETF华夏",
                "最新价": "1.065",
                "开盘价": "1.018",
                "最高价": "1.071",
                "最低价": "1.015",
                "昨收": "1.021",
                "涨跌幅": "4.31",
                "成交量": "45942103",
                "成交额": "4810354175.0",
                "更新时间": "2026-08-17 11:30:10+08:00",
            }
        ]

    def fund_etf_hist_em(self, symbol, period, start_date, end_date, adjust):
        return [
            {"日期": "2026-08-14", "开盘": "1.000", "收盘": "1.020", "最高": "1.030", "最低": "0.990", "成交量": "10000", "成交额": "10150.00"},
            {"日期": "2026-08-17", "开盘": "1.020", "收盘": "1.050", "最高": "1.060", "最低": "1.010", "成交量": "12000", "成交额": "12480.00"},
        ]

    def stock_zh_a_spot_em(self):
        return [
            {"代码": "600519", "名称": "贵州茅台", "最新价": "1500"},
            {"代码": "200001", "名称": "深物业B", "最新价": "5"},
        ]


class FakeIndexFallbackAKShare(FakeAKShare):
    def __init__(self):
        self.calls = []

    def index_zh_a_hist(self, symbol, period, start_date, end_date):
        self.calls.append(("eastmoney", symbol))
        raise RuntimeError("push2his unavailable")

    def stock_zh_index_daily_tx(self, symbol):
        self.calls.append(("tencent", symbol))
        return [
            {"date": "2025-12-31", "open": "2990", "close": "3000", "high": "3010", "low": "2980", "amount": "1"},
            {"date": "2026-01-02", "open": "3000", "close": "3030", "high": "3040", "low": "2990", "amount": "2"},
            {"date": "2026-08-17", "open": "3900", "close": "3980", "high": "3990", "low": "3890", "amount": "3"},
            {"date": "2026-08-18", "open": "3980", "close": "3999", "high": "4001", "low": "3970", "amount": "4"},
        ]


class FakeCatalogFallbackAKShare(FakeAKShare):
    def fund_etf_spot_em(self):
        raise RuntimeError("eastmoney unavailable")

    def fund_etf_spot_ths(self):
        return [{"基金代码": "510300", "基金名称": "沪深300ETF"}]

    def stock_zh_a_spot_em(self):
        raise RuntimeError("eastmoney unavailable")

    def stock_zh_a_spot_tx(self):
        return [{"code": "600519", "name": "贵州茅台"}]


class AKShareAdapterTests(unittest.TestCase):
    def test_parse_realtime_quote_table(self):
        quote = parse_quote_table(FakeAKShare().fund_etf_spot_em(), "588170.SH", datetime(2026, 8, 17, 3, 30, 30, tzinfo=timezone.utc))

        self.assertEqual(quote.source, "akshare")
        self.assertEqual(quote.latest_price, Decimal("1.065"))
        self.assertEqual(quote.open_price, Decimal("1.018"))
        self.assertEqual(quote.high_price, Decimal("1.071"))
        self.assertEqual(quote.low_price, Decimal("1.015"))
        self.assertEqual(quote.previous_close, Decimal("1.021"))
        self.assertEqual(quote.change_percent, Decimal("4.31"))
        self.assertTrue(quote.is_fresh)

    def test_parse_history_bar_table(self):
        bars = parse_bars_table(FakeAKShare().fund_etf_hist_em("588170", "daily", "20260801", "20260817", "qfq"), "588170.SH")

        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[1].close_price, Decimal("1.050"))
        self.assertEqual(bars[1].amount, Decimal("12480.00"))

    def test_adapter_uses_akshare_functions(self):
        adapter = AKShareAdapter(ak_module=FakeAKShare())

        quote = adapter.get_quote("588170.SH")
        bars = adapter.get_bars("588170.SH", start="20260801", end="20260817")

        self.assertEqual(quote.name, "科创半导体ETF华夏")
        self.assertEqual(len(bars), 2)

    def test_searches_stock_and_etf_by_code_or_name(self):
        adapter = AKShareAdapter(ak_module=FakeAKShare())

        etfs = adapter.search_instruments("588170")
        stocks = adapter.search_instruments("茅台")

        self.assertEqual(etfs, [{"symbol": "588170.SH", "name": "科创半导体ETF华夏", "asset_type": "etf"}])
        self.assertEqual(stocks, [{"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "stock"}])

    def test_catalog_falls_back_when_eastmoney_spot_lists_are_unavailable(self):
        adapter = AKShareAdapter(ak_module=FakeCatalogFallbackAKShare())

        catalog = adapter.list_instruments()

        self.assertEqual(
            catalog,
            [
                {"symbol": "510300.SH", "name": "沪深300ETF", "asset_type": "etf"},
                {"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "stock"},
            ],
        )

    def test_index_history_falls_back_to_tencent_source(self):
        fake = FakeIndexFallbackAKShare()
        adapter = AKShareAdapter(ak_module=fake)

        bars = adapter.get_index_bars("000001.SH", "000001", start="20260101", end="20260817")

        self.assertEqual(fake.calls, [("eastmoney", "000001"), ("tencent", "sh000001")])
        self.assertEqual([bar.timestamp.date().isoformat() for bar in bars], ["2026-01-02", "2026-08-17"])
        self.assertEqual(bars[0].symbol, "000001.SH")
        self.assertEqual(bars[-1].close_price, Decimal("3980"))
        self.assertEqual(bars[-1].amount, Decimal("3"))

    def test_missing_dependency_has_chinese_message(self):
        adapter = AKShareAdapter(ak_module=None)

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "akshare":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(AKShareError) as ctx:
                adapter._akshare()

        self.assertIn("安装", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
