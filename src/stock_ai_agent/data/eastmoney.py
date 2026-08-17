from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from ..models import Bar, Quote
from ..universe import normalize_symbol, validate_hs_symbol


class EastmoneyError(RuntimeError):
    pass


FIELDS = ",".join(
    [
        "f57",
        "f58",
        "f43",
        "f46",
        "f44",
        "f45",
        "f60",
        "f47",
        "f48",
        "f170",
        "f86",
        "f19",
        "f39",
    ]
)

KLINE_FIELDS1 = "f1,f2,f3,f4,f5,f6"
KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
KLINE_INTERVALS = {
    "daily": "101",
    "weekly": "102",
    "monthly": "103",
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
}
ADJUST_FLAGS = {
    "none": "0",
    "qfq": "1",
    "hfq": "2",
}
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def eastmoney_secid(symbol: str) -> str:
    normalized = validate_hs_symbol(symbol)
    code, exchange = normalized.split(".")
    market = "1" if exchange == "SH" else "0"
    return f"{market}.{code}"


def _strip_jsonp(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = re.search(r"\((\{.*\})\)\s*;?$", stripped, flags=re.S)
    if not match:
        raise EastmoneyError("东方财富响应格式无法解析")
    return match.group(1)


def _value(raw: Any, scale: Decimal = Decimal("1")) -> Decimal:
    if raw in (None, "-", ""):
        return Decimal("0")
    value = Decimal(str(raw))
    return value / scale


def _price(raw: Any) -> Decimal:
    value = _value(raw)
    if value.copy_abs() >= Decimal("1000"):
        return (value / Decimal("1000")).quantize(Decimal("0.001"))
    return value


def _timestamp(raw: Any, fetched_at: datetime) -> datetime:
    if raw in (None, "-", ""):
        return fetched_at
    text = str(raw)
    if text.isdigit() and len(text) == 10:
        return datetime.fromtimestamp(int(text), tz=MARKET_TIMEZONE)
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=MARKET_TIMEZONE)
        except ValueError:
            pass
    return fetched_at


def _kline_timestamp(raw: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise EastmoneyError(f"东方财富 K 线日期格式无法解析：{raw}")


def parse_quote_response(text: str, symbol: str, fetched_at: Optional[datetime] = None, freshness_seconds: int = 90) -> Quote:
    fetched = fetched_at or datetime.now(timezone.utc)
    payload = json.loads(_strip_jsonp(text))
    data = payload.get("data")
    if not data:
        raise EastmoneyError(f"东方财富没有返回 {symbol} 的行情数据")

    normalized = normalize_symbol(symbol)
    timestamp = _timestamp(data.get("f86"), fetched)
    return Quote(
        symbol=normalized,
        name=str(data.get("f58") or normalized),
        timestamp=timestamp,
        latest_price=_price(data.get("f43")),
        open_price=_price(data.get("f46")),
        high_price=_price(data.get("f44")),
        low_price=_price(data.get("f45")),
        previous_close=_price(data.get("f60")),
        volume=_value(data.get("f47")),
        amount=_value(data.get("f48")),
        change_percent=_value(data.get("f170"), Decimal("100") if isinstance(data.get("f170"), int) else Decimal("1")),
        source="eastmoney_public",
        fetched_at=fetched,
        freshness_seconds=freshness_seconds,
        bid_price=_price(data.get("f19")) if data.get("f19") not in (None, "-", "") else None,
        ask_price=_price(data.get("f39")) if data.get("f39") not in (None, "-", "") else None,
    )


def parse_kline_response(text: str, symbol: str) -> List[Bar]:
    payload = json.loads(_strip_jsonp(text))
    data = payload.get("data")
    if not data:
        raise EastmoneyError(f"东方财富没有返回 {symbol} 的历史 K 线数据")
    normalized = normalize_symbol(symbol)
    klines = data.get("klines") or []
    bars: List[Bar] = []
    for item in klines:
        parts = str(item).split(",")
        if len(parts) < 7:
            raise EastmoneyError(f"东方财富 K 线字段数量不足：{item}")
        bars.append(
            Bar(
                symbol=normalized,
                timestamp=_kline_timestamp(parts[0]),
                open_price=_value(parts[1]),
                close_price=_value(parts[2]),
                high_price=_value(parts[3]),
                low_price=_value(parts[4]),
                volume=_value(parts[5]),
                amount=_value(parts[6]),
            )
        )
    return bars


class EastmoneyPublicAdapter:
    endpoint = "https://push2.eastmoney.com/api/qt/stock/get"
    kline_endpoint = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, freshness_seconds: int = 90, timeout: float = 5.0) -> None:
        self.freshness_seconds = freshness_seconds
        self.timeout = timeout

    def get_quote(self, symbol: str) -> Quote:
        secid = eastmoney_secid(symbol)
        params = urllib.parse.urlencode({"secid": secid, "fields": FIELDS})
        url = f"{self.endpoint}?{params}"
        fetched_at = datetime.now(timezone.utc)
        text = self._request_text(url, "东方财富公开行情")
        return parse_quote_response(text, symbol=symbol, fetched_at=fetched_at, freshness_seconds=self.freshness_seconds)

    def get_daily_bars(
        self,
        symbol: str,
        start: str = "20240101",
        end: str = "20500101",
        adjust: str = "qfq",
    ) -> List[Bar]:
        return self.get_bars(symbol=symbol, interval="daily", start=start, end=end, adjust=adjust)

    def get_bars(
        self,
        symbol: str,
        interval: str = "daily",
        start: str = "20240101",
        end: str = "20500101",
        adjust: str = "qfq",
    ) -> List[Bar]:
        secid = eastmoney_secid(symbol)
        if interval not in KLINE_INTERVALS:
            raise EastmoneyError(f"不支持的东方财富 K 线周期：{interval}")
        if adjust not in ADJUST_FLAGS:
            raise EastmoneyError(f"不支持的复权方式：{adjust}")
        params = urllib.parse.urlencode(
            {
                "secid": secid,
                "fields1": KLINE_FIELDS1,
                "fields2": KLINE_FIELDS2,
                "klt": KLINE_INTERVALS[interval],
                "fqt": ADJUST_FLAGS[adjust],
                "beg": start,
                "end": end,
            }
        )
        url = f"{self.kline_endpoint}?{params}"
        text = self._request_text(url, "东方财富历史 K 线")
        return parse_kline_response(text, symbol)

    def _request_text(self, url: str, label: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Connection": "close",
            },
        )
        last_error: Exception | None = None
        for _ in range(2):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
        raise EastmoneyError(f"{label}请求失败：{last_error}") from last_error
