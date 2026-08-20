import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from stock_ai_agent.models import Bar, Decision, Direction, Fill, Portfolio, Position, StrategySignal
from stock_ai_agent.storage.sqlite import SQLiteMarketDataStore


def bar(symbol="588170.SH", close="1.020"):
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 8, 17, tzinfo=timezone.utc),
        open_price=Decimal("1.000"),
        high_price=Decimal("1.030"),
        low_price=Decimal("0.990"),
        close_price=Decimal(close),
        volume=Decimal("10000"),
        amount=Decimal("10150.00"),
    )


class SQLiteStorageTests(unittest.TestCase):
    def test_save_and_load_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "bars.sqlite3")
            saved = store.save_bars([bar()], source="eastmoney_public")
            loaded = store.load_bars("588170.SH")

        self.assertEqual(saved, 1)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].close_price, Decimal("1.020"))

    def test_upsert_replaces_existing_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "bars.sqlite3")
            store.save_bars([bar(close="1.020")], source="eastmoney_public")
            store.save_bars([bar(close="1.050")], source="eastmoney_public")
            loaded = store.load_bars("588170.SH")

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].close_price, Decimal("1.050"))

    def test_user_watchlist_items_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "watchlist.sqlite3")
            store.add_watchlist_item("510300.SH", "沪深300ETF", "etf")
            store.add_watchlist_item("600519.SH", "贵州茅台", "stock")
            items = store.load_watchlist_items()

        self.assertEqual([item["symbol"] for item in items], ["510300.SH", "600519.SH"])
        self.assertEqual(items[0]["name"], "沪深300ETF")

    def test_instrument_catalog_search_and_watchlist_removal_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "catalog.sqlite3")
            store.replace_instrument_catalog(
                [
                    {"symbol": "600519.SH", "name": "贵州茅台", "asset_type": "stock"},
                    {"symbol": "510300.SH", "name": "沪深300ETF", "asset_type": "etf"},
                ],
                "2026-08-19",
                "akshare",
            )
            store.add_watchlist_item("510300.SH", "沪深300ETF", "etf")
            store.remove_watchlist_item("510300.SH")
            by_code = store.search_instrument_catalog("600519")
            by_name = store.search_instrument_catalog("沪深")
            remaining = store.load_watchlist_items()
            removed = store.load_removed_watchlist_symbols()

        self.assertEqual(by_code[0]["name"], "贵州茅台")
        self.assertEqual(by_name[0]["symbol"], "510300.SH")
        self.assertEqual(remaining, [])
        self.assertIn("510300.SH", removed)

    def test_save_and_load_paper_portfolio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "paper.sqlite3")
            portfolio = Portfolio(
                Decimal("990000.00"),
                {"588170.SH": Position("588170.SH", 10000, 0, Decimal("1.0000"), Decimal("1.1000"), Decimal("0"))},
            )
            store.save_portfolio(portfolio)
            loaded = store.load_portfolio(Decimal("1000000"))

        self.assertEqual(loaded.cash, Decimal("990000.00"))
        self.assertEqual(loaded.positions["588170.SH"].quantity, 10000)
        self.assertEqual(loaded.positions["588170.SH"].last_price, Decimal("1.1000"))

    def test_record_decisions_and_fills_by_trade_date(self):
        trade_date = datetime(2026, 8, 17, tzinfo=timezone.utc).date()
        signal = StrategySignal(
            "test",
            "588170.SH",
            Direction.BUY,
            Decimal("2"),
            Decimal("0.8"),
            Decimal("0.20"),
            ["量价配合"],
            [],
            "测试买入信号",
        )
        decision = Decision("588170.SH", Direction.BUY, Decimal("0.20"), True, ["风控通过"], signal)
        fill = Fill("588170.SH", Direction.BUY, 10000, Decimal("1.0000"), Decimal("3.00"), Decimal("5.00"), datetime.now(timezone.utc))

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "paper.sqlite3")
            store.record_decision(decision, trade_date)
            store.record_fill(fill, trade_date)
            decisions = store.load_decisions(trade_date)
            fills = store.load_fills(trade_date)
            fill_count = store.count_fills(trade_date)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].source_signal.explanation, "测试买入信号")
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].quantity, 10000)
        self.assertEqual(fill_count, 1)

    def test_t_plus_one_settlement_is_once_per_day(self):
        trade_date = datetime(2026, 8, 17, tzinfo=timezone.utc).date()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "paper.sqlite3")
            store.save_portfolio(Portfolio(Decimal("0"), {"588170.SH": Position("588170.SH", 10000, 0, Decimal("1"), Decimal("1"))}))
            first = store.settle_t_plus_one(trade_date)
            store.save_portfolio(Portfolio(Decimal("0"), {"588170.SH": Position("588170.SH", 12000, 0, Decimal("1"), Decimal("1"))}))
            second = store.settle_t_plus_one(trade_date)
            loaded = store.load_portfolio(Decimal("0"))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(loaded.positions["588170.SH"].available_quantity, 0)

    def test_portfolio_snapshots_and_backtest_runs_are_persisted(self):
        trade_date = datetime(2026, 8, 17, tzinfo=timezone.utc).date()
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "paper.sqlite3")
            store.record_portfolio_snapshot(trade_date, Portfolio(Decimal("100"), {"588170.SH": Position("588170.SH", 100, 100, Decimal("1"), Decimal("2"))}))
            store.record_backtest_run(
                "momentum_grid",
                {"lookback_days": 5, "threshold": "0.02"},
                {"total_return": "0.12", "max_drawdown": "0.03"},
                "待人工确认",
            )
            snapshots = store.load_portfolio_snapshots()
            runs = store.load_backtest_runs()

        self.assertEqual(snapshots[0][0], trade_date)
        self.assertEqual(snapshots[0][1], Decimal("300.00"))
        self.assertIn("id", runs[0])
        self.assertEqual(runs[0]["strategy_id"], "momentum_grid")
        self.assertEqual(runs[0]["status"], "待人工确认")

    def test_backtest_runs_can_be_confirmed_in_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "paper.sqlite3")
            store.record_backtest_run("momentum_grid", {"lookback_days": 5}, {"total_return": "0.12"}, "待人工确认")
            store.record_backtest_run("mean_reversion_grid", {"threshold": "-1.2"}, {"total_return": "0.03"}, "待人工确认")
            ids = [run["id"] for run in store.load_backtest_runs()]
            changed = store.update_backtest_run_status(ids, "已确认")
            runs = store.load_backtest_runs()

        self.assertEqual(changed, 2)
        self.assertEqual({run["status"] for run in runs}, {"已确认"})

    def test_daily_reports_are_upserted_listed_and_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteMarketDataStore(Path(tmp) / "reports.sqlite3")
            first = {"report_date": "2026-08-17", "status": "已归档", "summary": "无操作", "account": {"daily_pnl": "0.00"}, "positions": [], "fills": [], "decisions": []}
            updated = {**first, "summary": "已复盘", "account": {"daily_pnl": "120.00"}}
            older = {**first, "report_date": "2026-08-16"}
            store.save_daily_report(first)
            store.save_daily_report(updated)
            store.save_daily_report(older)
            rows = store.load_daily_reports(limit=10)
            detail = store.load_daily_report(date(2026, 8, 17))

        self.assertEqual([row["report_date"] for row in rows], ["2026-08-17", "2026-08-16"])
        self.assertEqual(rows[0]["daily_pnl"], "120.00")
        self.assertEqual(detail["summary"], "已复盘")


if __name__ == "__main__":
    unittest.main()
