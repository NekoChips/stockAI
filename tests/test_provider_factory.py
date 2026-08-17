import unittest

from stock_ai_agent.config import load_config
from stock_ai_agent.data.akshare_provider import AKShareAdapter
from stock_ai_agent.data.biying import BiyingAPIAdapter
from stock_ai_agent.data.eastmoney import EastmoneyPublicAdapter
from stock_ai_agent.data.providers import create_history_data_provider, create_market_data_provider


class ProviderFactoryTests(unittest.TestCase):
    def test_default_provider_is_akshare(self):
        config = load_config()

        self.assertIsInstance(create_market_data_provider(config), AKShareAdapter)
        self.assertIsInstance(create_history_data_provider(config), AKShareAdapter)

    def test_can_create_fallback_providers_by_name(self):
        config = load_config()

        self.assertIsInstance(create_market_data_provider(config, "eastmoney_public"), EastmoneyPublicAdapter)
        self.assertIsInstance(create_market_data_provider(config, "biying"), BiyingAPIAdapter)


if __name__ == "__main__":
    unittest.main()
