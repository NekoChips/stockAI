from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import AppConfig
from .models import Bar
from .universe import validate_hs_symbol
from .watchlist import effective_watchlist


MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
MINUTE_PERIODS = (1, 5, 15, 30, 60)


def build_instrument_detail_payload(
    config: AppConfig,
    store: Any,
    symbol: str,
    as_of: date | None = None,
) -> dict[str, Any]:
    normalized = validate_hs_symbol(symbol)
    item = next((row for row in effective_watchlist(config, store) if row.symbol == normalized), None)
    if item is None:
        raise ValueError(f"标的 {normalized} 不在观察池中")
    as_of = as_of or date.today()
    daily_bars = store.load_watchlist_bars(normalized, interval="daily")
    ticks = store.load_quote_ticks(normalized, as_of) if hasattr(store, "load_quote_ticks") else []
    archived_minute_bars = store.load_intraday_bars(normalized, interval="1m")
    current_minute_bars = aggregate_quote_ticks(ticks, 1)
    five_day_bars = _latest_trading_day_bars([*archived_minute_bars, *current_minute_bars], limit=5)
    latest = store.load_latest_quotes([normalized]).get(normalized) if hasattr(store, "load_latest_quotes") else None
    fills = [fill for fill in store.load_all_fills() if fill.symbol == normalized] if hasattr(store, "load_all_fills") else []

    return {
        "instrument": {"symbol": item.symbol, "name": item.name, "asset_type": item.asset_type},
        "latest_quote": latest,
        "intraday": {"ticks": ticks, "previous_close": latest.get("previous_close") if latest else None},
        "five_day": [_bar_payload(bar) for bar in five_day_bars],
        "five_day_trading_days": len({_as_datetime(bar.timestamp).date() for bar in five_day_bars}),
        "daily": [_bar_payload(bar) for bar in daily_bars[-240:]],
        "weekly": [_bar_payload(bar) for bar in aggregate_bars(daily_bars, "weekly")[-120:]],
        "monthly": [_bar_payload(bar) for bar in aggregate_bars(daily_bars, "monthly")[-120:]],
        "minute_bars": {f"{minutes}m": [_bar_payload(bar) for bar in aggregate_quote_ticks(ticks, minutes)] for minutes in MINUTE_PERIODS},
        "trade_markers": [
            {
                "timestamp": fill.timestamp,
                "direction": fill.direction.value,
                "quantity": fill.quantity,
                "price": fill.price,
                "fee": fill.fee,
                "summary": f"{fill.direction.value} {fill.quantity} 份，成交价 {fill.price}，手续费 {fill.fee}",
            }
            for fill in fills
        ],
    }


def aggregate_bars(bars: Iterable[Bar], period: str) -> list[Bar]:
    grouped: OrderedDict[date, list[Bar]] = OrderedDict()
    for bar in sorted(bars, key=lambda item: _as_datetime(item.timestamp)):
        timestamp = _as_datetime(bar.timestamp)
        key = timestamp.date() - timedelta(days=timestamp.weekday()) if period == "weekly" else timestamp.date().replace(day=1)
        grouped.setdefault(key, []).append(bar)
    return [_combine_bars(group, datetime.combine(key, time.min, tzinfo=MARKET_TIMEZONE)) for key, group in grouped.items()]


def aggregate_quote_ticks(ticks: Iterable[dict], minutes: int) -> list[Bar]:
    grouped: OrderedDict[datetime, list[dict]] = OrderedDict()
    for tick in sorted(ticks, key=lambda item: _as_datetime(item["observed_at"])):
        timestamp = _as_datetime(tick["observed_at"])
        bucket = timestamp.replace(minute=(timestamp.minute // minutes) * minutes, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(tick)
    result: list[Bar] = []
    for timestamp, group in grouped.items():
        prices = [Decimal(str(item["latest_price"])) for item in group]
        result.append(
            Bar(
                symbol=str(group[0]["symbol"]),
                timestamp=timestamp,
                open_price=prices[0],
                high_price=max(prices),
                low_price=min(prices),
                close_price=prices[-1],
                volume=Decimal("0"),
                amount=Decimal("0"),
            )
        )
    return result


def _latest_trading_day_bars(bars: Iterable[Bar], limit: int) -> list[Bar]:
    ordered = sorted(bars, key=lambda item: _as_datetime(item.timestamp))
    dates = sorted({_as_datetime(bar.timestamp).date() for bar in ordered})[-limit:]
    selected_dates = set(dates)
    return [bar for bar in ordered if _as_datetime(bar.timestamp).date() in selected_dates]


def _combine_bars(bars: list[Bar], timestamp: datetime) -> Bar:
    return Bar(
        symbol=bars[0].symbol,
        timestamp=timestamp,
        open_price=bars[0].open_price,
        high_price=max(item.high_price for item in bars),
        low_price=min(item.low_price for item in bars),
        close_price=bars[-1].close_price,
        volume=sum((item.volume for item in bars), Decimal("0")),
        amount=sum((item.amount for item in bars), Decimal("0")),
    )


def _bar_payload(bar: Bar) -> dict[str, Any]:
    return {
        "time": _as_datetime(bar.timestamp),
        "open": bar.open_price,
        "high": bar.high_price,
        "low": bar.low_price,
        "close": bar.close_price,
        "volume": bar.volume,
        "amount": bar.amount,
    }


def _as_datetime(value: date | datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=MARKET_TIMEZONE) if value.tzinfo is None else value.astimezone(MARKET_TIMEZONE)
    return datetime.combine(value, time.min, tzinfo=MARKET_TIMEZONE)
