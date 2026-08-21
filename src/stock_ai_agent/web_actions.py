"""Web actions that mutate watchlists or backtest state."""

from __future__ import annotations

from typing import Any

from .config import AppConfig
from .universe import infer_asset_type, validate_hs_symbol
from .watchlist import add_watchlist_item, effective_watchlist, remove_watchlist_item
from .web_support import _DASHBOARD_CACHE, _to_jsonable
from .web_dashboard import build_dashboard_overview_payload


def confirm_backtest_runs(config: AppConfig, store, run_ids: list[int]) -> dict[str, Any]:
    updated = store.update_backtest_run_status(run_ids, "已确认") if hasattr(store, "update_backtest_run_status") else 0
    _DASHBOARD_CACHE.invalidate_store(id(store))
    return _to_jsonable(
        {
            "updated": updated,
            "backtest_runs": store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else [],
        }
    )


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




