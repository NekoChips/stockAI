"""Resolve persisted strategy profiles and evaluate their enabled members."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .config import AppConfig
from .quant_strategies import (
    DrawdownControlStrategy,
    ExternalStrategyContext,
    FuturesPositionSentimentStrategy,
    LhbConsensusStrategy,
    LhbFollowStarSeatsStrategy,
    LhbQuantSectorStrategy,
    LhbReverseInstitutionalStrategy,
    LhbSeatProfileStrategy,
    MeanReversionStrategy,
    OverseasMarketSentimentStrategy,
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
    "futures_position_sentiment",
    "overseas_market_sentiment",
    "lhb_follow_star_seats",
    "lhb_reverse_institutional",
    "lhb_seat_profile",
    "lhb_consensus",
    "lhb_quant_sector",
)
LEGACY_STRATEGY_ID_ALIASES = {
    "futures_sentiment": "futures_position_sentiment",
    "overseas_sentiment": "overseas_market_sentiment",
    "lhb_follow": "lhb_follow_star_seats",
    "quant_sector_rotation": "lhb_quant_sector",
}


def profile_from_config(config: AppConfig, name: str = "default", asset_type: str = "etf") -> dict[str, Any]:
    enabled = config.strategy.enabled_by_asset_type.get(asset_type) or [
        "technical_composite",
        "time_series_momentum",
    ]
    weights = config.strategy.weights_by_asset_type.get(asset_type) or config.strategy.weights
    weights = {key: value for key, value in weights.items() if key in enabled}
    return {
        "profile_id": name,
        "name_zh": "默认复合策略",
        "name_en": "Default Composite",
        "scope_type": "default",
        "scope_value": "",
        "status": "active",
        "config_schema_version": 2,
        "revision": 1,
        "enabled": list(enabled),
        "weights": {key: str(value) for key, value in weights.items()},
        "technical": deepcopy(config.strategy.technical),
        "quant": deepcopy(config.strategy.quant),
        "external": deepcopy(config.strategy.external),
        "aggregator": deepcopy(config.strategy.aggregator),
        "target_weight_levels": [str(item) for item in config.strategy.target_weight_levels],
    }


def resolve_strategy_profile(config: AppConfig, store: Any, symbol: str, asset_type: str) -> dict[str, Any]:
    fallback = profile_from_config(config, asset_type=asset_type)
    if not hasattr(store, "load_active_strategy_profile"):
        return fallback
    profile = store.load_active_strategy_profile(symbol, asset_type)
    if not profile:
        return fallback
    merged = deepcopy(fallback)
    merged.update(profile)
    merged["enabled"] = list(profile.get("enabled") or fallback["enabled"])
    for key in ("weights", "technical", "quant", "external", "aggregator"):
        values = dict(fallback.get(key) or {})
        values.update(profile.get(key) or {})
        merged[key] = values
    merged["weights"] = {key: value for key, value in merged["weights"].items() if key in merged["enabled"]}
    merged["enabled"] = [LEGACY_STRATEGY_ID_ALIASES.get(key, key) for key in merged["enabled"]]
    merged["weights"] = {LEGACY_STRATEGY_ID_ALIASES.get(key, key): value for key, value in merged["weights"].items()}
    return merged


def evaluate_strategy_profile(
    profile: dict[str, Any],
    symbol: str,
    features,
    strategy_context: StrategyContext,
    quant_context: QuantContext,
    high_atr_ratio: Decimal,
    external_context: ExternalStrategyContext | None = None,
) -> list:
    enabled = set(profile.get("enabled") or STRATEGY_IDS)
    quant = profile.get("quant") or {}
    technical = profile.get("technical") or {}
    signals = []
    if "technical_composite" in enabled:
        signals.append(TechnicalCompositeStrategy(technical).evaluate(features, strategy_context))
    if "time_series_momentum" in enabled:
        signals.append(
            TimeSeriesMomentumStrategy(
                int(quant.get("lookback_days", 20)),
                Decimal(str(quant.get("momentum_threshold", "0.03"))),
                Decimal(str(quant.get("momentum_exit_threshold", "-0.02"))),
                Decimal(str(quant.get("momentum_target_weight", "0.40"))),
            ).evaluate(symbol, features, quant_context)
        )
    if "mean_reversion" in enabled:
        signals.append(MeanReversionStrategy(Decimal(str(quant.get("mean_reversion_z", "-1.2")))).evaluate(symbol, features, quant_context))
    if "relative_strength" in enabled:
        signals.append(RelativeStrengthRotationStrategy(int(quant.get("lookback_days", 20))).evaluate(symbol, features, quant_context))
    if "volatility_target" in enabled:
        signals.append(VolatilityTargetStrategy(high_atr_ratio).evaluate(symbol, features, quant_context))
    if "drawdown_control" in enabled:
        signals.append(DrawdownControlStrategy(Decimal(str(quant.get("drawdown_stop", "0.08")))).evaluate(symbol, features, quant_context))
    external = external_context or ExternalStrategyContext()
    strategy_options = profile.get("external") or {}
    if "futures_position_sentiment" in enabled:
        signals.append(FuturesPositionSentimentStrategy(strategy_options.get("futures_position_sentiment", {})).evaluate(symbol, features, external))
    if "overseas_market_sentiment" in enabled:
        signals.append(OverseasMarketSentimentStrategy(strategy_options.get("overseas_market_sentiment", {})).evaluate(symbol, features, external))
    if "lhb_follow_star_seats" in enabled:
        signals.append(LhbFollowStarSeatsStrategy(strategy_options.get("lhb_follow_star_seats", {})).evaluate(symbol, features, external))
    if "lhb_reverse_institutional" in enabled:
        signals.append(LhbReverseInstitutionalStrategy(strategy_options.get("lhb_reverse_institutional", {})).evaluate(symbol, features, external))
    if "lhb_seat_profile" in enabled:
        signals.append(LhbSeatProfileStrategy(strategy_options.get("lhb_seat_profile", {})).evaluate(symbol, features, external))
    if "lhb_consensus" in enabled:
        signals.append(LhbConsensusStrategy(strategy_options.get("lhb_consensus", {})).evaluate(symbol, features, external))
    if "lhb_quant_sector" in enabled:
        signals.append(LhbQuantSectorStrategy(strategy_options.get("lhb_quant_sector", {})).evaluate(symbol, features, external))
    return signals


def load_external_strategy_context(
    store: Any,
    symbol: str,
    quote=None,
    *,
    as_of: date | None = None,
) -> ExternalStrategyContext:
    """Load analysis-only external data. No external instrument may become a tradeable symbol."""
    as_of = as_of or date.today()
    futures = store.load_latest_futures_position() if hasattr(store, "load_latest_futures_position") else None
    if futures and not _is_recent_external_row(futures, as_of):
        futures = None
    overseas_rows = store.load_latest_overseas_data() if hasattr(store, "load_latest_overseas_data") else None
    if overseas_rows is not None:
        overseas_rows = [row for row in overseas_rows if _is_recent_external_row(row, as_of)]
    overseas = {str(row.get("symbol")): row for row in overseas_rows} if overseas_rows is not None else None
    lhb_rows = store.load_lhb_records() if hasattr(store, "load_lhb_records") else None
    if lhb_rows is not None:
        lhb_rows = [row for row in lhb_rows if _is_recent_external_row(row, as_of)]
    sector = store.load_instrument_sector(symbol) if hasattr(store, "load_instrument_sector") else None
    if lhb_rows is not None:
        for row in lhb_rows:
            row.setdefault("sector", store.load_instrument_sector(str(row.get("symbol"))) if hasattr(store, "load_instrument_sector") else None)
    auction_gap = None
    if quote is not None and quote.previous_close > 0:
        auction_gap = ((quote.open_price / quote.previous_close) - Decimal("1")) * Decimal("100")
    profiles = {}
    if lhb_rows is not None and hasattr(store, "load_seat_profile"):
        for row in lhb_rows:
            for side in ("buy", "sell"):
                for index in range(1, 6):
                    seat = row.get(f"{side}_seat_{index}")
                    if seat and seat not in profiles:
                        profile = store.load_seat_profile(str(seat))
                        if profile:
                            profiles[str(seat)] = profile
    quant_seats = {str(row["seat_name"]): row for row in store.load_quant_seats()} if hasattr(store, "load_quant_seats") else {}
    return ExternalStrategyContext(
        futures=futures,
        overseas=overseas,
        lhb_records=lhb_rows,
        sector=sector or "综合",
        auction_gap_pct=auction_gap,
        seat_profiles=profiles,
        quant_seats=quant_seats,
        sector_defaulted=not bool(sector),
    )


def _is_recent_external_row(row: dict[str, Any], as_of: date, max_age_days: int = 5) -> bool:
    """Allow at most one source-market session of stale daily evidence.

    ``exchange_calendars`` is optional at import time so local mock development
    remains lightweight. Production images include it; when unavailable we keep
    the older weekend-aware bound as a conservative compatibility fallback.
    """
    raw_date = row.get("trade_date")
    if not raw_date:
        return False
    try:
        source_date = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        return False
    if source_date > as_of:
        return False
    market = str(row.get("market") or "").upper()
    calendar_name = "XNYS" if market == "US" else "XKRX" if market in {"KR", "KOREA"} else "XSHG"
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar(calendar_name)
        cursor = source_date + timedelta(days=1)
        sessions_since = 0
        while cursor <= as_of and sessions_since <= 1:
            if calendar.is_session(cursor.isoformat()):
                sessions_since += 1
            cursor += timedelta(days=1)
        return sessions_since <= 1
    except Exception:  # noqa: BLE001 - optional dependency/calendar coverage fallback
        return (as_of - source_date).days <= max_age_days


def _unavailable_signal(strategy_id: str, symbol: str):
    """Fail closed until the corresponding persisted reference dataset is wired in."""
    from .models import Direction, StrategySignal

    return StrategySignal(
        strategy_id,
        symbol,
        Direction.WATCH,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        [],
        [f"{strategy_id} 数据集尚未同步，本轮策略失效。"],
        f"{strategy_id} 缺少有效数据，禁止该策略触发交易。",
    )
