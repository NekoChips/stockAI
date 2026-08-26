import unittest

from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.storage.mysql import MySQLMarketDataStore


class StorageContractTests(unittest.TestCase):
    def test_mock_and_mysql_adapters_expose_execution_contract(self):
        required = {
            "load_portfolio", "save_portfolio", "record_decision", "load_decisions",
            "record_fill", "load_fills", "count_fills", "save_order", "load_open_orders",
            "count_symbol_operations", "load_portfolio_snapshots", "settle_t_plus_one",
            "acquire_monitor_lock", "release_monitor_lock",
        }
        for adapter in (MockMarketDataStore, MySQLMarketDataStore):
            with self.subTest(adapter=adapter.__name__):
                self.assertTrue(required.issubset(set(dir(adapter))))


if __name__ == "__main__":
    unittest.main()
