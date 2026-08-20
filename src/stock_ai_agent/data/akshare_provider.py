from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from ..models import Bar, Quote
from ..universe import UniverseError, infer_asset_type, normalize_symbol, validate_hs_symbol


class AKShareError(RuntimeError):
    pass


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
ADJUSTS = {"none": "", "qfq": "qfq", "hfq": "hfq"}
PERIODS = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
PREFIXED_INDEX_FUNCTIONS = {"stock_zh_index_daily", "stock_zh_index_daily_tx", "stock_zh_index_daily_em"}
DEFAULT_INDEX_FALLBACK_FUNCTIONS = ["stock_zh_index_daily_tx", "stock_zh_index_daily", "index_zh_a_hist"]


def _decimal(value: Any) -> Decimal:
    if value in (None, "", "-", "--"):
        return Decimal("0")
    return Decimal(str(value).replace(",", ""))


def _records(table: Any) -> List[Dict[str, Any]]:
    if isinstance(table, list):
        return [dict(item) for item in table]
    if hasattr(table, "to_dict"):
        return list(table.to_dict(orient="records"))
    raise AKShareError("AKShare 返回的数据表无法解析")


def _get(record: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return default


def _timestamp(value: Any, fetched_at: datetime) -> datetime:
    if value in (None, "", "-", "--"):
        return fetched_at
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=MARKET_TIMEZONE)
        return parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=MARKET_TIMEZONE)
        except ValueError:
            pass
    return fetched_at


def _find_record(records: Iterable[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
    normalized = normalize_symbol(symbol)
    code = normalized.split(".", 1)[0]
    for record in records:
        record_code = str(_get(record, "代码", "code", "dm", "symbol", default="")).strip()
        if record_code == code or record_code == normalized:
            return record
    raise AKShareError(f"AKShare 实时行情中没有找到标的：{normalized}")


def parse_quote_table(table: Any, symbol: str, fetched_at: Optional[datetime] = None, freshness_seconds: int = 90) -> Quote:
    fetched = fetched_at or datetime.now(timezone.utc)
    record = _find_record(_records(table), symbol)
    normalized = normalize_symbol(symbol)
    latest = _decimal(_get(record, "最新价", "最新", "price", "p"))
    change_percent = _decimal(_get(record, "涨跌幅", "change_percent", "pc", default=0))
    previous_close = _decimal(_get(record, "昨收", "昨收价", "previous_close", default=0))
    if previous_close == 0 and latest > 0:
        denominator = Decimal("1") + change_percent / Decimal("100")
        if denominator != 0:
            previous_close = latest / denominator
    return Quote(
        symbol=normalized,
        name=str(_get(record, "名称", "name", default=normalized)),
        timestamp=_timestamp(_get(record, "更新时间", "时间", "time", "t"), fetched),
        latest_price=latest,
        open_price=_decimal(_get(record, "今开", "开盘", "开盘价", "open", "o")),
        high_price=_decimal(_get(record, "最高", "最高价", "high", "h")),
        low_price=_decimal(_get(record, "最低", "最低价", "low", "l")),
        previous_close=previous_close,
        volume=_decimal(_get(record, "成交量", "volume", "v", default=0)),
        amount=_decimal(_get(record, "成交额", "amount", "a", default=0)),
        change_percent=change_percent,
        source="akshare",
        fetched_at=fetched,
        freshness_seconds=freshness_seconds,
    )


def parse_bars_table(table: Any, symbol: str) -> List[Bar]:
    normalized = normalize_symbol(symbol)
    bars: List[Bar] = []
    for record in _records(table):
        timestamp = _timestamp(_get(record, "日期", "时间", "date", "t"), datetime.now(timezone.utc))
        bars.append(
            Bar(
                symbol=normalized,
                timestamp=timestamp,
                open_price=_decimal(_get(record, "开盘", "open", "o")),
                high_price=_decimal(_get(record, "最高", "high", "h")),
                low_price=_decimal(_get(record, "最低", "low", "l")),
                close_price=_decimal(_get(record, "收盘", "close", "c")),
                volume=_decimal(_get(record, "成交量", "volume", "v", default=0)),
                amount=_decimal(_get(record, "成交额", "amount", "a", default=0)),
            )
        )
    return bars


def _call_index_history(function, function_name: str, symbol: str, start: str, end: str):
    if function_name in PREFIXED_INDEX_FUNCTIONS:
        return function(symbol=symbol)
    try:
        return function(symbol=symbol, period="daily", start_date=start, end_date=end)
    except TypeError:
        return function(symbol=symbol)


def _index_source_symbol(function_name: str, symbol: str, akshare_symbol: str) -> str:
    if function_name not in PREFIXED_INDEX_FUNCTIONS:
        return akshare_symbol
    normalized = normalize_symbol(symbol)
    code, exchange = normalized.split(".", 1)
    prefix = "sh" if exchange == "SH" else "sz"
    return f"{prefix}{code}"


def _filter_bars_by_date(bars: List[Bar], start: str, end: str) -> List[Bar]:
    start_date = _compact_date(start)
    end_date = _compact_date(end)
    return [
        bar
        for bar in bars
        if (start_date is None or bar.timestamp.date() >= start_date)
        and (end_date is None or bar.timestamp.date() <= end_date)
    ]


def _compact_date(value: str) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


class AKShareAdapter:
    def __init__(self, options: Dict[str, object] | None = None, freshness_seconds: int = 90, ak_module: Any = None) -> None:
        self.options = options or {}
        self.freshness_seconds = freshness_seconds
        self.ak = ak_module

    def get_quote(self, symbol: str) -> Quote:
        ak = self._akshare()
        normalized = normalize_symbol(symbol)
        if infer_asset_type(normalized) == "etf":
            function_name = str(self.options.get("fund_spot_function") or "fund_etf_spot_em")
        else:
            function_name = str(self.options.get("stock_spot_function") or "stock_zh_a_spot_em")
        table = getattr(ak, function_name)()
        return parse_quote_table(table, normalized, freshness_seconds=self.freshness_seconds)

    def search_instruments(self, query: str, limit: int = 12) -> List[Dict[str, str]]:
        """Search the public A-share and ETF spot lists by six-digit code or name."""
        text = str(query).strip().upper()
        if len(text) < 2:
            return []
        return [
            item for item in self.list_instruments()
            if text in item["symbol"] or text in item["name"].upper()
        ][:limit]

    def list_instruments(self) -> List[Dict[str, str]]:
        """Load a daily-searchable A-share and ETF catalog from public spot tables."""
        ak = self._akshare()
        sources = [
            (
                "etf",
                [
                    str(self.options.get("fund_spot_function") or "fund_etf_spot_em"),
                    *self._fallback_function_names("fund_spot_fallback_functions", ["fund_etf_spot_ths"]),
                ],
            ),
            (
                "stock",
                [
                    str(self.options.get("stock_spot_function") or "stock_zh_a_spot_em"),
                    *self._fallback_function_names("stock_spot_fallback_functions", ["stock_zh_a_spot_tx"]),
                ],
            ),
        ]
        results: List[Dict[str, str]] = []
        seen: set[str] = set()
        for asset_type, function_names in sources:
            records = self._load_catalog_records(ak, function_names)
            for record in records:
                code = str(_get(record, "代码", "基金代码", "code", "dm", "symbol", default="")).strip()
                name = str(_get(record, "名称", "基金名称", "name", default="")).strip()
                if not code:
                    continue
                try:
                    symbol = validate_hs_symbol(code, asset_type)
                except UniverseError:
                    continue
                if symbol in seen:
                    continue
                seen.add(symbol)
                results.append({"symbol": symbol, "name": name or symbol, "asset_type": asset_type})
        return sorted(results, key=lambda item: item["symbol"])

    def _load_catalog_records(self, ak: Any, function_names: List[str]) -> List[Dict[str, Any]]:
        failures: List[str] = []
        for function_name in dict.fromkeys(function_names):
            if not hasattr(ak, function_name):
                failures.append(f"{function_name}: AKShare 中不存在该函数")
                continue
            try:
                records = _records(getattr(ak, function_name)())
            except Exception as exc:  # noqa: BLE001 - public providers use heterogeneous errors
                failures.append(f"{function_name}: {exc}")
                continue
            if records:
                return records
            failures.append(f"{function_name}: 返回空数据")
        raise AKShareError("证券目录获取失败：" + "；".join(failures))

    def _fallback_function_names(self, option_name: str, defaults: List[str]) -> List[str]:
        configured = self.options.get(option_name, defaults)
        if isinstance(configured, str):
            return [item.strip() for item in configured.split(",") if item.strip()]
        return [str(item) for item in configured]

    def get_bars(self, symbol: str, interval: str = "daily", start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        ak = self._akshare()
        normalized = normalize_symbol(symbol)
        code = normalized.split(".", 1)[0]
        period = PERIODS.get(interval, interval)
        adjust_value = ADJUSTS.get(adjust, adjust)
        if infer_asset_type(normalized) == "etf":
            function_name = str(self.options.get("fund_history_function") or "fund_etf_hist_em")
        else:
            function_name = str(self.options.get("stock_history_function") or "stock_zh_a_hist")
        function = getattr(ak, function_name)
        try:
            table = function(symbol=code, period=period, start_date=start, end_date=end, adjust=adjust_value)
        except TypeError:
            table = function(symbol=code, period=period, start_date=start, end_date=end)
        return parse_bars_table(table, normalized)

    def get_daily_bars(self, symbol: str, start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        return self.get_bars(symbol, "daily", start, end, adjust)

    def get_index_bars(self, symbol: str, akshare_symbol: str, start: str = "20240101", end: str = "20500101") -> List[Bar]:
        ak = self._akshare()
        function_names = self._index_history_function_names()
        failures: List[str] = []
        for function_name in function_names:
            if not hasattr(ak, function_name):
                failures.append(f"{function_name}: AKShare 中不存在该函数")
                continue
            function = getattr(ak, function_name)
            source_symbol = _index_source_symbol(function_name, symbol, akshare_symbol)
            try:
                table = _call_index_history(function, function_name, source_symbol, start, end)
                bars = _filter_bars_by_date(parse_bars_table(table, symbol), start, end)
            except Exception as exc:  # noqa: BLE001 - external data providers raise mixed exception types
                failures.append(f"{function_name}({source_symbol}): {exc}")
                continue
            if bars:
                return bars
            failures.append(f"{function_name}({source_symbol}): 返回空数据")
        detail = "；".join(failures) if failures else "没有可用的指数历史函数"
        raise AKShareError(f"AKShare 指数历史 K 线获取失败：{detail}")

    def _index_history_function_names(self) -> List[str]:
        primary = str(self.options.get("index_history_function") or "index_zh_a_hist")
        configured = self.options.get("index_history_fallback_functions", DEFAULT_INDEX_FALLBACK_FUNCTIONS)
        if isinstance(configured, str):
            fallbacks = [item.strip() for item in configured.split(",") if item.strip()]
        else:
            fallbacks = [str(item) for item in configured]
        names: List[str] = []
        for name in [primary, *fallbacks]:
            if name not in names:
                names.append(name)
        return names

    def _akshare(self):
        if self.ak is not None:
            return self.ak
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise AKShareError("缺少 AKShare 依赖，请先安装：python3 -m pip install akshare") from exc
        self.ak = ak
        return ak
