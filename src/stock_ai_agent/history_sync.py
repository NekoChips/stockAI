from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def compact_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


def date_code(value: date) -> str:
    return value.strftime("%Y%m%d")


def previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def missing_history_range(
    store: Any,
    symbol: str,
    interval: str,
    configured_start: str,
    configured_end: str,
    as_of: date | None = None,
) -> tuple[str, str] | None:
    """Return the inclusive missing K-line range, or None when storage is current."""
    end_date = min(compact_date(configured_end), as_of or date.today())
    recent = store.load_bars(symbol, interval=interval, limit=1)
    start_date = compact_date(configured_start)
    if recent:
        start_date = max(start_date, recent[-1].timestamp.date() + timedelta(days=1))
    if start_date > end_date:
        return None
    return date_code(start_date), date_code(end_date)
