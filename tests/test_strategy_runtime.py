import unittest
from datetime import date
from decimal import Decimal

from stock_ai_agent.config import load_config
from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.strategy_runtime import load_external_strategy_context, profile_from_config, resolve_strategy_profile


class StrategyRuntimeTests(unittest.TestCase):
    def test_symbol_profile_overrides_default_after_confirmation(self):
        config = load_config()
        store = MockMarketDataStore()
        store.ensure_strategy_defaults(config)
        profile = profile_from_config(config, "588170.SH")
        profile.update({"scope_type": "symbol", "scope_value": "588170.SH", "enabled": ["mean_reversion"], "weights": {"mean_reversion": "1"}})
        store.save_strategy_profile(profile)
        store.confirm_strategy_profile("588170.SH")

        resolved = resolve_strategy_profile(config, store, "588170.SH", "etf")

        self.assertEqual(resolved["enabled"], ["mean_reversion"])
        self.assertEqual(resolved["weights"]["mean_reversion"], "1")
        self.assertEqual(resolve_strategy_profile(config, store, "588200.SH", "etf")["enabled"], config.strategy.enabled_by_asset_type["etf"])

    def test_unconfirmed_profile_does_not_change_runtime(self):
        config = load_config()
        store = MockMarketDataStore()
        store.ensure_strategy_defaults(config)
        profile = profile_from_config(config, "asset_type:etf")
        profile.update({"scope_type": "asset_type", "scope_value": "etf", "enabled": ["mean_reversion"]})
        store.save_strategy_profile(profile)

        resolved = resolve_strategy_profile(config, store, "588170.SH", "etf")

        self.assertEqual(resolved["enabled"], config.strategy.enabled_by_asset_type["etf"])

    def test_editing_active_profile_keeps_old_revision_until_confirmation(self):
        config = load_config()
        store = MockMarketDataStore()
        store.ensure_strategy_defaults(config)
        profile = profile_from_config(config, "588170.SH")
        profile.update({"scope_type": "symbol", "scope_value": "588170.SH", "enabled": ["mean_reversion"]})
        store.save_strategy_profile(profile)
        store.confirm_strategy_profile("588170.SH")
        changed = dict(profile)
        changed["enabled"] = ["time_series_momentum"]
        store.save_strategy_profile(changed)

        resolved = resolve_strategy_profile(config, store, "588170.SH", "etf")

        self.assertEqual(resolved["enabled"], ["mean_reversion"])

        center = store.load_strategy_center(config)
        pending = next(item for item in center["profiles"] if item["profile_id"] == "588170.SH")
        self.assertEqual(pending["status"], "draft")
        self.assertTrue(pending["pending_confirmation"])
        self.assertTrue(pending["draft_diff"])

        store.confirm_strategy_profile("588170.SH")
        resolved = resolve_strategy_profile(config, store, "588170.SH", "etf")
        self.assertEqual(resolved["enabled"], ["time_series_momentum"])

    def test_draft_can_be_withdrawn_without_rolling_back_active_profile(self):
        config = load_config()
        store = MockMarketDataStore()
        store.ensure_strategy_defaults(config)
        profile = profile_from_config(config, "588170.SH")
        profile.update({"scope_type": "symbol", "scope_value": "588170.SH", "enabled": ["mean_reversion"], "weights": {"mean_reversion": "1"}})
        store.save_strategy_profile(profile)
        store.confirm_strategy_profile("588170.SH")
        draft = dict(profile)
        draft["enabled"] = ["time_series_momentum"]
        draft["weights"] = {"time_series_momentum": "1"}
        store.save_strategy_profile(draft)

        store.discard_strategy_draft("588170.SH")

        self.assertEqual(resolve_strategy_profile(config, store, "588170.SH", "etf")["enabled"], ["mean_reversion"])

    def test_stale_external_data_is_excluded_from_strategy_context(self):
        store = MockMarketDataStore()
        store.save_futures_positions([{"trade_date": "2026-08-10", "contract": "IC", "combined_net_ratio": "0.70"}])
        store.save_overseas_market_data([{"market": "US", "symbol": "XLK", "trade_date": "2026-08-10", "prev_close": "1", "close_price": "2", "change_pct": "2"}])
        store.save_lhb_records([{"trade_date": "2026-08-10", "symbol": "588170.SH"}])

        context = load_external_strategy_context(store, "588170.SH", as_of=date(2026, 8, 24))

        self.assertIsNone(context.futures)
        self.assertEqual(context.overseas, {})
        self.assertEqual(context.lhb_records, [])


if __name__ == "__main__":
    unittest.main()
