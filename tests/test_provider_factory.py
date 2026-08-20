import unittest

from stock_ai_agent.config import load_config
from stock_ai_agent.data.akshare_provider import AKShareAdapter
from stock_ai_agent.data.biying import BiyingAPIAdapter
from stock_ai_agent.data.eastmoney import EastmoneyPublicAdapter
from stock_ai_agent.data.providers import FallbackHistoryDataProvider, create_history_data_provider, create_market_data_provider


class ProviderFactoryTests(unittest.TestCase):
    def test_default_provider_is_akshare(self):
        config = load_config()

        self.assertIsInstance(create_market_data_provider(config), AKShareAdapter)
        provider = create_history_data_provider(config)
        self.assertIsInstance(provider, FallbackHistoryDataProvider)
        self.assertIsInstance(provider.providers[0][1], AKShareAdapter)
        self.assertIsInstance(provider.providers[1][1], EastmoneyPublicAdapter)

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


if __name__ == "__main__":
    unittest.main()
