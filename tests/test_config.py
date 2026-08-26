import unittest
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.app import create_market_data_store
from stock_ai_agent.config import load_config
from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.storage.mysql import MySQLMarketDataStore


class ConfigTests(unittest.TestCase):
    def test_default_config_matches_confirmed_decisions(self):
        config = load_config()

        self.assertEqual(config.data.provider, "alphafeed")
        self.assertEqual(config.data.market_fallback_providers, ["akshare"])
        self.assertEqual(config.data.history_provider, "alphafeed")
        self.assertEqual(config.data.history_fallback_providers, ["akshare", "eastmoney_public"])
        self.assertEqual(config.data.providers["alphafeed"]["quote_max_symbols_per_request"], 5)
        self.assertEqual(config.data.providers["alphafeed"]["quote_max_requests_per_minute"], 10)
        self.assertEqual(config.data.providers["alphafeed"]["kline_max_symbols_per_request"], 1)
        self.assertEqual(config.data.providers["alphafeed"]["kline_max_requests_per_minute"], 10)
        self.assertEqual(config.data.history["retry_attempts"], 1)
        self.assertEqual(config.data.providers["akshare"]["fund_spot_function"], "fund_etf_spot_em")
        self.assertEqual(config.storage.driver, "mock")
        self.assertEqual(config.environment, "development")
        self.assertEqual(config.storage.backup_dir, "")
        self.assertEqual(config.storage.database, "")
        self.assertIsInstance(create_market_data_store(config), MockMarketDataStore)
        self.assertEqual(config.paper_account.initial_cash, Decimal("1000000"))
        self.assertEqual(config.universe, [])
        self.assertEqual(config.risk.max_etf_total_weight, Decimal("0.50"))
        self.assertEqual(config.risk.max_stock_total_weight, Decimal("0.40"))
        self.assertEqual(config.risk.min_cash_ratio, Decimal("0.10"))
        self.assertIsNone(config.risk.max_daily_trades)
        self.assertEqual(config.risk.max_operations_per_symbol, 10)
        self.assertEqual([item.name for item in config.benchmarks][:2], ["上证指数", "深证成指"])
        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertTrue(config.strategy.manual_approval_required)
        self.assertIn("futures_position_sentiment", config.strategy.enabled_by_asset_type["etf"])
        self.assertIn("lhb_quant_sector", config.strategy.enabled_by_asset_type["etf"])
        self.assertEqual(config.monitor.poll_seconds, 60)
        self.assertTrue(config.monitor.respect_market_hours)

    def test_strategy_weights_include_quant_and_indicator_dimensions(self):
        config = load_config()

        expected = {
            "technical_composite",
            "time_series_momentum",
            "mean_reversion",
            "relative_strength",
            "volatility_target",
            "drawdown_control",
        }
        self.assertTrue(expected.issubset(config.strategy.weights))

    def test_release_example_inherits_development_settings_without_secrets(self):
        config = load_config(Path("config/release.example.yaml"))

        self.assertEqual(config.environment, "release")
        self.assertEqual(config.storage.driver, "mysql")
        self.assertEqual(config.storage.mysql.host, "${STOCK_AI_MYSQL_HOST}")
        self.assertEqual(config.storage.mysql.port, 12306)
        self.assertEqual(config.storage.mysql.database, "${STOCK_AI_MYSQL_DATABASE}")
        self.assertTrue(config.web.require_basic_auth)
        self.assertEqual(config.web.username, "${STOCK_AI_WEB_USERNAME}")
        self.assertEqual(config.strategy.target_weight_levels, [Decimal("0"), Decimal("0.20"), Decimal("0.40"), Decimal("0.60")])
        store = create_market_data_store(config)
        self.assertIsInstance(store, MySQLMarketDataStore)
        self.assertEqual(store.port, 12306)
        with self.assertRaisesRegex(ValueError, "发布配置不完整"):
            store.initialize()

    def test_release_config_reports_an_invalid_mysql_port(self):
        path = Path(self.id().replace(".", "_"))
        config_path = Path("/tmp") / f"{path.name}.json"
        self.addCleanup(config_path.unlink, missing_ok=True)
        config_path.write_text(
            '{"extends": "' + str(Path("config/default.yaml").resolve()) + '", "storage": {"driver": "mysql", "mysql": {"host": "db", "port": "invalid", "database": "stock_ai", "username": "agent", "password": "secret"}}}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "STOCK_AI_MYSQL_PORT"):
            load_config(config_path)


if __name__ == "__main__":
    unittest.main()
