from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .config import AppConfig
from .data.providers import create_history_data_provider, create_market_data_provider
from .history_sync import missing_history_range
from .universe import UniverseError, validate_hs_symbol
from .watchlist import effective_watchlist


SECTOR_KEYWORDS = {
    "科技": "信息技术",
    "信息": "信息技术",
    "芯片": "信息技术",
    "医药": "医药卫生",
    "医疗": "医药卫生",
    "金融": "金融地产",
    "地产": "金融地产",
    "能源": "能源",
    "工业": "工业",
    "消费": "可选消费",
    "食品": "必需消费",
    "材料": "材料",
    "公用": "公用事业",
    "通信": "电信服务",
}


class AKShareSectorAdapter:
    """Resolve a single A-share instrument's broad strategy sector."""

    def get_sector(self, symbol: str, name: str, asset_type: str) -> str | None:
        del asset_type
        for keyword, sector in SECTOR_KEYWORDS.items():
            if keyword in name:
                return sector
        try:
            import akshare as ak
            function = getattr(ak, "stock_individual_info_em", None)
            if function is None:
                return None
            frame = function(symbol=str(symbol).split(".", 1)[0])
            for _, row in frame.iterrows():
                if str(row.iloc[0]) in {"行业", "所属行业"}:
                    return str(row.iloc[1]) or None
        except Exception:  # noqa: BLE001 - source failure is a data-health event
            return None
        return None


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
        getattr(adapter, "last_source", "") or config.data.provider,
    )


def sync_benchmark_history(config: AppConfig, store: Any, adapter=None, as_of: date | None = None) -> dict[str, int]:
    adapter = adapter or create_history_data_provider(config)
    if not hasattr(adapter, "get_index_bars"):
        raise ValueError("当前历史数据源暂不支持指数历史 K 线同步。")
    history_config = config.data.history
    configured_start = str(history_config.get("start", "20240101"))
    configured_end = str(history_config.get("end", "20500101"))
    counts: dict[str, int] = {}
    errors: list[str] = []
    started_at = datetime.now()
    for benchmark in config.benchmarks:
        try:
            range_to_sync = missing_history_range(
                store,
                benchmark.symbol,
                "daily",
                configured_start,
                configured_end,
                as_of,
                loader=store.load_index_bars,
            )
            if range_to_sync is None:
                counts[benchmark.symbol] = 0
                continue
            start, end = range_to_sync
            bars = adapter.get_index_bars(benchmark.symbol, benchmark.akshare_symbol, start=start, end=end)
            source = getattr(adapter, "last_source", "") or config.data.history_provider
            counts[benchmark.symbol] = store.save_index_price_tracks(
                bars,
                interval="daily",
                source=f"{source}_benchmark",
            )
        except Exception as exc:  # noqa: BLE001 - isolate one benchmark failure
            counts[benchmark.symbol] = 0
            errors.append(f"{benchmark.symbol}：{exc}")
    if hasattr(store, "save_data_task_status"):
        report_date = as_of or date.today()
        finished_at = datetime.now()
        store.save_data_task_status(
            "benchmark_history",
            report_date,
            "success" if not errors else "degraded",
            sum(1 for value in counts.values() if value > 0),
            len(errors),
            "；".join(errors),
            started_at,
            finished_at,
        )
    return counts


def sync_sector_mappings(
    config: AppConfig,
    store: Any,
    adapter=None,
    symbols: list[str] | None = None,
    as_of: date | None = None,
) -> int:
    adapter = adapter or AKShareSectorAdapter()
    items = [
        {"symbol": item.symbol, "name": item.name, "asset_type": item.asset_type}
        for item in effective_watchlist(config, store)
    ]
    allowed = set(symbols or [])
    count = 0
    for item in items:
        symbol = str(item["symbol"])
        if allowed and symbol not in allowed:
            continue
        sector = adapter.get_sector(symbol, str(item.get("name") or symbol), str(item.get("asset_type") or ""))
        if not sector:
            continue
        store.save_sector_mapping(symbol, sector, source=getattr(adapter, "last_source", "akshare") or "akshare")
        count += 1
    if hasattr(store, "save_data_task_status"):
        now = as_of or date.today()
        store.save_data_task_status("sector_mapping", now, "success" if count else "degraded", count, max(0, len(items) - count), "未找到板块映射的标的使用综合板块。", datetime.now(), datetime.now())
    return count
