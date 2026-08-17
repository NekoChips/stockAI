from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from .config import InstrumentConfig
from .models import Instrument


SYMBOL_PATTERN = re.compile(r"^(?P<code>\d{6})\.(?P<exchange>SH|SZ)$")
ETF_PREFIXES = ("15", "16", "50", "51", "56", "58")
B_SHARE_PREFIXES = ("200", "900")


class UniverseError(ValueError):
    pass


def normalize_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if "." not in clean and clean.isdigit() and len(clean) == 6:
        if clean.startswith(("5", "6", "9")):
            return f"{clean}.SH"
        return f"{clean}.SZ"
    return clean


def infer_asset_type(symbol: str) -> str:
    code = normalize_symbol(symbol).split(".", 1)[0]
    if code.startswith(ETF_PREFIXES):
        return "etf"
    return "stock"


def validate_hs_symbol(symbol: str, asset_type: str | None = None) -> str:
    normalized = normalize_symbol(symbol)
    match = SYMBOL_PATTERN.match(normalized)
    if not match:
        raise UniverseError(f"仅支持沪深市场代码，收到：{symbol}")
    code = match.group("code")
    if code.startswith(B_SHARE_PREFIXES):
        raise UniverseError(f"暂不支持 B 股标的：{normalized}")
    inferred = infer_asset_type(normalized)
    if asset_type and asset_type not in {"stock", "etf"}:
        raise UniverseError(f"仅支持 A 股股票或 ETF，收到资产类型：{asset_type}")
    if asset_type and asset_type != inferred and asset_type == "stock" and inferred == "etf":
        raise UniverseError(f"标的 {normalized} 更像 ETF，请配置为 etf")
    return normalized


@dataclass(frozen=True)
class Universe:
    instruments: List[Instrument]

    @classmethod
    def from_config(cls, items: Iterable[InstrumentConfig]) -> "Universe":
        instruments = []
        for item in items:
            symbol = validate_hs_symbol(item.symbol, item.asset_type)
            instruments.append(Instrument(symbol=symbol, asset_type=item.asset_type, name=item.name))
        return cls(instruments)

    def contains(self, symbol: str) -> bool:
        normalized = normalize_symbol(symbol)
        return any(item.symbol == normalized for item in self.instruments)

    def require(self, symbol: str) -> Instrument:
        normalized = normalize_symbol(symbol)
        for item in self.instruments:
            if item.symbol == normalized:
                return item
        raise UniverseError(f"标的 {normalized} 不在固定模拟盘股票/ETF 池中")
