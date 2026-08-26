from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable

from .alphafeed import AlphaFeedError


_UNAVAILABLE_SOURCE_UNTIL: dict[str, date] = {}


@dataclass(frozen=True)
class ExternalMarketSpec:
    market: str
    canonical_symbol: str
    name: str
    source_symbols: tuple[str, ...]
    proxy_symbols: tuple[str, ...] = ()


DEFAULT_US_SPECS = tuple(
    ExternalMarketSpec("US", symbol, name, (f"{symbol}.US",))
    for symbol, name in (
        ("XLK", "信息技术 ETF"),
        ("XLV", "医药卫生 ETF"),
        ("XLF", "金融地产 ETF"),
        ("XLE", "能源 ETF"),
        ("XLI", "工业 ETF"),
        ("XLY", "可选消费 ETF"),
        ("XLP", "必需消费 ETF"),
        ("XLU", "公用事业 ETF"),
        ("XLB", "材料 ETF"),
        ("XLC", "电信服务 ETF"),
    )
) + (
    ExternalMarketSpec("US", "^IXIC", "纳斯达克", ("IXIC.US", "QQQ.US"), ("QQQ.US",)),
    ExternalMarketSpec("US", "^GSPC", "标普 500", ("GSPC.US", "SPY.US"), ("SPY.US",)),
    ExternalMarketSpec("US", "^DJI", "道琼斯", ("DJI.US", "DIA.US"), ("DIA.US",)),
)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _change_percent(previous: Decimal, current: Decimal) -> Decimal:
    return ((current / previous) - Decimal("1")) * Decimal("100")


def _cached_for_sync(row: dict, sync_date: date) -> bool:
    if str(row.get("data_status", "ready")) != "ready":
        return False
    fetched = _as_date(row.get("fetched_at"))
    return fetched == sync_date


def _looks_like_capability_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("not found", "unsupported", "不存在", "无效", "无权限", "权限不足"))


def _source_capability_unavailable(source_symbol: str, sync_date: date) -> bool:
    until = _UNAVAILABLE_SOURCE_UNTIL.get(source_symbol)
    if until is None:
        return False
    if sync_date > until:
        _UNAVAILABLE_SOURCE_UNTIL.pop(source_symbol, None)
        return False
    return True


def sync_external_market_data(
    store: Any,
    adapter: Any,
    specs: Iterable[ExternalMarketSpec] = DEFAULT_US_SPECS,
    *,
    as_of: date | None = None,
    fallback_fetcher: Callable[[ExternalMarketSpec], dict | None] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Synchronize analysis-only external daily data one source symbol at a time."""
    sync_date = as_of or date.today()
    now = now_fn or (lambda: datetime.now(timezone.utc))
    existing = {str(row.get("symbol")): row for row in store.load_latest_overseas_data(market="US")}
    successes = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    for spec in specs:
        if _cached_for_sync(existing.get(spec.canonical_symbol, {}), sync_date):
            skipped += 1
            continue
        row = None
        errors: list[str] = []
        for source_symbol in spec.source_symbols:
            if _source_capability_unavailable(source_symbol, sync_date):
                errors.append(f"{source_symbol}: 来源能力探测未通过，短期跳过")
                continue
            try:
                bars = adapter.get_external_daily_bars(
                    source_symbol,
                    (sync_date - timedelta(days=10)).strftime("%Y%m%d"),
                    sync_date.strftime("%Y%m%d"),
                    count=20,
                )
                if len(bars) < 2:
                    raise AlphaFeedError(f"{source_symbol} 有效日 K 不足两条")
                previous, current = bars[-2], bars[-1]
                if previous.close_price <= 0 or current.close_price <= 0:
                    raise AlphaFeedError(f"{source_symbol} 收盘价无效")
                row = {
                    "market": spec.market,
                    "symbol": spec.canonical_symbol,
                    "source_symbol": source_symbol,
                    "name": spec.name,
                    "trade_date": current.trade_date.date().isoformat(),
                    "prev_close": str(previous.close_price),
                    "close_price": str(current.close_price),
                    "change_pct": str(_change_percent(previous.close_price, current.close_price)),
                    "source": "alphafeed",
                    "is_proxy": source_symbol in spec.proxy_symbols,
                    "data_status": "ready",
                    "fetched_at": now().isoformat(),
                }
                break
            except Exception as exc:  # noqa: BLE001 - providers expose mixed exception types
                errors.append(f"{source_symbol}: {exc}")
                if _looks_like_capability_failure(exc):
                    _UNAVAILABLE_SOURCE_UNTIL[source_symbol] = sync_date + timedelta(days=5)
        if row is None and fallback_fetcher is not None:
            try:
                fallback = fallback_fetcher(spec)
                if fallback:
                    row = {
                        "market": spec.market,
                        "symbol": spec.canonical_symbol,
                        "source_symbol": str(fallback.get("source_symbol") or fallback.get("symbol") or spec.canonical_symbol),
                        "name": str(fallback.get("name") or spec.name),
                        "trade_date": str(fallback.get("trade_date") or sync_date.isoformat())[:10],
                        "prev_close": str(fallback["prev_close"]),
                        "close_price": str(fallback["close_price"]),
                        "change_pct": str(fallback["change_pct"]),
                        "source": str(fallback.get("source") or "fallback"),
                        "is_proxy": bool(fallback.get("is_proxy", False)),
                        "data_status": "ready",
                        "fetched_at": now().isoformat(),
                    }
            except Exception as exc:  # noqa: BLE001
                errors.append(f"fallback: {exc}")
        if row is None:
            failures.append({"symbol": spec.canonical_symbol, "reason": "；".join(errors) or "没有可用数据源"})
            continue
        store.save_overseas_market_data([row])
        successes += 1
    result = {"success_count": successes, "skipped_count": skipped, "failure_count": len(failures), "failures": failures}
    if hasattr(store, "save_data_task_status"):
        store.save_data_task_status(
            "external_us_daily",
            sync_date,
            "success" if not failures else "degraded",
            successes,
            len(failures),
            "；".join(item["reason"] for item in failures),
            now(),
            now(),
        )
    return result
