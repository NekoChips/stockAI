import unittest
from contextlib import contextmanager
from datetime import datetime

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

    def test_schema_contains_daily_reports_table(self):
        store = MySQLMarketDataStore(
            MySQLConnectionConfig(host="127.0.0.1", port=3306, database="stock_ai", username="stock_agent", password="secret")
        )
        statements = []

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, traceback): return False
            def execute(self, statement): statements.append(statement)

        class Connection:
            def cursor(self): return Cursor()

        @contextmanager
        def fake_connect():
            yield Connection()

        store._connect = fake_connect
        store.initialize()

        self.assertTrue(any("CREATE TABLE IF NOT EXISTS daily_reports" in statement for statement in statements))

    def test_schema_contains_calendar_and_strategy_tables(self):
        store = MySQLMarketDataStore(
            MySQLConnectionConfig(host="127.0.0.1", port=3306, database="stock_ai", username="agent", password="secret")
        )
        statements = []

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, traceback): return False
            def execute(self, statement): statements.append(statement)

        class Connection:
            def cursor(self): return Cursor()

        @contextmanager
        def fake_connect():
            yield Connection()

        store._connect = fake_connect
        store.initialize()

        self.assertTrue(any("CREATE TABLE IF NOT EXISTS trading_calendar" in statement for statement in statements))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS strategy_profiles" in statement for statement in statements))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS strategy_change_log" in statement for statement in statements))

    def test_daily_report_methods_preserve_summary_and_detail_contract(self):
        store = MySQLMarketDataStore(
            MySQLConnectionConfig(host="127.0.0.1", port=3306, database="stock_ai", username="stock_agent", password="secret")
        )
        store._initialized = True
        executed = []
        report = {"report_date": "2026-08-20", "status": "已归档", "summary": "无操作", "account": {"total_asset": "100", "daily_pnl": "0", "daily_return": "0"}, "positions": [], "fills": [], "decisions": []}
        store._execute = lambda sql, params=(): executed.append((sql, params)) or 1
        store._fetchall = lambda sql, params=(): [("2026-08-20", "已归档", "无操作", "100", "0", "0", "2026-08-20 15:05:00")]
        store._fetchone = lambda sql, params=(): (__import__("json").dumps(report, ensure_ascii=False),)

        store.save_daily_report(report)
        rows = store.load_daily_reports()
        detail = store.load_daily_report("2026-08-20")

        self.assertIn("ON DUPLICATE KEY UPDATE", executed[0][0])
        self.assertEqual(rows[0]["report_date"], "2026-08-20")
        self.assertEqual(detail, report)

    def test_overseas_rows_accept_iso_string_fetch_time(self):
        store = MySQLMarketDataStore(
            MySQLConnectionConfig(host="127.0.0.1", port=3306, database="stock_ai", username="agent", password="secret")
        )
        store._initialized = True
        captured = []
        store._executemany = lambda sql, values: captured.extend(values)
        store.save_overseas_market_data([{"market": "US", "symbol": "^IXIC", "trade_date": "2026-08-25", "prev_close": "100", "close_price": "101", "change_pct": "1", "fetched_at": "2026-08-26T09:05:00+00:00"}])
        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0][-1], str)
        self.assertTrue(captured[0][-1].startswith("2026-08-26 09:05:00"))


if __name__ == "__main__":
    unittest.main()
