from __future__ import annotations

from typing import List, Protocol

from ..models import Bar


class MarketDataStore(Protocol):
    def initialize(self) -> None:
        ...

    def save_bars(self, bars: List[Bar], interval: str = "daily", source: str = "unknown") -> int:
        ...

    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> List[Bar]:
        ...
