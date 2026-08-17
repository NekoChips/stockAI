from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..models import Bar, Quote
from ..universe import infer_asset_type, normalize_symbol


class BiyingAPIError(RuntimeError):
    pass


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
INTERVALS = {"daily": "d", "weekly": "w", "monthly": "m", "1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60"}
ADJUSTS = {"none": "n", "qfq": "f", "hfq": "b"}


def _decimal(value: Any) -> Decimal:
    if value in (None, "", "-"):
        return Decimal("0")
    return Decimal(str(value))


def _payload(text: str) -> Any:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BiyingAPIError("必盈 API 响应不是合法 JSON") from exc
    if isinstance(data, dict) and data.get("code") not in (None, 0, "0") and "data" in data:
        raise BiyingAPIError(f"必盈 API 返回错误：{data}")
    if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        return data["data"]
    return data


def _first_record(data: Any) -> Dict[str, Any]:
    if isinstance(data, list):
        if not data:
            raise BiyingAPIError("必盈 API 返回空列表")
        data = data[0]
    if not isinstance(data, dict):
        raise BiyingAPIError("必盈 API 响应结构无法解析")
    return data


def _timestamp(raw: Any, fetched_at: datetime) -> datetime:
    if raw in (None, "", "-"):
        return fetched_at
    text = str(raw).strip()
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d%H:%M", "%Y-%m-%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=MARKET_TIMEZONE)
        except ValueError:
            pass
    return fetched_at


def _previous_close(record: Dict[str, Any]) -> Decimal:
    if "yc" in record:
        return _decimal(record["yc"])
    price = _decimal(record.get("p"))
    change_percent = _decimal(record.get("pc"))
    denominator = Decimal("1") + change_percent / Decimal("100")
    if price > 0 and denominator != 0:
        return price / denominator
    return Decimal("0")


def parse_quote_response(text: str, symbol: str, fetched_at: Optional[datetime] = None, freshness_seconds: int = 90) -> Quote:
    fetched = fetched_at or datetime.now(timezone.utc)
    record = _first_record(_payload(text))
    normalized = normalize_symbol(symbol)
    timestamp = _timestamp(record.get("t"), fetched)
    return Quote(
        symbol=normalized,
        name=str(record.get("name") or normalized),
        timestamp=timestamp,
        latest_price=_decimal(record.get("p")),
        open_price=_decimal(record.get("o")),
        high_price=_decimal(record.get("h")),
        low_price=_decimal(record.get("l")),
        previous_close=_previous_close(record),
        volume=_decimal(record.get("v", record.get("tv", 0))),
        amount=_decimal(record.get("cje", record.get("a", 0))),
        change_percent=_decimal(record.get("pc")),
        source="biying_api",
        fetched_at=fetched,
        freshness_seconds=freshness_seconds,
    )


def parse_bars_response(text: str, symbol: str) -> List[Bar]:
    data = _payload(text)
    if not isinstance(data, list):
        raise BiyingAPIError("必盈历史 K 线响应不是列表")
    normalized = normalize_symbol(symbol)
    bars: List[Bar] = []
    for record in data:
        if not isinstance(record, dict):
            raise BiyingAPIError("必盈历史 K 线记录无法解析")
        bars.append(
            Bar(
                symbol=normalized,
                timestamp=_timestamp(record.get("t"), datetime.now(timezone.utc)),
                open_price=_decimal(record.get("o")),
                high_price=_decimal(record.get("h")),
                low_price=_decimal(record.get("l")),
                close_price=_decimal(record.get("c")),
                volume=_decimal(record.get("v")),
                amount=_decimal(record.get("a")),
            )
        )
    return bars


class BiyingAPIAdapter:
    def __init__(self, options: Dict[str, object] | None = None, freshness_seconds: int = 90, timeout: float = 10.0) -> None:
        options = options or {}
        licence = str(options.get("licence") or "").strip()
        licence_env = str(options.get("licence_env") or "BIYING_API_LICENCE")
        self.licence = licence or os.environ.get(licence_env, "")
        self.licence_env = licence_env
        self.base_url = str(options.get("base_url") or "https://api.biyingapi.com").rstrip("/")
        self.history_base_url = str(options.get("history_base_url") or self.base_url).rstrip("/")
        self.stock_realtime_path = str(options.get("stock_realtime_path") or "/hsstock/real/time/{code}/{licence}")
        self.fund_realtime_path = str(options.get("fund_realtime_path") or "/fd/real/time/{code}/{licence}")
        self.history_path_template = str(options.get("history_path_template") or "/hsstock/vip/{symbol}/{interval}/{adjust}/{licence}")
        self.freshness_seconds = freshness_seconds
        self.timeout = timeout

    def get_quote(self, symbol: str) -> Quote:
        self._require_licence()
        normalized = normalize_symbol(symbol)
        code = normalized.split(".", 1)[0]
        path_template = self.fund_realtime_path if infer_asset_type(normalized) == "etf" else self.stock_realtime_path
        path = path_template.format(code=urllib.parse.quote(code), symbol=urllib.parse.quote(normalized), licence=urllib.parse.quote(self.licence))
        text = self._request_text(f"{self.base_url}{path}", "必盈实时行情")
        return parse_quote_response(text, normalized, freshness_seconds=self.freshness_seconds)

    def get_bars(self, symbol: str, interval: str = "daily", start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        self._require_licence()
        normalized = normalize_symbol(symbol)
        interval_code = INTERVALS.get(interval, interval)
        adjust_code = ADJUSTS.get(adjust, adjust)
        path = self.history_path_template.format(
            code=urllib.parse.quote(normalized.split(".", 1)[0]),
            symbol=urllib.parse.quote(normalized),
            interval=urllib.parse.quote(interval_code),
            adjust=urllib.parse.quote(adjust_code),
            licence=urllib.parse.quote(self.licence),
        )
        query = urllib.parse.urlencode({"st": start, "et": end})
        text = self._request_text(f"{self.history_base_url}{path}?{query}", "必盈历史 K 线")
        return parse_bars_response(text, normalized)

    def get_daily_bars(self, symbol: str, start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        return self.get_bars(symbol, "daily", start, end, adjust)

    def _require_licence(self) -> None:
        if not self.licence:
            raise BiyingAPIError(f"缺少必盈 API licence，请设置环境变量 {self.licence_env} 或在配置中填写 data.providers.biying.licence")

    def _request_text(self, url: str, label: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BiyingAPIError(f"{label}请求失败：{exc}") from exc
