"""Web actions that mutate watchlists or backtest state."""

from __future__ import annotations

from typing import Any

from .config import AppConfig
from .universe import infer_asset_type, validate_hs_symbol
from .watchlist import add_watchlist_item, effective_watchlist, remove_watchlist_item, set_watchlist_trading_enabled
from .risk_config import parse_risk_config, risk_config_payload
from .web_support import _DASHBOARD_CACHE, _to_jsonable
from .web_dashboard import build_dashboard_overview_payload
from .web_dashboard import build_dashboard_strategies_payload
from .strategy_runtime import LEGACY_STRATEGY_ID_ALIASES


def confirm_backtest_runs(config: AppConfig, store, run_ids: list[int]) -> dict[str, Any]:
    updated = store.update_backtest_run_status(run_ids, "已确认") if hasattr(store, "update_backtest_run_status") else 0
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable(
        {
            "updated": updated,
            "backtest_runs": store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else [],
        }
    )


def run_dashboard_backtest(config: AppConfig, store) -> dict[str, Any]:
    from .app import optimize_strategy_from_store

    optimize_strategy_from_store(config, store)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable({"backtest_runs": store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else []})


def discard_dashboard_strategy_draft(config: AppConfig, store, profile_id: str) -> dict[str, Any]:
    del config
    if not hasattr(store, "discard_strategy_draft"):
        raise ValueError("当前存储适配器不支持撤销策略草稿。")
    store.discard_strategy_draft(profile_id)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return {"discarded": profile_id}


def search_watchlist_instruments(config: AppConfig, store, query: str, provider=None, limit: int = 12) -> list[dict[str, str]]:
    text = str(query).strip().upper()
    if len(text) < 2:
        return []
    catalog_matches = store.search_instrument_catalog(text, limit=limit) if hasattr(store, "search_instrument_catalog") else []
    if catalog_matches:
        return catalog_matches
    direct_code = text.split(".", 1)[0]
    if direct_code.isdigit() and len(direct_code) == 6 and text in {direct_code, f"{direct_code}.SH", f"{direct_code}.SZ"}:
        try:
            symbol = validate_hs_symbol(text)
            return [{"symbol": symbol, "name": "名称待目录同步", "asset_type": infer_asset_type(symbol)}]
        except ValueError:
            return []
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in effective_watchlist(config, store):
        if text not in item.symbol and text not in item.name.upper():
            continue
        results.append({"symbol": item.symbol, "name": item.name, "asset_type": item.asset_type})
        seen.add(item.symbol)
    if results:
        return results[:limit]
    if provider is not None and hasattr(provider, "search_instruments"):
        for item in provider.search_instruments(text, limit=limit):
            symbol = str(item.get("symbol") or "")
            if not symbol or symbol in seen:
                continue
            results.append({
                "symbol": symbol,
                "name": str(item.get("name") or symbol),
                "asset_type": str(item.get("asset_type") or "stock"),
            })
            seen.add(symbol)
            if len(results) >= limit:
                break
    return results[:limit]


def add_dashboard_watchlist_item(config: AppConfig, store, payload: dict[str, Any]) -> dict[str, Any]:
    item = add_watchlist_item(
        config,
        store,
        str(payload.get("symbol") or ""),
        str(payload.get("name") or ""),
        str(payload.get("asset_type") or "") or None,
    )
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable({"item": item, "dashboard": build_dashboard_overview_payload(config, store)})


def remove_dashboard_watchlist_item(config: AppConfig, store, symbol: str) -> dict[str, Any]:
    removed = remove_watchlist_item(config, store, symbol)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    overview = build_dashboard_overview_payload(config, store)
    return _to_jsonable({"removed": removed, "watchlist": overview["watchlist"], "dashboard": overview})


def set_dashboard_watchlist_trading(config: AppConfig, store, symbol: str, enabled: bool) -> dict[str, Any]:
    updated = set_watchlist_trading_enabled(config, store, symbol, enabled)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable({"updated": updated, "enabled": bool(enabled), "dashboard": build_dashboard_overview_payload(config, store)})


def save_dashboard_strategy_profile(config: AppConfig, store, payload: dict[str, Any]) -> dict[str, Any]:
    if not hasattr(store, "save_strategy_profile"):
        raise ValueError("当前存储适配器不支持策略持久化。")
    profile = dict(payload)
    profile_id = str(profile.get("profile_id") or profile.get("scope_value") or "").strip()
    if not profile_id:
        raise ValueError("策略组合必须提供 profile_id。")
    enabled = [LEGACY_STRATEGY_ID_ALIASES.get(str(item), str(item)) for item in profile.get("enabled", []) if str(item)]
    weights = {LEGACY_STRATEGY_ID_ALIASES.get(str(key), str(key)): str(value) for key, value in dict(profile.get("weights") or {}).items()}
    for value in weights.values():
        try:
            if float(value) < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("策略权重必须是非负数字。") from exc
    enabled_weights = [float(weights[item]) for item in enabled if item in weights]
    if not enabled:
        raise ValueError("至少启用一个策略。")
    if len(enabled_weights) != len(enabled) or sum(enabled_weights) <= 0:
        raise ValueError("每个已启用策略都必须配置正权重，权重合计必须大于 0。")
    aggregator = dict(profile.get("aggregator") or {})
    for key in ("buy_score_threshold", "exit_score_threshold"):
        if key in aggregator:
            try:
                if not -1 <= float(aggregator[key]) <= 1:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError("策略聚合阈值必须在 -1 到 1 之间。") from exc
    profile.update({
        "profile_id": profile_id,
        "config_schema_version": 2,
        "enabled": enabled,
        "weights": weights,
        "technical": dict(profile.get("technical") or {}),
        "quant": dict(profile.get("quant") or {}),
        "external": dict(profile.get("external") or {}),
        "aggregator": aggregator,
    })
    store.ensure_strategy_defaults(config) if hasattr(store, "ensure_strategy_defaults") else None
    store.save_strategy_profile(profile)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return build_dashboard_strategies_payload(config, store)


def confirm_dashboard_strategy_profile(config: AppConfig, store, profile_id: str) -> dict[str, Any]:
    if not hasattr(store, "confirm_strategy_profile"):
        raise ValueError("当前存储适配器不支持策略持久化。")
    store.confirm_strategy_profile(profile_id)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return build_dashboard_strategies_payload(config, store)


def save_dashboard_risk_config(config: AppConfig, store, payload: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_risk_config(config.risk, payload)
    draft = risk_config_payload(parsed, status="draft", pending_confirmation=True)
    if not hasattr(store, "save_risk_config_draft"):
        raise ValueError("当前存储适配器不支持风险配置持久化。")
    store.save_risk_config_draft(draft)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return {"risk_config": draft}


def confirm_dashboard_risk_config(config: AppConfig, store) -> dict[str, Any]:
    del config
    if not hasattr(store, "confirm_risk_config"):
        raise ValueError("当前存储适配器不支持风险配置持久化。")
    active = store.confirm_risk_config()
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return {"risk_config": active}
