import unittest

from stock_ai_agent.config import load_config
from stock_ai_agent.data.akshare_provider import AKShareAdapter
from stock_ai_agent.data.alphafeed import AlphaFeedAdapter, AlphaFeedRateLimitError
from stock_ai_agent.data.biying import BiyingAPIAdapter
from stock_ai_agent.data.eastmoney import EastmoneyPublicAdapter
from stock_ai_agent.data.providers import (
    FallbackHistoryDataProvider,
    FallbackMarketDataProvider,
    create_history_data_provider,
    create_market_data_provider,
)


class ProviderFactoryTests(unittest.TestCase):
    def test_default_provider_is_alphafeed_with_akshare_fallback(self):
        config = load_config()

        market = create_market_data_provider(config)
        self.assertIsInstance(market, FallbackMarketDataProvider)
        self.assertIsInstance(market.providers[0][1], AlphaFeedAdapter)
        self.assertIsInstance(market.providers[1][1], AKShareAdapter)
        provider = create_history_data_provider(config)
        self.assertIsInstance(provider, FallbackHistoryDataProvider)
        self.assertIsInstance(provider.providers[0][1], AlphaFeedAdapter)
        self.assertIsInstance(provider.providers[1][1], AKShareAdapter)
        self.assertIsInstance(provider.providers[2][1], EastmoneyPublicAdapter)

    def test_can_create_fallback_providers_by_name(self):
        config = load_config()

        self.assertIsInstance(create_market_data_provider(config, "eastmoney_public"), EastmoneyPublicAdapter)
        self.assertIsInstance(create_market_data_provider(config, "biying"), BiyingAPIAdapter)

    def test_history_provider_tries_next_source_after_failure(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from stock_ai_agent.models import Bar

        first = type("FailingProvider", (), {"get_bars": lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("primary down"))})()
        second = type(
            "WorkingProvider",
            (),
            {"get_bars": lambda self, **kwargs: [Bar(kwargs["symbol"], datetime.now(timezone.utc), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))]},
        )()
        provider = FallbackHistoryDataProvider([("primary", first), ("fallback", second)], attempts=1)

        bars = provider.get_bars("588170.SH")

        self.assertEqual(len(bars), 1)
        self.assertEqual(provider.last_source, "fallback")

    def test_market_provider_tries_akshare_after_alphafeed_failure(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from stock_ai_agent.models import Quote

        quote = Quote(
            symbol="588170.SH",
            name="科创100ETF基金",
            timestamp=datetime.now(timezone.utc),
            latest_price=Decimal("1.05"),
            open_price=Decimal("1.04"),
            high_price=Decimal("1.06"),
            low_price=Decimal("1.03"),
            previous_close=Decimal("1.04"),
            volume=Decimal("100"),
            amount=Decimal("1000"),
            change_percent=Decimal("1"),
            source="akshare",
            fetched_at=datetime.now(timezone.utc),
        )
        first = type("FailingProvider", (), {"get_quotes": lambda self, symbols: (_ for _ in ()).throw(RuntimeError("rate limited"))})()
        second = type("WorkingProvider", (), {"get_quotes": lambda self, symbols: {"588170.SH": quote}})()
        provider = FallbackMarketDataProvider([("alphafeed", first), ("akshare", second)])

        result = provider.get_quotes(["588170.SH"])

        self.assertEqual(result["588170.SH"].source, "akshare")
        self.assertEqual(provider.last_source, "akshare")

    def test_history_rate_limit_switches_without_retrying_alpha_feed(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from stock_ai_agent.models import Bar

        sleeps = []

        class RateLimitedProvider:
            def get_bars(self, **kwargs):
                raise AlphaFeedRateLimitError("429 rate limit")

        class WorkingProvider:
            def get_bars(self, **kwargs):
                return [Bar(kwargs["symbol"], datetime.now(timezone.utc), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))]

        provider = FallbackHistoryDataProvider(
            [("alphafeed", RateLimitedProvider()), ("akshare", WorkingProvider())],
            attempts=3,
            sleep_fn=sleeps.append,
        )

        bars = provider.get_bars("588170.SH")

        self.assertEqual(len(bars), 1)
        self.assertEqual(provider.last_source, "akshare")
        self.assertEqual(sleeps, [])

    def test_market_provider_fills_partial_primary_batch_from_fallback(self):
        from datetime import datetime, timezone
        from decimal import Decimal
        from stock_ai_agent.models import Quote

        def quote(symbol, source):
            now = datetime.now(timezone.utc)
            return Quote(symbol, symbol, now, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0"), source, now)

        first = type("PartialProvider", (), {"get_quotes": lambda self, symbols: {symbols[0]: quote(symbols[0], "alphafeed")}})()
        second = type("FallbackProvider", (), {"get_quotes": lambda self, symbols: {symbol: quote(symbol, "akshare") for symbol in symbols}})()
        provider = FallbackMarketDataProvider([("alphafeed", first), ("akshare", second)])

        result = provider.get_quotes(["588170.SH", "588200.SH"])

        self.assertEqual(set(result), {"588170.SH", "588200.SH"})
        self.assertEqual(result["588170.SH"].source, "alphafeed")
        self.assertEqual(result["588200.SH"].source, "akshare")


if __name__ == "__main__":
    unittest.main()
