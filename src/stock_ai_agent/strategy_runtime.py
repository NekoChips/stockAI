"""Resolve persisted strategy profiles and evaluate their enabled members."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from .config import AppConfig
from .quant_strategies import (
    DrawdownControlStrategy,
    MeanReversionStrategy,
    QuantContext,
    RelativeStrengthRotationStrategy,
    TimeSeriesMomentumStrategy,
    VolatilityTargetStrategy,
)
from .strategy import StrategyContext, TechnicalCompositeStrategy


STRATEGY_IDS = (
    "technical_composite",
    "time_series_momentum",
    "mean_reversion",
    "relative_strength",
    "volatility_target",
    "drawdown_control",
)


def profile_from_config(config: AppConfig, name: str = "default") -> dict[str, Any]:
    return {
        "profile_id": name,
        "name_zh": "默认复合策略",
        "name_en": "Default Composite",
        "scope_type": "default",
        "scope_value": "",
        "status": "active",
        "revision": 1,
        "enabled": list(STRATEGY_IDS),
        "weights": {key: str(value) for key, value in config.strategy.weights.items()},
        "technical": deepcopy(config.strategy.technical),
        "quant": deepcopy(config.strategy.quant),
        "aggregator": deepcopy(config.strategy.aggregator),
        "target_weight_levels": [str(item) for item in config.strategy.target_weight_levels],
    }


def resolve_strategy_profile(config: AppConfig, store: Any, symbol: str, asset_type: str) -> dict[str, Any]:
    fallback = profile_from_config(config)
    if not hasattr(store, "load_active_strategy_profile"):
        return fallback
    profile = store.load_active_strategy_profile(symbol, asset_type)
    if not profile:
        return fallback
    merged = deepcopy(fallback)
    merged.update(profile)
    merged["enabled"] = list(profile.get("enabled") or fallback["enabled"])
    for key in ("weights", "technical", "quant", "aggregator"):
        values = dict(fallback.get(key) or {})
        values.update(profile.get(key) or {})
        merged[key] = values
    return merged


def evaluate_strategy_profile(
    profile: dict[str, Any],
    symbol: str,
    features,
    strategy_context: StrategyContext,
    quant_context: QuantContext,
    high_atr_ratio: Decimal,
) -> list:
    enabled = set(profile.get("enabled") or STRATEGY_IDS)
    quant = profile.get("quant") or {}
    technical = profile.get("technical") or {}
    signals = []
    if "technical_composite" in enabled:
        signals.append(TechnicalCompositeStrategy(technical).evaluate(features, strategy_context))
    if "time_series_momentum" in enabled:
        signals.append(TimeSeriesMomentumStrategy(int(quant.get("lookback_days", 20))).evaluate(symbol, features, quant_context))
    if "mean_reversion" in enabled:
        signals.append(MeanReversionStrategy(Decimal(str(quant.get("mean_reversion_z", "-1.2")))).evaluate(symbol, features, quant_context))
    if "relative_strength" in enabled:
        signals.append(RelativeStrengthRotationStrategy(int(quant.get("lookback_days", 20))).evaluate(symbol, features, quant_context))
    if "volatility_target" in enabled:
        signals.append(VolatilityTargetStrategy(high_atr_ratio).evaluate(symbol, features, quant_context))
    if "drawdown_control" in enabled:
        signals.append(DrawdownControlStrategy(Decimal(str(quant.get("drawdown_stop", "0.08")))).evaluate(symbol, features, quant_context))
    return signals
