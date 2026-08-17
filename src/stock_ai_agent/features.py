from __future__ import annotations

from decimal import Decimal, getcontext
from statistics import pstdev
from typing import Iterable, List, Optional

from .models import Bar, FeatureSet, Quote

getcontext().prec = 28


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def sma(values: Iterable[Decimal], period: int) -> Optional[Decimal]:
    items = list(values)
    if len(items) < period:
        return None
    window = items[-period:]
    return sum(window, Decimal("0")) / Decimal(period)


def ema(values: Iterable[Decimal], period: int) -> Optional[Decimal]:
    items = list(values)
    if len(items) < period:
        return None
    multiplier = Decimal("2") / Decimal(period + 1)
    result = sum(items[:period], Decimal("0")) / Decimal(period)
    for value in items[period:]:
        result = (value - result) * multiplier + result
    return result


def macd(values: Iterable[Decimal]) -> Optional[dict]:
    items = list(values)
    if len(items) < 35:
        return None
    macd_line_series: List[Decimal] = []
    for index in range(26, len(items) + 1):
        subset = items[:index]
        fast = ema(subset, 12)
        slow = ema(subset, 26)
        if fast is not None and slow is not None:
            macd_line_series.append(fast - slow)
    signal = ema(macd_line_series, 9)
    if signal is None:
        return None
    line = macd_line_series[-1]
    histogram = line - signal
    return {"macd": line, "macd_signal": signal, "macd_histogram": histogram}


def rsi(values: Iterable[Decimal], period: int = 14) -> Optional[Decimal]:
    items = list(values)
    if len(items) <= period:
        return None
    gains: List[Decimal] = []
    losses: List[Decimal] = []
    for previous, current in zip(items[-period - 1 : -1], items[-period:]):
        change = current - previous
        if change >= 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(-change)
    avg_gain = sum(gains, Decimal("0")) / Decimal(period)
    avg_loss = sum(losses, Decimal("0")) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def bollinger(values: Iterable[Decimal], period: int = 20, width: Decimal = Decimal("2")) -> Optional[dict]:
    items = list(values)
    if len(items) < period:
        return None
    window = items[-period:]
    middle = sum(window, Decimal("0")) / Decimal(period)
    std = _d(pstdev([float(value) for value in window]))
    if std == 0:
        z_score = Decimal("0")
    else:
        z_score = (window[-1] - middle) / std
    return {
        "bollinger_middle": middle,
        "bollinger_upper": middle + width * std,
        "bollinger_lower": middle - width * std,
        "bollinger_z": z_score,
    }


def atr(bars: Iterable[Bar], period: int = 14) -> Optional[Decimal]:
    items = list(bars)
    if len(items) <= period:
        return None
    true_ranges: List[Decimal] = []
    for previous, current in zip(items[-period - 1 : -1], items[-period:]):
        ranges = [
            current.high_price - current.low_price,
            abs(current.high_price - previous.close_price),
            abs(current.low_price - previous.close_price),
        ]
        true_ranges.append(max(ranges))
    return sum(true_ranges, Decimal("0")) / Decimal(period)


def build_features(symbol: str, bars: List[Bar], quote: Optional[Quote] = None) -> FeatureSet:
    if not bars:
        raise ValueError("缺少 K 线数据，无法计算技术指标")
    closes = [bar.close_price for bar in bars]
    volumes = [bar.volume for bar in bars]
    latest_bar = bars[-1]
    close = quote.latest_price if quote else latest_bar.close_price
    values = {"close": close}
    missing: List[str] = []

    indicator_map = {
        "sma5": sma(closes, 5),
        "sma20": sma(closes, 20),
        "ema12": ema(closes, 12),
        "ema26": ema(closes, 26),
        "rsi14": rsi(closes, 14),
        "atr14": atr(bars, 14),
    }
    for key, value in indicator_map.items():
        if value is None:
            missing.append(f"{key} 数据不足")
        else:
            values[key] = value

    macd_values = macd(closes)
    if macd_values is None:
        missing.append("MACD 数据不足")
    else:
        values.update(macd_values)

    bollinger_values = bollinger(closes)
    if bollinger_values is None:
        missing.append("布林带数据不足")
    else:
        values.update(bollinger_values)

    avg_volume = sma(volumes, 20)
    if avg_volume is None or avg_volume == 0:
        missing.append("成交量均值数据不足")
    else:
        values["volume_ratio"] = latest_bar.volume / avg_volume

    total_volume = sum(volumes[-20:], Decimal("0"))
    if total_volume > 0:
        total_amount = sum((bar.close_price * bar.volume for bar in bars[-20:]), Decimal("0"))
        values["vwap"] = total_amount / total_volume
    else:
        missing.append("VWAP 成交量不足")

    if latest_bar.high_price > latest_bar.low_price:
        values["intraday_position"] = (close - latest_bar.low_price) / (latest_bar.high_price - latest_bar.low_price)
    else:
        values["intraday_position"] = Decimal("0.5")

    if "atr14" in values and close > 0:
        values["atr_ratio"] = values["atr14"] / close

    return FeatureSet(symbol=symbol, timestamp=quote.timestamp if quote else latest_bar.timestamp, values=values, missing_reasons=missing)
