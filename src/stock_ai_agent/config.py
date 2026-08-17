from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class InstrumentConfig:
    symbol: str
    asset_type: str
    name: str = ""


@dataclass(frozen=True)
class BenchmarkConfig:
    symbol: str
    name: str
    akshare_symbol: str


@dataclass(frozen=True)
class DataConfig:
    provider: str
    history_provider: str
    freshness_seconds: int
    history: Dict[str, object]
    providers: Dict[str, Dict[str, object]]


@dataclass(frozen=True)
class StorageConfig:
    driver: str
    database: str


@dataclass(frozen=True)
class PaperAccountConfig:
    initial_cash: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal


@dataclass(frozen=True)
class RiskConfig:
    max_symbol_weight: Decimal
    max_total_exposure: Decimal
    min_cash_ratio: Decimal
    max_drawdown: Decimal
    max_daily_trades: int
    high_atr_ratio: Decimal


@dataclass(frozen=True)
class StrategyConfig:
    target_weight_levels: List[Decimal]
    manual_approval_required: bool
    weights: Dict[str, Decimal]
    quant: Dict[str, object]


@dataclass(frozen=True)
class MonitorConfig:
    poll_seconds: int
    post_close_report_time: str
    respect_market_hours: bool
    settle_on_start: bool


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    allowed_exchanges: List[str]
    allowed_asset_types: List[str]
    data: DataConfig
    storage: StorageConfig
    paper_account: PaperAccountConfig
    universe: List[InstrumentConfig]
    benchmarks: List[BenchmarkConfig]
    risk: RiskConfig
    strategy: StrategyConfig
    monitor: MonitorConfig


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def load_config(path: str | Path = "config/default.yaml") -> AppConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    market = raw["market"]
    data = raw["data"]
    storage = raw["storage"]
    account = raw["paper_account"]
    risk = raw["risk"]
    strategy = raw["strategy"]
    monitor = raw.get("monitor", {})

    return AppConfig(
        timezone=market["timezone"],
        allowed_exchanges=list(market["allowed_exchanges"]),
        allowed_asset_types=list(market["allowed_asset_types"]),
        data=DataConfig(
            provider=data["provider"],
            history_provider=data.get("history_provider", data["provider"]),
            freshness_seconds=int(data["freshness_seconds"]),
            history=dict(data.get("history", {})),
            providers={key: dict(value) for key, value in data.get("providers", {}).items()},
        ),
        storage=StorageConfig(
            driver=storage["driver"],
            database=storage["database"],
        ),
        paper_account=PaperAccountConfig(
            initial_cash=_decimal(account["initial_cash"]),
            fee_rate=_decimal(account["fee_rate"]),
            slippage_rate=_decimal(account["slippage_rate"]),
        ),
        universe=[
            InstrumentConfig(
                symbol=item["symbol"],
                asset_type=item["asset_type"],
                name=item.get("name", ""),
            )
            for item in raw["universe"]
        ],
        benchmarks=[
            BenchmarkConfig(
                symbol=item["symbol"],
                name=item["name"],
                akshare_symbol=item.get("akshare_symbol", item["symbol"].split(".", 1)[0]),
            )
            for item in raw.get("benchmarks", [])
        ],
        risk=RiskConfig(
            max_symbol_weight=_decimal(risk["max_symbol_weight"]),
            max_total_exposure=_decimal(risk["max_total_exposure"]),
            min_cash_ratio=_decimal(risk["min_cash_ratio"]),
            max_drawdown=_decimal(risk["max_drawdown"]),
            max_daily_trades=int(risk["max_daily_trades"]),
            high_atr_ratio=_decimal(risk["high_atr_ratio"]),
        ),
        strategy=StrategyConfig(
            target_weight_levels=[_decimal(level) for level in strategy["target_weight_levels"]],
            manual_approval_required=bool(strategy["manual_approval_required"]),
            weights={key: _decimal(value) for key, value in strategy["weights"].items()},
            quant=dict(strategy["quant"]),
        ),
        monitor=MonitorConfig(
            poll_seconds=int(monitor.get("poll_seconds", 60)),
            post_close_report_time=str(monitor.get("post_close_report_time", "15:05")),
            respect_market_hours=bool(monitor.get("respect_market_hours", True)),
            settle_on_start=bool(monitor.get("settle_on_start", True)),
        ),
    )
