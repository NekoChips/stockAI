import unittest
from contextlib import contextmanager

from stock_ai_agent.config import MySQLConnectionConfig
from stock_ai_agent.storage.mysql import MySQLMarketDataStore


class MySQLStorageTests(unittest.TestCase):
    def test_schema_initialization_runs_only_once_per_store_instance(self):
        store = MySQLMarketDataStore(
            MySQLConnectionConfig(
                host="127.0.0.1",
                port=3306,
                database="stock_ai",
                username="stock_agent",
                password="secret",
            )
        )
        connection_count = 0

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def execute(self, statement):
                pass

        class Connection:
            def cursor(self):
                return Cursor()

        @contextmanager
        def fake_connect():
            nonlocal connection_count
            connection_count += 1
            yield Connection()

        store._connect = fake_connect

        store.initialize()
        store.initialize()

        self.assertEqual(connection_count, 1)


if __name__ == "__main__":
    unittest.main()
