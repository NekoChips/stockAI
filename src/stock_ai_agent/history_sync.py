from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .watchlist import effective_watchlist


@dataclass(frozen=True)
class HistorySyncResult:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    attempted: int = 0

    @property
    def synced_count(self) -> int:
        return sum(1 for value in self.counts.values() if value > 0)


def compact_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


def date_code(value: date) -> str:
    return value.strftime("%Y%m%d")


def previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def missing_history_range(
    store: Any,
    symbol: str,
    interval: str,
    configured_start: str,
    configured_end: str,
    as_of: date | None = None,
    loader: Any | None = None,
) -> tuple[str, str] | None:
    """Return the inclusive missing K-line range, or None when storage is current."""
    end_date = min(compact_date(configured_end), as_of or date.today())
    load_history = loader or store.load_watchlist_bars
    recent = load_history(symbol, interval=interval, limit=1)
    start_date = compact_date(configured_start)
    if recent:
        start_date = max(start_date, recent[-1].timestamp.date() + timedelta(days=1))
    if start_date > end_date:
        return None
    return date_code(start_date), date_code(end_date)


def sync_watchlist_history(
    config: Any,
    store: Any,
    adapter: Any,
    *,
    as_of: date | None = None,
    force: bool = False,
    only_incomplete: bool = False,
) -> HistorySyncResult:
    """Synchronize the effective watchlist through one shared history path."""
    history = config.data.history
    interval = str(history.get("interval", "daily"))
    start = str(history.get("start", "20240101"))
    end = str(history.get("end", "20500101"))
    adjust = str(history.get("adjust", "qfq"))
    minimum = int(history.get("monitor_minimum_bars", 35))
    report_date = as_of or date.today()
    instruments = effective_watchlist(config, store)
    candidates = [
        instrument
        for instrument in instruments
        if force or not only_incomplete or len(store.load_watchlist_bars(instrument.symbol, interval=interval, limit=minimum)) < minimum
    ]
    counts: dict[str, int] = {}
    warnings: list[str] = []
    started_at = datetime.now()
    for instrument in candidates:
        try:
            existing = store.load_watchlist_bars(instrument.symbol, interval=interval, limit=minimum)
            if not force and len(existing) < minimum:
                range_to_sync = (start, min(date_code(report_date), end))
            else:
                range_to_sync = missing_history_range(store, instrument.symbol, interval, start, end, as_of)
            if range_to_sync is None:
                counts[instrument.symbol] = 0
                continue
            sync_start, sync_end = range_to_sync
            qfq_bars = adapter.get_bars(instrument.symbol, interval=interval, start=sync_start, end=sync_end, adjust=adjust)
            # AlphaFeed requires an explicit `none`; an empty value becomes
            # `adjust=` and is rejected with HTTP 400.
            raw_bars = adapter.get_bars(instrument.symbol, interval=interval, start=sync_start, end=sync_end, adjust="none")
            source = getattr(adapter, "last_source", "") or config.data.history_provider
            if hasattr(store, "save_watchlist_price_tracks"):
                counts[instrument.symbol] = store.save_watchlist_price_tracks(raw_bars, qfq_bars, interval=interval, source=source)
            else:
                raise ValueError("当前存储适配器不支持观察池价格轨迹。")
        except Exception as exc:  # noqa: BLE001 - isolate one provider failure per symbol
            counts[instrument.symbol] = 0
            warnings.append(f"{instrument.symbol} 历史 K 线同步失败：{exc}")
    if hasattr(store, "save_data_task_status"):
        finished_at = datetime.now()
        store.save_data_task_status(
            "watchlist_history",
            report_date,
            "success" if not warnings else "degraded",
            sum(1 for value in counts.values() if value > 0),
            len(warnings),
            "；".join(warnings) or ("无缺失历史数据。" if not candidates else ""),
            started_at,
            finished_at,
        )
    return HistorySyncResult(counts, warnings, len(candidates))
