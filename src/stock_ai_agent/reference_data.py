from __future__ import annotations

from datetime import date
from typing import Any

from .config import AppConfig
from .data.providers import create_history_data_provider, create_market_data_provider
from .universe import UniverseError, validate_hs_symbol


def sync_instrument_catalog(
    config: AppConfig,
    store: Any,
    adapter=None,
    synced_date: str | None = None,
) -> int:
    adapter = adapter or create_market_data_provider(config)
    if not hasattr(adapter, "list_instruments"):
        raise ValueError("当前行情源不支持同步全量证券目录。")
    items = []
    for item in adapter.list_instruments():
        try:
            symbol = validate_hs_symbol(str(item["symbol"]), str(item.get("asset_type") or "") or None)
        except UniverseError:
            continue
        asset_type = str(item.get("asset_type") or "")
        if asset_type not in config.allowed_asset_types:
            continue
        items.append({"symbol": symbol, "name": str(item.get("name") or symbol), "asset_type": asset_type})
    if not items:
        raise ValueError("行情源未返回可用的沪深股票或 ETF 目录。")
    if not hasattr(store, "replace_instrument_catalog"):
        raise ValueError("当前存储适配器不支持证券目录。")
    return store.replace_instrument_catalog(
        items,
        synced_date or date.today().isoformat(),
        config.data.provider,
    )


def sync_benchmark_history(config: AppConfig, store: Any, adapter=None) -> dict[str, int]:
    adapter = adapter or create_history_data_provider(config)
    if not hasattr(adapter, "get_index_bars"):
        raise ValueError("当前历史数据源暂不支持指数历史 K 线同步。")
    history_config = config.data.history
    start = str(history_config.get("start", "20240101"))
    end = str(history_config.get("end", "20500101"))
    counts: dict[str, int] = {}
    for benchmark in config.benchmarks:
        bars = adapter.get_index_bars(benchmark.symbol, benchmark.akshare_symbol, start=start, end=end)
        counts[benchmark.symbol] = store.save_bars(
            bars,
            interval="daily",
            source=f"{config.data.history_provider}_benchmark",
        )
    return counts
