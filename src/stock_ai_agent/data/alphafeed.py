from __future__ import annotations

import os
import time
from threading import Lock
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from ..models import Bar, ExternalDailyBar, Quote
from ..universe import normalize_symbol, validate_hs_symbol


class AlphaFeedError(RuntimeError):
    """Raised when the AlphaFeed SDK cannot provide usable data."""

    rate_limited = False


class AlphaFeedRateLimitError(AlphaFeedError):
    rate_limited = True

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
PERIODS = {"daily": "1d", "weekly": "1w", "monthly": "1M"}
ADJUSTS = {"none": "none", "qfq": "forward", "hfq": "backward"}
_GLOBAL_RATE_LOCK = Lock()
_GLOBAL_RATE_STATE: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW_SECONDS = 60.0
SAFE_QUOTE_REQUESTS_PER_MINUTE = 10
SAFE_KLINE_REQUESTS_PER_MINUTE = 10
MAX_QUOTE_SYMBOLS_PER_REQUEST = 5
MAX_HISTORY_COUNT = 10000


def _decimal(value: Any) -> Decimal:
    if value in (None, "", "-", "--"):
        return Decimal("0")
    return Decimal(str(value).replace(",", ""))


def _records(table: Any) -> List[Dict[str, Any]]:
    if isinstance(table, dict):
        return [dict(table)]
    if isinstance(table, list):
        return [dict(item) for item in table]
    if hasattr(table, "to_dict"):
        return [dict(item) for item in table.to_dict(orient="records")]
    raise AlphaFeedError("AlphaFeed 返回的数据表无法解析")


def _get(record: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return default


def _timestamp(value: Any, fallback: datetime) -> datetime:
    if value in (None, "", "-", "--"):
        return fallback
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=MARKET_TIMEZONE)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return fallback
    return parsed.replace(tzinfo=MARKET_TIMEZONE) if parsed.tzinfo is None else parsed


def _date(value: Any) -> date | None:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _percent(value: Any) -> Decimal:
    result = _decimal(value)
    return result * Decimal("100") if result.copy_abs() <= Decimal("1") else result


def _required_decimal(record: Dict[str, Any], label: str, *keys: str) -> Decimal:
    raw = _get(record, *keys)
    if raw in (None, "", "-", "--"):
        raise AlphaFeedError(f"AlphaFeed 返回缺少关键字段：{label}")
    value = _decimal(raw)
    if value <= 0:
        raise AlphaFeedError(f"AlphaFeed 返回关键字段无效：{label}={value}")
    return value


def _date_timestamp(value: str, end_of_day: bool = False) -> int:
    parsed = _date(value)
    if parsed is None:
        raise AlphaFeedError(f"日期格式无法解析：{value}")
    hour = 23 if end_of_day else 0
    dt = datetime(parsed.year, parsed.month, parsed.day, hour, 59 if end_of_day else 0, 59 if end_of_day else 0, tzinfo=MARKET_TIMEZONE)
    return int(dt.timestamp() * 1000)


def _is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(token in text for token in ("429", "rate limit", "rate_limit", "quota", "too many", "限流", "频率"))


def _retry_after_seconds(exc: Exception) -> float | None:
    value = getattr(exc, "retry_after", None)
    if value is None:
        headers = getattr(getattr(exc, "response", None), "headers", None) or getattr(exc, "headers", None) or {}
        value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _frame_bars(table: Any, symbol: str, start: str, end: str) -> List[Bar]:
    normalized = validate_hs_symbol(symbol)
    start_date = _date(start)
    end_date = _date(end)
    bars: List[Bar] = []
    for record in _records(table):
        trade_date = _date(_get(record, "trade_date", "trade_date_time", "date", "日期", "时间"))
        if trade_date is None or (start_date and trade_date < start_date) or (end_date and trade_date > end_date):
            continue
        bars.append(
            Bar(
                symbol=normalized,
                timestamp=datetime.combine(trade_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE),
                open_price=_required_decimal(record, "open", "open", "开盘", "o"),
                high_price=_required_decimal(record, "high", "high", "最高", "h"),
                low_price=_required_decimal(record, "low", "low", "最低", "l"),
                close_price=_required_decimal(record, "close", "close", "收盘", "c"),
                volume=_decimal(_get(record, "volume", "成交量", "v")),
                amount=_decimal(_get(record, "amount", "成交额", "a")),
            )
        )
    return bars


def _frame_external_daily_bars(table: Any, source_symbol: str, start: str, end: str) -> List[ExternalDailyBar]:
    start_date = _date(start)
    end_date = _date(end)
    bars: List[ExternalDailyBar] = []
    for record in _records(table):
        trade_date = _date(_get(record, "trade_date", "trade_date_time", "date", "日期", "时间"))
        if trade_date is None or (start_date and trade_date < start_date) or (end_date and trade_date > end_date):
            continue
        bars.append(
            ExternalDailyBar(
                source_symbol=source_symbol,
                trade_date=datetime.combine(trade_date, datetime.min.time(), tzinfo=timezone.utc),
                close_price=_required_decimal(record, "close", "close", "收盘", "c"),
            )
        )
    return sorted(bars, key=lambda item: item.trade_date)


def _frame_quote(table: Any, symbol: str, fetched_at: datetime, freshness_seconds: int) -> Quote:
    normalized = validate_hs_symbol(symbol)
    records = _records(table)
    code = normalized.split(".", 1)[0]
    record = next(
        (
            item
            for item in records
            if normalize_symbol(str(_get(item, "symbol", "代码", "code", default=""))) == normalized
            or str(_get(item, "symbol", "代码", "code", default="")).strip() == code
        ),
        None,
    )
    if record is None:
        raise AlphaFeedError(f"AlphaFeed 实时行情中没有找到标的：{normalized}")
    latest_price = _required_decimal(record, "last_price", "last_price", "price", "最新价")
    previous_close = _required_decimal(record, "prev_close", "prev_close", "previous_close", "昨收")
    return Quote(
        symbol=normalized,
        name=str(_get(record, "ext.name", "name", "名称", default=normalized)),
        timestamp=_timestamp(_get(record, "trade_time", "timestamp", "time", "更新时间"), fetched_at),
        latest_price=latest_price,
        open_price=_required_decimal(record, "open", "open", "开盘", "open_price"),
        high_price=_required_decimal(record, "high", "high", "最高", "high_price"),
        low_price=_required_decimal(record, "low", "low", "最低", "low_price"),
        previous_close=previous_close,
        volume=_decimal(_get(record, "volume", "成交量")),
        amount=_decimal(_get(record, "amount", "成交额")),
        change_percent=_percent(_get(record, "ext.change_pct", "change_pct", "涨跌幅")),
        source="alphafeed",
        fetched_at=fetched_at,
        freshness_seconds=freshness_seconds,
        bid_price=_decimal(_get(record, "bid_price", "买一价")) or None,
        ask_price=_decimal(_get(record, "ask_price", "卖一价")) or None,
    )


class AlphaFeedAdapter:
    """AlphaFeed SDK adapter with batching and a conservative request throttle."""

    def __init__(
        self,
        options: Dict[str, object] | None = None,
        freshness_seconds: int = 90,
        client: Any = None,
        api_key: str | None = None,
        sdk_importer: Callable[[], Any] | None = None,
        min_request_interval_seconds: float | None = None,
        quote_cache_seconds: float | None = None,
        history_count: int | None = None,
        quote_max_symbols_per_request: int | None = None,
        quote_max_requests_per_minute: int | None = None,
        kline_max_symbols_per_request: int | None = None,
        kline_max_requests_per_minute: int | None = None,
        quote_request_interval_seconds: float | None = None,
        kline_request_interval_seconds: float | None = None,
        monotonic_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.options = options or {}
        self.freshness_seconds = freshness_seconds
        self.client = client
        self.api_key = api_key if api_key is not None else str(self.options.get("api_key") or os.environ.get(str(self.options.get("api_key_env") or "ALPHAFEED_API_KEY"), ""))
        self.sdk_importer = sdk_importer
        self.quote_cache_seconds = max(
            0.0,
            float(quote_cache_seconds if quote_cache_seconds is not None else self.options.get("quote_cache_seconds", 3)),
        )
        configured_history_count = int(
            history_count if history_count is not None else self.options.get("history_count", MAX_HISTORY_COUNT)
        )
        # AlphaFeed defaults to 100 rows when count is omitted. Always use an
        # explicit bounded count for long historical backfills.
        self.history_count = min(MAX_HISTORY_COUNT, max(0, configured_history_count))
        self.quote_max_symbols_per_request = min(
            MAX_QUOTE_SYMBOLS_PER_REQUEST,
            max(
                1,
                int(
                    quote_max_symbols_per_request
                    if quote_max_symbols_per_request is not None
                    else self.options.get("quote_max_symbols_per_request", 5)
                ),
            ),
        )
        self.quote_max_requests_per_minute = min(
            SAFE_QUOTE_REQUESTS_PER_MINUTE,
            max(
                1,
                int(
                    quote_max_requests_per_minute
                    if quote_max_requests_per_minute is not None
                    else self.options.get("quote_max_requests_per_minute", 8)
                ),
            ),
        )
        self.kline_max_symbols_per_request = 1
        self.kline_max_requests_per_minute = min(
            SAFE_KLINE_REQUESTS_PER_MINUTE,
            max(
                1,
                int(
                    kline_max_requests_per_minute
                    if kline_max_requests_per_minute is not None
                    else self.options.get("kline_max_requests_per_minute", 10)
                ),
            ),
        )
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        legacy_interval = min_request_interval_seconds if min_request_interval_seconds is not None else self.options.get("min_request_interval_seconds", 0)
        self.min_request_interval_seconds = max(0.0, float(legacy_interval))
        self.quote_request_interval_seconds = max(
            0.0,
            float(
                quote_request_interval_seconds
                if quote_request_interval_seconds is not None
                else self.options.get("quote_request_interval_seconds", legacy_interval)
            ),
        )
        self.kline_request_interval_seconds = max(
            0.0,
            float(
                kline_request_interval_seconds
                if kline_request_interval_seconds is not None
                else self.options.get("kline_request_interval_seconds", legacy_interval)
            ),
        )
        self._quote_cache: dict[str, tuple[float, Quote]] = {}
        self._rate_limit_key = self.api_key or f"client:{id(client)}"
        self.last_source = ""
        self.last_errors: dict[str, str] = {}

    def get_quote(self, symbol: str) -> Quote:
        return self.get_quotes([symbol])[validate_hs_symbol(symbol)]

    def get_quotes(self, symbols: Iterable[str]) -> Dict[str, Quote]:
        normalized = [validate_hs_symbol(symbol) for symbol in symbols]
        if not normalized:
            return {}
        cache_now = self.monotonic_fn()
        cached = {
            symbol: self._quote_cache[symbol][1]
            for symbol in normalized
            if self.quote_cache_seconds > 0
            and symbol in self._quote_cache
            and cache_now - self._quote_cache[symbol][0] <= self.quote_cache_seconds
        }
        missing = [symbol for symbol in normalized if symbol not in cached]
        if not missing:
            return cached
        client = self._client()
        try:
            quotes: Dict[str, Quote] = {}
            errors: dict[str, str] = {}
            for batch in _chunks(missing, self.quote_max_symbols_per_request):
                self._throttle("quote", self.quote_max_requests_per_minute)
                fetched_at = self.now_fn()
                table = client.quotes.get(symbols=batch, to_dataframe=True)
                for symbol in batch:
                    try:
                        quotes[symbol] = _frame_quote(table, symbol, fetched_at, self.freshness_seconds)
                    except Exception as exc:  # noqa: BLE001 - one bad row must not discard a valid batch
                        errors[symbol] = str(exc)
            self.last_errors = errors
            if not quotes and errors:
                raise AlphaFeedError("；".join(f"{symbol}: {message}" for symbol, message in errors.items()))
        except Exception as exc:  # noqa: BLE001 - SDK and provider errors vary by plan/network
            if _is_rate_limit_error(exc):
                raise AlphaFeedRateLimitError(f"AlphaFeed 实时行情触发调用频率限制：{exc}", _retry_after_seconds(exc)) from exc
            raise AlphaFeedError(f"AlphaFeed 实时行情请求失败：{exc}") from exc
        self.last_source = "alphafeed"
        cache_now = self.monotonic_fn()
        self._quote_cache.update({symbol: (cache_now, quote) for symbol, quote in quotes.items()})
        return {**cached, **quotes}

    def get_bars(self, symbol: str, interval: str = "daily", start: str = "20200101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        return self.get_bars_batch([symbol], interval, start, end, adjust)[validate_hs_symbol(symbol)]

    def get_bars_batch(self, symbols: Iterable[str], interval: str = "daily", start: str = "20200101", end: str = "20500101", adjust: str = "qfq") -> Dict[str, List[Bar]]:
        normalized = [validate_hs_symbol(symbol) for symbol in symbols]
        if not normalized:
            return {}
        period = PERIODS.get(interval, interval)
        # Keep compatibility with older callers that used an empty string for
        # raw prices, while always sending AlphaFeed a valid explicit value.
        adjustment = ADJUSTS.get(adjust or "none", adjust or "none")
        if self.kline_max_symbols_per_request != 1:
            raise AlphaFeedError("A 股日 K 线套餐要求每次请求仅包含 1 个标的")
        client = self._client()
        try:
            result: Dict[str, List[Bar]] = {}
            for symbol in normalized:
                self._throttle("daily_kline", self.kline_max_requests_per_minute)
                kline_kwargs = {
                    "period": period,
                    "start_time": _date_timestamp(start),
                    "end_time": _date_timestamp(end, end_of_day=True),
                    "adjust": adjustment,
                    "to_dataframe": True,
                }
                if self.history_count > 0:
                    # AlphaFeed defaults to 100 rows when count is omitted;
                    # keep the long-history request explicit and bounded.
                    kline_kwargs["count"] = self.history_count
                table = client.klines.get(symbol, **kline_kwargs)
                bars = _frame_bars(table, symbol, start, end)
                if not bars:
                    raise AlphaFeedError(f"AlphaFeed 日 K 线缺少标的：{symbol}")
                result[symbol] = bars
        except Exception as exc:  # noqa: BLE001 - SDK and provider errors vary by plan/network
            if isinstance(exc, AlphaFeedError):
                raise
            if _is_rate_limit_error(exc):
                raise AlphaFeedRateLimitError(f"AlphaFeed 历史 K 线触发调用频率限制：{exc}", _retry_after_seconds(exc)) from exc
            raise AlphaFeedError(f"AlphaFeed 历史 K 线请求失败：{exc}") from exc
        self.last_source = "alphafeed"
        return result

    def get_index_bars(self, symbol: str, akshare_symbol: str, start: str = "20200101", end: str = "20500101") -> List[Bar]:
        del akshare_symbol
        return self.get_bars(symbol, "daily", start, end, "none")

    def get_external_daily_bars(
        self,
        source_symbol: str,
        start: str,
        end: str,
        *,
        count: int | None = None,
    ) -> List[ExternalDailyBar]:
        clean_symbol = str(source_symbol).strip().upper()
        if not clean_symbol or clean_symbol.endswith((".SH", ".SZ")):
            raise AlphaFeedError(f"海外日 K 代码无效：{source_symbol}")
        client = self._client()
        try:
            self._throttle("daily_kline", self.kline_max_requests_per_minute)
            kline_kwargs = {
                "period": "1d",
                "start_time": _date_timestamp(start),
                "end_time": _date_timestamp(end, end_of_day=True),
                "adjust": "none",
                "to_dataframe": True,
            }
            if count or self.history_count > 0:
                kline_kwargs["count"] = int(count or self.history_count)
            table = client.klines.get(clean_symbol, **kline_kwargs)
            bars = _frame_external_daily_bars(table, clean_symbol, start, end)
            if not bars:
                raise AlphaFeedError(f"AlphaFeed 海外日 K 缺少标的：{clean_symbol}")
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, AlphaFeedError):
                raise
            if _is_rate_limit_error(exc):
                raise AlphaFeedRateLimitError(f"AlphaFeed 海外日 K 触发调用频率限制：{exc}", _retry_after_seconds(exc)) from exc
            raise AlphaFeedError(f"AlphaFeed 海外日 K 请求失败：{exc}") from exc
        self.last_source = "alphafeed"
        return bars

    def _throttle(self, endpoint: str, max_requests_per_minute: int) -> None:
        endpoint_interval = self.quote_request_interval_seconds if endpoint == "quote" else self.kline_request_interval_seconds
        interval = max(endpoint_interval, RATE_LIMIT_WINDOW_SECONDS / max_requests_per_minute)
        key = f"{self._rate_limit_key}:{endpoint}"
        with _GLOBAL_RATE_LOCK:
            now = self.monotonic_fn()
            timestamps = [
                timestamp
                for timestamp in _GLOBAL_RATE_STATE.get(key, [])
                if now - timestamp < RATE_LIMIT_WINDOW_SECONDS
            ]
            scheduled_at = max(now, timestamps[-1] + interval) if timestamps else now
            if len(timestamps) >= max_requests_per_minute:
                scheduled_at = max(scheduled_at, timestamps[0] + RATE_LIMIT_WINDOW_SECONDS)
            wait = scheduled_at - now
            if wait > 0:
                self.sleep_fn(wait)
            timestamps = [
                timestamp
                for timestamp in timestamps
                if scheduled_at - timestamp < RATE_LIMIT_WINDOW_SECONDS
            ]
            timestamps.append(scheduled_at)
            _GLOBAL_RATE_STATE[key] = timestamps

    def _client(self):
        if self.client is not None:
            return self.client
        if not self.api_key:
            raise AlphaFeedError("缺少 AlphaFeed API Key，请设置环境变量 ALPHAFEED_API_KEY")
        try:
            importer = self.sdk_importer or self._default_sdk_importer
            factory = importer()
            self.client = factory(api_key=self.api_key)
        except AlphaFeedError:
            raise
        except Exception as exc:  # noqa: BLE001 - import and SDK initialization errors vary
            raise AlphaFeedError(f"AlphaFeed SDK 初始化失败：{exc}") from exc
        return self.client

    @staticmethod
    def _default_sdk_importer():
        from alphafeed import AlphaFeed  # type: ignore

        return AlphaFeed


def _chunks(items: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]
