import unittest
from decimal import Decimal

from stock_ai_agent.config import load_config
from stock_ai_agent.storage.mock import MockMarketDataStore
from stock_ai_agent.strategy_runtime import profile_from_config, resolve_strategy_profile


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

        store.confirm_strategy_profile("588170.SH")
        resolved = resolve_strategy_profile(config, store, "588170.SH", "etf")
        self.assertEqual(resolved["enabled"], ["time_series_momentum"])


if __name__ == "__main__":
    unittest.main()
