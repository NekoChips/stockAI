from __future__ import annotations

import os
import time
from threading import Lock
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from ..models import Bar, Quote
from ..universe import normalize_symbol, validate_hs_symbol


class AlphaFeedError(RuntimeError):
    """Raised when the AlphaFeed SDK cannot provide usable data."""

    rate_limited = False


class AlphaFeedRateLimitError(AlphaFeedError):
    rate_limited = True


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
PERIODS = {"daily": "1d", "weekly": "1w", "monthly": "1M"}
ADJUSTS = {"none": "none", "qfq": "forward", "hfq": "backward"}
_GLOBAL_RATE_LOCK = Lock()
_GLOBAL_RATE_STATE: dict[str, float] = {}


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
        monotonic_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.options = options or {}
        self.freshness_seconds = freshness_seconds
        self.client = client
        self.api_key = api_key if api_key is not None else str(self.options.get("api_key") or os.environ.get(str(self.options.get("api_key_env") or "ALPHAFEED_API_KEY"), ""))
        self.sdk_importer = sdk_importer
        self.min_request_interval_seconds = float(
            min_request_interval_seconds
            if min_request_interval_seconds is not None
            else self.options.get("min_request_interval_seconds", 3)
        )
        self.quote_cache_seconds = max(
            0.0,
            float(quote_cache_seconds if quote_cache_seconds is not None else self.options.get("quote_cache_seconds", 3)),
        )
        self.history_count = int(history_count if history_count is not None else self.options.get("history_count", 2000))
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._last_request_at: float | None = None
        self._quote_cache: dict[str, tuple[float, Quote]] = {}
        self._rate_limit_key = self.api_key or f"client:{id(client)}"
        self.last_source = ""

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
        self._throttle()
        fetched_at = self.now_fn()
        try:
            table = client.quotes.get(symbols=missing, to_dataframe=True)
            quotes = {symbol: _frame_quote(table, symbol, fetched_at, self.freshness_seconds) for symbol in missing}
        except Exception as exc:  # noqa: BLE001 - SDK and provider errors vary by plan/network
            if _is_rate_limit_error(exc):
                raise AlphaFeedRateLimitError(f"AlphaFeed 实时行情触发调用频率限制：{exc}") from exc
            raise AlphaFeedError(f"AlphaFeed 实时行情请求失败：{exc}") from exc
        self.last_source = "alphafeed"
        cache_now = self.monotonic_fn()
        self._quote_cache.update({symbol: (cache_now, quote) for symbol, quote in quotes.items()})
        return {**cached, **quotes}

    def get_bars(self, symbol: str, interval: str = "daily", start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        return self.get_bars_batch([symbol], interval, start, end, adjust)[validate_hs_symbol(symbol)]

    def get_bars_batch(self, symbols: Iterable[str], interval: str = "daily", start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> Dict[str, List[Bar]]:
        normalized = [validate_hs_symbol(symbol) for symbol in symbols]
        if not normalized:
            return {}
        period = PERIODS.get(interval, interval)
        adjustment = ADJUSTS.get(adjust, adjust)
        client = self._client()
        self._throttle()
        try:
            frames = client.klines.batch(
                normalized,
                period=period,
                count=self.history_count,
                start_time=_date_timestamp(start),
                end_time=_date_timestamp(end, end_of_day=True),
                adjust=adjustment,
                to_dataframe=True,
            )
            if not isinstance(frames, dict):
                raise AlphaFeedError("AlphaFeed 批量 K 线返回格式不是字典")
            result = {symbol: _frame_bars(frames[symbol], symbol, start, end) for symbol in normalized if symbol in frames}
            if any(not result.get(symbol) for symbol in normalized):
                missing = [symbol for symbol in normalized if not result.get(symbol)]
                raise AlphaFeedError(f"AlphaFeed 批量 K 线缺少标的：{','.join(missing)}")
        except Exception as exc:  # noqa: BLE001 - SDK and provider errors vary by plan/network
            if isinstance(exc, AlphaFeedError):
                raise
            if _is_rate_limit_error(exc):
                raise AlphaFeedRateLimitError(f"AlphaFeed 历史 K 线触发调用频率限制：{exc}") from exc
            raise AlphaFeedError(f"AlphaFeed 历史 K 线请求失败：{exc}") from exc
        self.last_source = "alphafeed"
        return result

    def get_index_bars(self, symbol: str, akshare_symbol: str, start: str = "20240101", end: str = "20500101") -> List[Bar]:
        del akshare_symbol
        return self.get_bars(symbol, "daily", start, end, "none")

    def _throttle(self) -> None:
        now = self.monotonic_fn()
        with _GLOBAL_RATE_LOCK:
            last_request_at = _GLOBAL_RATE_STATE.get(self._rate_limit_key)
            wait = 0.0 if last_request_at is None else self.min_request_interval_seconds - (now - last_request_at)
            if wait > 0:
                self.sleep_fn(wait)
                now += wait
            _GLOBAL_RATE_STATE[self._rate_limit_key] = now
            self._last_request_at = now

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
