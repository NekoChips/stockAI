from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.models import Bar, Portfolio
from stock_ai_agent.storage.backup import backup_sqlite_database, restore_sqlite_database
from stock_ai_agent.storage.sqlite import SQLiteMarketDataStore


def bar(close: str) -> Bar:
    return Bar(
        symbol="588170.SH",
        timestamp=datetime(2026, 8, 20, tzinfo=timezone.utc),
        open_price=Decimal(close),
        high_price=Decimal(close),
        low_price=Decimal(close),
        close_price=Decimal(close),
        volume=Decimal("100"),
        amount=Decimal("100"),
    )


class SQLiteBackupTests(unittest.TestCase):
    def test_database_persists_after_store_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "stock.sqlite3"
            SQLiteMarketDataStore(database).save_bars([bar("1.01")])

            reopened = SQLiteMarketDataStore(database)

            self.assertEqual(reopened.load_bars("588170.SH")[0].close_price, Decimal("1.01"))

    def test_restore_replaces_changed_data_and_keeps_rollback_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "stock.sqlite3"
            store = SQLiteMarketDataStore(database)
            store.save_bars([bar("1.01")])
            store.save_portfolio(Portfolio(Decimal("1000000")))

            backup = backup_sqlite_database(database, root / "backups")
            store.save_bars([bar("1.99")])
            store.save_portfolio(Portfolio(Decimal("500000")))

            restored = restore_sqlite_database(database, backup.path, root / "backups")
            reopened = SQLiteMarketDataStore(database)

            self.assertEqual(reopened.load_bars("588170.SH")[0].close_price, Decimal("1.01"))
            self.assertEqual(reopened.load_portfolio(Decimal("0")).cash, Decimal("1000000"))
            self.assertIsNotNone(restored.rollback_backup)
            self.assertTrue(restored.rollback_backup.exists())

    def test_restore_rejects_invalid_backup_before_replacing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "stock.sqlite3"
            SQLiteMarketDataStore(database).save_bars([bar("1.01")])
            invalid = root / "invalid.sqlite3"
            invalid.write_text("not a sqlite database", encoding="utf-8")

            with self.assertRaises(ValueError):
                restore_sqlite_database(database, invalid, root / "backups")

            self.assertEqual(SQLiteMarketDataStore(database).load_bars("588170.SH")[0].close_price, Decimal("1.01"))
