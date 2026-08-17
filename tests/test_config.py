import unittest
from decimal import Decimal

from stock_ai_agent.config import load_config


class ConfigTests(unittest.TestCase):
    def test_default_config_matches_confirmed_decisions(self):
        config = load_config()

        self.assertEqual(config.data.provider, "akshare")
        self.assertEqual(config.data.history_provider, "akshare")
        self.assertEqual(config.data.providers["akshare"]["fund_spot_function"], "fund_etf_spot_em")
        self.assertEqual(config.storage.driver, "sqlite")
        self.assertTrue(config.storage.database.endswith("stock_ai_agent.sqlite3"))
        self.assertEqual(config.paper_account.initial_cash, Decimal("1000000"))
        self.assertEqual([item.symbol for item in config.universe], ["588170.SH", "588200.SH"])
        self.assertEqual([item.name for item in config.benchmarks][:2], ["上证指数", "深证成指"])
        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertTrue(config.strategy.manual_approval_required)
        self.assertEqual(config.monitor.poll_seconds, 60)
        self.assertTrue(config.monitor.respect_market_hours)

    def test_strategy_weights_include_quant_and_indicator_dimensions(self):
        config = load_config()

        expected = {
            "trend",
            "momentum",
            "volatility",
            "volume",
            "risk_penalty",
            "time_series_momentum",
            "mean_reversion",
            "relative_strength",
            "volatility_target",
            "drawdown_control",
        }
        self.assertTrue(expected.issubset(config.strategy.weights))
        self.assertEqual(config.strategy.target_weight_levels, [Decimal("0"), Decimal("0.20"), Decimal("0.40"), Decimal("0.60")])


if __name__ == "__main__":
    unittest.main()
