import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from stock_ai_agent.models import Bar, Decision, Direction, OrderStatus, PaperOrder, Portfolio, Position, Quote
from stock_ai_agent.storage.mock import MockMarketDataStore


class MockStorageTests(unittest.TestCase):
    def test_development_store_has_no_filesystem_state_and_preserves_runtime_data(self):
        store = MockMarketDataStore()
        bar = Bar("588170.SH", datetime(2026, 8, 20, tzinfo=timezone.utc), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1.05"), Decimal("100"))
        quote = Quote("588170.SH", "科创100ETF基金", datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc), Decimal("1.06"), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1"), Decimal("100"), Decimal("100"), Decimal("6"), "mock", datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc))

        self.assertEqual(store.seed_watchlist_bars([bar]), 1)
        self.assertEqual(store.save_quotes([quote]), 1)
        self.assertEqual(store.load_watchlist_bars("588170.SH"), [bar])
        self.assertEqual(store.load_latest_quotes()["588170.SH"]["latest_price"], Decimal("1.06"))

    def test_prune_archives_previous_trade_day_quotes_as_minute_bars(self):
        store = MockMarketDataStore()
        quote = Quote("588170.SH", "科创100ETF基金", datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc), Decimal("1.06"), Decimal("1"), Decimal("1.1"), Decimal("0.9"), Decimal("1"), Decimal("100"), Decimal("100"), Decimal("6"), "mock", datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc))
        store.save_quotes([quote])

        self.assertEqual(store.prune_market_quotes(date(2026, 8, 21)), 1)
        self.assertEqual(len(store.load_intraday_bars("588170.SH", interval="1m")), 1)

    def test_repeated_same_decision_is_not_recorded_as_a_new_business_event(self):
        store = MockMarketDataStore()
        trade_date = date(2026, 8, 26)
        decision = Decision("588170.SH", Direction.WATCH, Decimal("0"), False, ["信号不足"])

        store.record_decision(decision, trade_date)
        store.record_decision(decision, trade_date)
        self.assertEqual(len(store.load_decision_events(trade_date)), 1)

        store.record_decision(
            replace(decision, direction=Direction.HOLD, reasons=["维持持仓"]),
            trade_date,
        )
        self.assertEqual(len(store.load_decision_events(trade_date)), 2)

    def test_repeated_approved_neutral_decision_with_changed_details_is_not_recorded(self):
        store = MockMarketDataStore()
        trade_date = date(2026, 8, 26)
        first = Decision("588170.SH", Direction.WATCH, Decimal("0.10"), True, ["首轮中性"], source_signal=None)
        second = Decision("588170.SH", Direction.WATCH, Decimal("0.20"), True, ["参与策略变化"], source_signal=None)

        store.record_decision(first, trade_date)
        store.record_decision(second, trade_date)

        events = store.load_decision_events(trade_date)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target_weight"], "0.10")

    def test_repeated_same_order_state_is_not_recorded_as_a_new_business_event(self):
        store = MockMarketDataStore()
        trade_date = date(2026, 8, 26)
        order = PaperOrder(
            "588170.SH", Direction.BUY, 100, Decimal("1.00"), order_id="order-1"
        )

        store.save_order(order, trade_date)
        store.save_order(order, trade_date)
        self.assertEqual(len(store.load_decision_events(trade_date)), 1)

        approved = replace(order, status=OrderStatus.APPROVED, updated_at=datetime.now(timezone.utc))
        store.save_order(approved, trade_date)
        self.assertEqual(len(store.load_decision_events(trade_date)), 2)

    def test_business_event_maintenance_compacts_legacy_rows_and_purges_expired_rows(self):
        store = MockMarketDataStore()
        store._decision_events.extend([
            {
                "trade_date": "2026-08-20", "symbol": "588170.SH", "phase": "decision",
                "direction": "观望", "approved": False, "target_weight": "0", "strategy_id": "s",
                "event_at": "2026-08-20T09:30:00", "event_key": "legacy-1",
            },
            {
                "trade_date": "2026-08-20", "symbol": "588170.SH", "phase": "decision",
                "direction": "观望", "approved": False, "target_weight": "0", "strategy_id": "s",
                "event_at": "2026-08-20T09:31:00", "event_key": "legacy-2",
            },
        ])

        self.assertEqual(store.compact_decision_events(), 1)
        self.assertEqual(store.purge_decision_events(date(2026, 8, 26), decision_retention_days=3), 1)

    def test_decision_event_keeps_position_context_without_creating_raw_evaluations(self):
        store = MockMarketDataStore()
        trade_date = date(2026, 8, 26)
        portfolio = Portfolio(
            Decimal("1000000"),
            {"588170.SH": Position("588170.SH", 10000, 10000, Decimal("1.00"), Decimal("1.00"))},
        )
        store.record_decision(Decision("588170.SH", Direction.HOLD, Decimal("0.01"), True, []), trade_date, portfolio)

        event = store.load_decision_events(trade_date)[0]
        self.assertEqual(event["position_state"], "held")
        self.assertEqual(event["position_quantity"], 10000)
        self.assertEqual(event["position_weight"], "0.0099")


if __name__ == "__main__":
    unittest.main()
