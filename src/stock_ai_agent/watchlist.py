from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .config import AppConfig, InstrumentConfig
from .universe import infer_asset_type, validate_hs_symbol


def _catalog_item(store: Any, symbol: str) -> dict[str, str] | None:
    if not hasattr(store, "search_instrument_catalog"):
        return None
    matches = store.search_instrument_catalog(symbol, limit=1)
    return matches[0] if matches else None


def effective_watchlist(config: AppConfig, store: Any) -> list[InstrumentConfig]:
    """Combine configured instruments with user-managed instruments persisted by the store."""
    items = list(config.universe)
    removed = store.load_removed_watchlist_symbols() if hasattr(store, "load_removed_watchlist_symbols") else set()
    items = [item for item in items if item.symbol not in removed]
    seen = {item.symbol for item in items}
    if not hasattr(store, "load_watchlist_items"):
        return items
    for row in store.load_watchlist_items():
        symbol = validate_hs_symbol(str(row["symbol"]), str(row.get("asset_type") or "") or None)
        if symbol in seen:
            continue
        if symbol in removed:
            continue
        catalog_item = _catalog_item(store, symbol)
        items.append(
            InstrumentConfig(
                symbol=symbol,
                asset_type=str(row.get("asset_type") or infer_asset_type(symbol)),
                name=str((catalog_item or {}).get("name") or row.get("name") or symbol),
                lifecycle_status=str(row.get("lifecycle_status") or "observing"),
                trading_enabled=bool(row.get("trading_enabled", 0)),
            )
        )
        seen.add(symbol)
    return items


def add_watchlist_item(
    config: AppConfig,
    store: Any,
    symbol: str,
    name: str = "",
    asset_type: str | None = None,
) -> InstrumentConfig:
    normalized = validate_hs_symbol(symbol, asset_type)
    exchange = normalized.rsplit(".", 1)[1]
    inferred_type = infer_asset_type(normalized)
    if asset_type and asset_type != inferred_type:
        raise ValueError(f"标的类型与证券代码不匹配：{normalized}")
    resolved_type = inferred_type
    if exchange not in config.allowed_exchanges:
        raise ValueError(f"不支持的市场：{exchange}")
    if resolved_type not in config.allowed_asset_types:
        raise ValueError(f"不支持的标的类型：{resolved_type}")
    catalog_item = _catalog_item(store, normalized)
    item = InstrumentConfig(
        normalized,
        resolved_type,
        name.strip() or str((catalog_item or {}).get("name") or normalized),
        lifecycle_status="observing",
        trading_enabled=False,
    )
    active_symbols = {row["symbol"] for row in store.load_watchlist_items()} if hasattr(store, "load_watchlist_items") else set()
    configured_symbols = {configured.symbol for configured in config.universe}
    removed_symbols = store.load_removed_watchlist_symbols() if hasattr(store, "load_removed_watchlist_symbols") else set()
    if normalized in (active_symbols | configured_symbols) and normalized not in removed_symbols:
        raise ValueError(f"标的 {normalized} 已在观察池中，不允许重复添加。")
    if hasattr(store, "restore_watchlist_item"):
        store.restore_watchlist_item(normalized)
    if normalized not in configured_symbols:
        if not hasattr(store, "add_watchlist_item"):
            raise ValueError("当前存储适配器不支持保存手动观察池")
        store.add_watchlist_item(item.symbol, item.name, item.asset_type)
    return item


def remove_watchlist_item(config: AppConfig, store: Any, symbol: str) -> str:
    normalized = validate_hs_symbol(symbol)
    portfolio = store.load_portfolio(config.paper_account.initial_cash)
    position = portfolio.positions.get(normalized)
    if position and position.quantity > 0:
        raise ValueError(f"标的 {normalized} 仍有持仓，不能移出观察池")
    if hasattr(store, "has_pending_orders") and store.has_pending_orders(normalized):
        raise ValueError(f"标的 {normalized} 存在未完成订单，不能移出观察池")
    if not hasattr(store, "remove_watchlist_item"):
        raise ValueError("当前存储适配器不支持移除观察池标的")
    store.remove_watchlist_item(normalized)
    return normalized


def set_watchlist_trading_enabled(config: AppConfig, store: Any, symbol: str, enabled: bool) -> str:
    normalized = validate_hs_symbol(symbol)
    if normalized in {item.symbol for item in config.universe}:
        raise ValueError("配置文件中的标的不能在页面直接切换交易权限，请通过配置草稿确认。")
    if not hasattr(store, "set_watchlist_trading_enabled"):
        raise ValueError("当前存储适配器不支持交易权限配置。")
    store.set_watchlist_trading_enabled(normalized, bool(enabled))
    return normalized


def watchlist_payload(config: AppConfig, store: Any) -> list[dict[str, str]]:
    configured = {item.symbol for item in config.universe}
    return [
        {**asdict(item), "source": "默认配置" if item.symbol in configured else "手动添加"}
        for item in effective_watchlist(config, store)
    ]
