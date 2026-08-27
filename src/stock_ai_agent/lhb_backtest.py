"""Incremental 龙虎榜 seat-profile backtest using persisted front-adjusted daily bars."""

from __future__ import annotations

from decimal import Decimal


def refresh_lhb_seat_profiles(store) -> int:
    if not hasattr(store, "load_lhb_records") or not hasattr(store, "save_seat_profile"):
        return 0
    samples: dict[str, list[Decimal]] = {}
    appearances: dict[str, int] = {}
    for record in store.load_lhb_records():
        symbol = str(record.get("symbol") or "")
        bars = store.load_watchlist_bars(symbol, interval="daily", price_mode="qfq")
        indexed = {bar.timestamp.date().isoformat(): index for index, bar in enumerate(bars)}
        start = indexed.get(str(record.get("trade_date")))
        if start is None or start + 3 >= len(bars) or bars[start].close_price <= 0:
            continue
        result = bars[start + 3].close_price / bars[start].close_price - Decimal("1")
        for index in range(1, 6):
            seat = str(record.get(f"buy_seat_{index}") or "")
            if not seat:
                continue
            samples.setdefault(seat, []).append(result)
            appearances[seat] = appearances.get(seat, 0) + 1
    for seat, returns in samples.items():
        count = len(returns)
        store.save_seat_profile({
            "seat_name": seat,
            "buy_count": count,
            "total_appearances": appearances[seat],
            "t3_avg_return": str(sum(returns, Decimal("0")) / count),
            "t3_win_rate": str(sum(1 for value in returns if value > 0) / count),
        })
    return len(samples)
