import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stock_ai_agent.app import run_once
from stock_ai_agent.config import InstrumentConfig, load_config
from stock_ai_agent.models import Bar, Quote


class MockQuoteProvider:
    def get_quote(self, symbol):
        now = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
        return Quote(
            symbol=symbol,
            name=symbol,
            timestamp=now,
            latest_price=Decimal("1.39"),
            open_price=Decimal("1.30"),
            high_price=Decimal("1.41"),
            low_price=Decimal("1.28"),
            previous_close=Decimal("1.29"),
            volume=Decimal("2000000"),
            amount=Decimal("2780000"),
            change_percent=Decimal("7.75"),
            source="eastmoney_public",
            fetched_at=now,
        )


def bars(symbol):
    base = datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)
    result = []
    for index in range(40):
        close = Decimal("1.00") + Decimal(index) * Decimal("0.01")
        result.append(
            Bar(
                symbol=symbol,
                timestamp=base + timedelta(days=index),
                open_price=close - Decimal("0.005"),
                high_price=close + Decimal("0.02"),
                low_price=close - Decimal("0.02"),
                close_price=close,
                volume=Decimal("1000000") + Decimal(index * 10000),
            )
        )
    return result


class AppTests(unittest.TestCase):
    def test_run_once_generates_decisions_and_structured_report(self):
        config = load_config()
        config = replace(config, universe=[InstrumentConfig("588170.SH", "etf", "测试 ETF"), InstrumentConfig("588200.SH", "etf", "测试 ETF 2")])
        histories = {
            "588170.SH": [Decimal("1.00")] * 21 + [Decimal("1.08")],
            "588200.SH": [Decimal("1.00")] * 21 + [Decimal("1.02")],
        }
        bars_by_symbol = {symbol: bars(symbol) for symbol in histories}

        result = run_once(config, bars_by_symbol, histories, MockQuoteProvider())

        self.assertGreaterEqual(len(result.decisions), 1)
        self.assertEqual(result.report["status"], "临时运行")
        self.assertIn("decisions", result.report)

    def test_run_once_skips_symbols_with_insufficient_history(self):
        config = load_config()
        config = replace(config, universe=[InstrumentConfig("588170.SH", "etf", "测试 ETF"), InstrumentConfig("588200.SH", "etf", "测试 ETF 2")])
        histories = {item.symbol: [Decimal("1.00")] * 10 for item in config.universe}
        bars_by_symbol = {symbol: bars(symbol)[:10] for symbol in histories}

        result = run_once(config, bars_by_symbol, histories, MockQuoteProvider())

        self.assertEqual(result.decisions, [])
        self.assertEqual(result.fills, [])


if __name__ == "__main__":
    unittest.main()
