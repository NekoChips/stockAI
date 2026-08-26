"""Analysis-only external market feeds for A-share strategy evidence.

These adapters never create tradeable instruments. Provider failures are returned to
the monitor as unavailable datasets, which fail the related strategy closed.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import quote
from urllib.request import urlopen


US_SYMBOLS = ("^IXIC", "^GSPC", "^DJI", "XLK", "XLV", "XLF", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC")
QUANT_SEATS = (
    ("银河证券北京中关村大街", "幻方量化", "高频/中性/指增"), ("中信证券杭州延安路", "幻方量化", "高频/中性/指增"), ("华泰证券杭州求是路", "幻方量化", "高频/中性/指增"),
    ("开源证券西安西大街", "九坤投资", "CTA+多因子"), ("开源证券西安太华路", "九坤投资", "CTA+多因子"), ("中信证券北京总部", "九坤投资", "CTA+多因子"),
    ("华泰证券上海福山路", "明汯投资", "全频段量化"), ("华鑫证券上海淞滨路", "明汯投资", "全频段量化"), ("申万宏源上海陆家嘴环路", "明汯投资", "全频段量化"),
    ("中信证券杭州凤起路", "灵均投资", "中性/指增"), ("华泰证券杭州解放东路", "灵均投资", "中性/指增"),
    ("中信建投北京朝阳门内大街", "天演资本", "Alpha/中性"), ("华泰证券北京分公司", "天演资本", "Alpha/中性"),
    ("国泰君安上海江苏路", "衍复投资", "中高频量化"), ("华泰南京江宁天元东路", "衍复投资", "中高频量化"),
)


def default_quant_seats() -> list[dict]:
    return [{"seat_name": seat, "quant_firm": firm, "strategy_style": style, "is_active": True} for seat, firm, style in QUANT_SEATS]


def fetch_us_market_data(symbols: tuple[str, ...] = US_SYMBOLS) -> list[dict]:
    rows: list[dict] = []
    for symbol in symbols:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=5d&interval=1d"
        with urlopen(url, timeout=12) as response:  # nosec B310: fixed HTTPS host
            payload = json.loads(response.read().decode("utf-8"))
        result = payload["chart"]["result"][0]
        closes = [Decimal(str(value)) for value in result["indicators"]["quote"][0]["close"] if value is not None]
        timestamps = result.get("timestamp") or []
        if len(closes) < 2 or not timestamps:
            continue
        previous, current = closes[-2], closes[-1]
        if previous <= 0:
            continue
        rows.append({"market": "US", "symbol": symbol, "name": symbol, "trade_date": datetime.fromtimestamp(timestamps[-1]).date().isoformat(), "prev_close": str(previous), "close_price": str(current), "change_pct": str(((current / previous) - Decimal("1")) * Decimal("100")), "source": "yahoo_chart"})
    return rows


def fetch_korea_market_data() -> list[dict]:
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - release dependency guard
        raise RuntimeError("AKShare 不可用，无法同步韩股市场数据。") from exc
    function = getattr(ak, "index_korea_hist", None)
    if function is None:
        raise RuntimeError("当前 AKShare 版本不支持韩国指数接口。")
    rows: list[dict] = []
    for symbol in ("KOSPI", "KOSPI_IT"):
        frame = function(symbol=symbol)
        if len(frame.index) < 2:
            continue
        close_column = next((column for column in frame.columns if str(column) in {"收盘", "Close", "close"}), None)
        date_column = next((column for column in frame.columns if str(column) in {"日期", "Date", "date"}), None)
        if not close_column:
            continue
        previous, current = Decimal(str(frame.iloc[-2][close_column])), Decimal(str(frame.iloc[-1][close_column]))
        if previous <= 0:
            continue
        trade_date = str(frame.iloc[-1][date_column])[:10] if date_column else date.today().isoformat()
        rows.append({"market": "KR", "symbol": symbol, "name": symbol, "trade_date": trade_date, "prev_close": str(previous), "close_price": str(current), "change_pct": str(((current / previous) - Decimal("1")) * Decimal("100")), "source": "akshare"})
    return rows


def fetch_lhb_data(trade_date: date, ak_module=None) -> list[dict]:
    if ak_module is None:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("AKShare 不可用，无法同步龙虎榜。") from exc
    else:
        ak = ak_module
    frame = ak.stock_lhb_detail_em(start_date=trade_date.strftime("%Y%m%d"), end_date=trade_date.strftime("%Y%m%d"))
    records: list[dict] = []
    for _, item in frame.iterrows():
        get = lambda *names: next((item[name] for name in names if name in frame.columns and item[name] is not None), None)
        code = get("代码", "股票代码")
        if not code:
            continue
        record = {"trade_date": trade_date.isoformat(), "symbol": f"{str(code).zfill(6)}.{ 'SH' if str(code).startswith(('6', '5')) else 'SZ'}", "name": get("名称", "股票名称"), "reason": get("上榜原因"), "close_price": str(get("收盘价") or "0"), "change_pct": str(get("涨跌幅") or "0"), "turnover_rate": str(get("换手率") or "0"), "total_amount": str(get("成交额") or "0"), "net_buy": str(get("净买额") or "0"), "star_net_buy": str(get("游资净买额", "知名游资净买额") or "") or None, "institution_net_buy": str(get("机构净买额", "机构买入净额") or "") or None, "seat_detail_available": False, "source": "akshare", "raw_data": {str(column): str(item[column]) for column in frame.columns}}
        detail_loader = getattr(ak, "stock_lhb_stock_detail_em", None)
        if detail_loader is not None:
            try:
                for side, flag in (("buy", "买入"), ("sell", "卖出")):
                    detail_frame = detail_loader(symbol=str(code).zfill(6), date=trade_date.strftime("%Y%m%d"), flag=flag)
                    detail_rows = _normalize_lhb_seat_rows(detail_frame, side)
                    for index, (seat_name, amount, net_amount) in enumerate(detail_rows[:5], start=1):
                        record[f"{side}_seat_{index}"] = seat_name
                        record[f"{side}_amount_{index}"] = str(amount)
                        record[f"{side}_net_{index}"] = str(net_amount)
                    record["seat_detail_available"] = record["seat_detail_available"] or bool(detail_rows)
            except Exception:
                record["seat_detail_available"] = False
        records.append(record)
    return records


def _normalize_lhb_seat_rows(frame, side: str) -> list[tuple[str, Decimal, Decimal]]:
    rows: list[tuple[str, Decimal, Decimal]] = []
    columns = {str(column) for column in getattr(frame, "columns", [])}
    seat_column = next((column for column in ("营业部名称", "席位名称", "营业部") if column in columns), None)
    amount_column = next((column for column in (("买入金额", "买入额") if side == "buy" else ("卖出金额", "卖出额")) if column in columns), None)
    net_column = next((column for column in ("净额", "净买额", "净卖额") if column in columns), None)
    if not seat_column or not amount_column:
        return rows
    for _, item in frame.iterrows():
        seat = str(item[seat_column] or "").strip()
        if not seat:
            continue
        try:
            amount = Decimal(str(item[amount_column] or "0").replace(",", ""))
            net_amount = Decimal(str(item[net_column] or "0").replace(",", "")) if net_column else Decimal("0")
        except Exception:
            continue
        rows.append((seat, amount, net_amount))
    return rows


def fetch_futures_positions(as_of: date | None = None) -> list[dict]:
    """Normalize AKShare's daily IC top-10 rank summary for the risk-control strategy.

    The upstream field names have varied between releases, so an unknown layout is
    treated as unavailable rather than manufacturing a net-position signal.
    """
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - release dependency guard
        raise RuntimeError("AKShare 不可用，无法同步中金所 IC 持仓。") from exc
    as_of = as_of or date.today()
    function = getattr(ak, "get_rank_sum_daily", None)
    if function is None:
        raise RuntimeError("当前 AKShare 版本不支持中金所会员持仓汇总接口。")
    day = as_of.strftime("%Y%m%d")
    frame = function(start_day=day, end_day=day, vars_list=["IC"])
    if frame is None or getattr(frame, "empty", True):
        return []
    row = frame.iloc[-1]
    long_value = _rank_value(row, frame.columns, "long")
    short_value = _rank_value(row, frame.columns, "short")
    if long_value is None or short_value is None or long_value + short_value <= 0:
        return []
    net_ratio = (long_value - short_value) / (long_value + short_value)
    return [{
        "trade_date": str(row.get("date") or row.get("日期") or as_of.isoformat())[:10],
        "contract": "IC",
        "top10_long": str(long_value),
        "top10_short": str(short_value),
        "top10_net_ratio": str(net_ratio),
        "combined_net_ratio": str(net_ratio),
        "source": "akshare.get_rank_sum_daily",
    }]


def _rank_value(row, columns, side: str) -> Decimal | None:
    """Prefer top-10 open-interest totals while tolerating AKShare column naming."""
    candidates = [
        column
        for column in columns
        if side in str(column).lower()
        and ("open_interest" in str(column).lower() or "持仓" in str(column))
        and ("10" in str(column) or "top10" in str(column).lower())
    ]
    for column in candidates:
        try:
            value = Decimal(str(row[column]).replace(",", ""))
        except Exception:  # noqa: BLE001 - source cells can contain empty placeholders
            continue
        if value >= 0:
            return value
    return None
