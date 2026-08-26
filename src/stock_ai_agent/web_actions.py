"""Web actions that mutate watchlists or backtest state."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any
from uuid import uuid4

from .config import AppConfig
from .universe import infer_asset_type, validate_hs_symbol
from .watchlist import add_watchlist_item, effective_watchlist, remove_watchlist_item, set_watchlist_trading_enabled
from .reference_data import sync_sector_mappings
from .risk_config import parse_risk_config, risk_config_payload
from .web_support import _DASHBOARD_CACHE, _to_jsonable
from .web_dashboard import build_dashboard_overview_payload
from .web_dashboard import build_dashboard_strategies_payload
from .strategy_runtime import LEGACY_STRATEGY_ID_ALIASES


def confirm_backtest_runs(config: AppConfig, store, run_ids: list[int]) -> dict[str, Any]:
    requested = {int(item) for item in run_ids}
    runs = store.load_backtest_runs(limit=None) if hasattr(store, "load_backtest_runs") else []
    selected = [item for item in runs if int(item.get("id", -1)) in requested]
    missing = requested - {int(item.get("id", -1)) for item in selected}
    if missing:
        raise ValueError("部分回测记录不存在或已被清理。")
    actionable = [item for item in selected if item.get("strategy_id") != "learning_review" and item.get("status") not in {"已应用", "已确认", "待下一轮生效"}]
    candidates_by_profile: dict[str, list[dict[str, Any]]] = {}
    for run in actionable:
        candidates_by_profile.setdefault(str(run.get("strategy_profile_id") or "default"), []).append(run)
    rejected_ids: list[int] = []
    selected_candidates: list[dict[str, Any]] = []
    for candidates in candidates_by_profile.values():
        winner = max(candidates, key=_backtest_rank)
        selected_candidates.append(winner)
        rejected_ids.extend(int(item["id"]) for item in candidates if item is not winner)
    queued_ids: list[int] = []
    reviewed_ids: list[int] = []
    drafts: list[tuple[dict[str, Any], dict[str, Any]]] = []
    center = store.load_strategy_center(config) if selected_candidates else {"profiles": []}
    profiles = {str(item.get("profile_id")): item for item in center.get("profiles", [])}
    for run in selected_candidates:
        run_id = int(run["id"])
        profile_id = str(run.get("strategy_profile_id") or "default")
        profile = profiles.get(profile_id)
        if not profile:
            raise ValueError(f"回测 {run_id} 关联的策略组合 {profile_id} 不存在。")
        if profile.get("pending_activation"):
            raise ValueError(f"策略组合 {profile_id} 已有待下一轮生效的变更，请先等待 monitor 应用。")
        drafts.append((profile, run))
    for profile, run in drafts:
        save_dashboard_strategy_profile(config, store, _backtest_profile_draft(profile, run))
        queued_ids.append(int(run["id"]))
    reviewed_ids.extend(
        int(item["id"])
        for item in selected
        if item.get("strategy_id") == "learning_review"
        and item.get("status") not in {"已应用", "已确认", "待下一轮生效"}
    )
    updated = 0
    if queued_ids and hasattr(store, "update_backtest_run_status"):
        updated += store.update_backtest_run_status(queued_ids, "待下一轮生效")
    if reviewed_ids and hasattr(store, "update_backtest_run_status"):
        updated += store.update_backtest_run_status(reviewed_ids, "已确认")
    if rejected_ids and hasattr(store, "update_backtest_run_status"):
        updated += store.update_backtest_run_status(rejected_ids, "已拒绝")
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable(
        {
            "updated": updated,
            "queued": len(queued_ids),
            "reviewed": len(reviewed_ids),
            "rejected": len(rejected_ids),
            "backtest_runs": store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else [],
        }
    )


def _backtest_rank(run: dict[str, Any]) -> tuple[Decimal, Decimal]:
    metrics = dict(run.get("metrics") or {})
    total_return = _backtest_metric(metrics.get("total_return"), Decimal("-999"))
    max_drawdown = _backtest_metric(metrics.get("max_drawdown"), Decimal("999"))
    win_rate = _backtest_metric(metrics.get("win_rate"), Decimal("0"))
    return total_return - max_drawdown, win_rate


def _backtest_metric(value: Any, fallback: Decimal) -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else fallback
    except (ArithmeticError, TypeError, ValueError):
        return fallback


def _backtest_profile_draft(profile: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Translate a confirmed optimizer candidate into a monitor-consumable draft."""
    draft = deepcopy(profile)
    strategy_id = str(run.get("strategy_id") or "")
    parameters = dict(run.get("parameters") or {})
    enabled = list(draft.get("enabled") or [])
    weights = {str(key): str(value) for key, value in dict(draft.get("weights") or {}).items()}
    quant = dict(draft.get("quant") or {})
    if strategy_id == "momentum_grid":
        if "time_series_momentum" not in enabled:
            enabled.append("time_series_momentum")
        weights.setdefault("time_series_momentum", "1")
        if "lookback_days" in parameters:
            quant["lookback_days"] = int(parameters["lookback_days"])
        if "threshold" in parameters:
            quant["momentum_threshold"] = str(parameters["threshold"])
        if "target_weight" in parameters:
            quant["momentum_target_weight"] = str(parameters["target_weight"])
    else:
        raise ValueError(f"暂不支持将 {strategy_id} 回测候选应用到策略组合。")
    draft.update({
        "profile_id": str(profile["profile_id"]),
        "enabled": enabled,
        "weights": weights,
        "quant": quant,
        "pending_activation": True,
        "pending_confirmation": False,
        "effective_monitor_round": "next",
        "source_backtest_id": int(run["id"]),
        "source_backtest_parameters": parameters,
    })
    return draft


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


def sync_dashboard_sectors(config: AppConfig, store, symbol: str | None = None) -> dict[str, Any]:
    symbols = [symbol] if symbol else None
    count = sync_sector_mappings(config, store, symbols=symbols)
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable({"synced_count": count, "sectors": store.load_sector_mappings(symbol=symbol) if hasattr(store, "load_sector_mappings") else []})


def save_dashboard_strategy_profile(config: AppConfig, store, payload: dict[str, Any]) -> dict[str, Any]:
    if not hasattr(store, "save_strategy_profile"):
        raise ValueError("当前存储适配器不支持策略持久化。")
    profile = dict(payload)
    profile_id = str(profile.get("profile_id") or "").strip()
    if not profile_id:
        profile_id = f"profile_{uuid4().hex[:12]}"
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
    result = build_dashboard_strategies_payload(config, store)
    result["saved_profile_id"] = profile_id
    return result


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
