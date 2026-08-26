from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class InstrumentConfig:
    symbol: str
    asset_type: str
    name: str = ""
    lifecycle_status: str = "observing"
    trading_enabled: bool = True


@dataclass(frozen=True)
class BenchmarkConfig:
    symbol: str
    name: str
    akshare_symbol: str


@dataclass(frozen=True)
class DataConfig:
    provider: str
    market_fallback_providers: List[str]
    history_provider: str
    history_fallback_providers: List[str]
    freshness_seconds: int
    history: Dict[str, object]
    providers: Dict[str, Dict[str, object]]


@dataclass(frozen=True)
class MySQLConnectionConfig:
    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True)
class StorageConfig:
    driver: str
    database: str
    backup_dir: str
    mysql: Optional[MySQLConnectionConfig] = None


@dataclass(frozen=True)
class PaperAccountConfig:
    initial_cash: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal
    min_commission: Decimal = Decimal("5")
    stock_sell_stamp_tax: Decimal = Decimal("0.0005")


@dataclass(frozen=True)
class RiskConfig:
    max_symbol_weight: Decimal
    max_etf_weight: Decimal
    max_stock_weight: Decimal
    max_etf_total_weight: Decimal
    max_stock_total_weight: Decimal
    max_total_exposure: Decimal
    min_cash_ratio: Decimal
    max_daily_trades: Optional[int]
    max_operations_per_symbol: int
    max_drawdown: Decimal
    single_position_loss: Decimal
    trailing_drawdown: Decimal
    portfolio_daily_loss: Decimal
    high_atr_ratio: Decimal

    def symbol_limit(self, asset_type: str) -> Decimal:
        return min(
            self.max_symbol_weight,
            self.max_etf_weight if asset_type == "etf" else self.max_stock_weight,
        )

    def asset_total_limit(self, asset_type: str) -> Decimal:
        return self.max_etf_total_weight if asset_type == "etf" else self.max_stock_total_weight


@dataclass(frozen=True)
class StrategyConfig:
    target_weight_levels: List[Decimal]
    manual_approval_required: bool
    weights: Dict[str, Decimal]
    weights_by_asset_type: Dict[str, Dict[str, Decimal]]
    enabled_by_asset_type: Dict[str, List[str]]
    aggregator: Dict[str, object]
    quant: Dict[str, object]
    technical: Dict[str, object]
    external: Dict[str, object]


@dataclass(frozen=True)
class MonitorConfig:
    poll_seconds: int
    post_close_report_time: str
    respect_market_hours: bool
    settle_on_start: bool
    quote_poll_seconds: float = 6.5


@dataclass(frozen=True)
class WebConfig:
    require_basic_auth: bool
    username: str
    password: str
    analysis_start_date: date


@dataclass(frozen=True)
class AppConfig:
    environment: str
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
    web: WebConfig


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def load_config(path: str | Path = "config/default.yaml") -> AppConfig:
    raw = _expand_environment(_load_raw_config(Path(path)))
    market = raw["market"]
    data = raw["data"]
    storage = raw["storage"]
    account = raw["paper_account"]
    risk = raw["risk"]
    strategy = raw["strategy"]
    monitor = raw.get("monitor", {})
    web = raw.get("web", {})
    mysql_raw = storage.get("mysql")
    mysql = None
    if mysql_raw is not None:
        try:
            mysql_port = int(mysql_raw["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError("MySQL 发布配置中的 STOCK_AI_MYSQL_PORT 必须是有效端口号。") from exc
        mysql = MySQLConnectionConfig(
            host=str(mysql_raw["host"]),
            port=mysql_port,
            database=str(mysql_raw["database"]),
            username=str(mysql_raw["username"]),
            password=str(mysql_raw["password"]),
        )
    if storage["driver"] == "mysql" and mysql is None:
        raise ValueError("MySQL 存储配置缺少 mysql 连接信息。")

    return AppConfig(
        environment=str(raw.get("environment", "development")),
        timezone=market["timezone"],
        allowed_exchanges=list(market["allowed_exchanges"]),
        allowed_asset_types=list(market["allowed_asset_types"]),
        data=DataConfig(
            provider=data["provider"],
            market_fallback_providers=[str(item) for item in data.get("market_fallback_providers", ["akshare"])],
            history_provider=data.get("history_provider", data["provider"]),
            history_fallback_providers=[str(item) for item in data.get("history_fallback_providers", [])],
            freshness_seconds=int(data["freshness_seconds"]),
            history=dict(data.get("history", {})),
            providers={key: dict(value) for key, value in data.get("providers", {}).items()},
        ),
        storage=StorageConfig(
            driver=storage["driver"],
            database=storage["database"],
            backup_dir=str(storage.get("backup_dir", "data/backups")),
            mysql=mysql,
        ),
        paper_account=PaperAccountConfig(
            initial_cash=_decimal(account["initial_cash"]),
            fee_rate=_decimal(account["fee_rate"]),
            slippage_rate=_decimal(account["slippage_rate"]),
            min_commission=_decimal(account.get("min_commission", "5")),
            stock_sell_stamp_tax=_decimal(account.get("stock_sell_stamp_tax", "0.0005")),
        ),
        universe=[
            InstrumentConfig(
                symbol=item["symbol"],
                asset_type=item["asset_type"],
                name=item.get("name", ""),
                lifecycle_status=str(item.get("lifecycle_status", "observing")),
                trading_enabled=bool(item.get("trading_enabled", True)),
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
            max_etf_weight=_decimal(risk.get("max_etf_weight", risk["max_symbol_weight"])),
            max_stock_weight=_decimal(risk.get("max_stock_weight", risk["max_symbol_weight"])),
            max_etf_total_weight=_decimal(risk.get("max_etf_total_weight", risk["max_total_exposure"])),
            max_stock_total_weight=_decimal(risk.get("max_stock_total_weight", risk["max_total_exposure"])),
            max_total_exposure=_decimal(risk["max_total_exposure"]),
            min_cash_ratio=_decimal(risk["min_cash_ratio"]),
            max_daily_trades=(None if risk.get("max_daily_trades") in (None, "") else int(risk["max_daily_trades"])),
            max_operations_per_symbol=int(risk.get("max_operations_per_symbol", 10)),
            max_drawdown=_decimal(risk.get("max_drawdown", "0.10")),
            single_position_loss=_decimal(risk.get("single_position_loss", "0.08")),
            trailing_drawdown=_decimal(risk.get("trailing_drawdown", "0.06")),
            portfolio_daily_loss=_decimal(risk.get("portfolio_daily_loss", "0.03")),
            high_atr_ratio=_decimal(risk["high_atr_ratio"]),
        ),
        strategy=StrategyConfig(
            target_weight_levels=[_decimal(level) for level in strategy["target_weight_levels"]],
            manual_approval_required=bool(strategy["manual_approval_required"]),
            weights={key: _decimal(value) for key, value in strategy["weights"].items()},
            weights_by_asset_type={
                asset_type: {key: _decimal(value) for key, value in values.items()}
                for asset_type, values in strategy.get("weights_by_asset_type", {}).items()
            },
            enabled_by_asset_type={
                asset_type: [str(value) for value in values]
                for asset_type, values in strategy.get("enabled_by_asset_type", {}).items()
            },
            aggregator=dict(strategy.get("aggregator", {})),
            quant=dict(strategy["quant"]),
            technical=dict(strategy.get("technical", {})),
            external=dict(strategy.get("external", {})),
        ),
        monitor=MonitorConfig(
            poll_seconds=int(monitor.get("poll_seconds", 60)),
            post_close_report_time=str(monitor.get("post_close_report_time", "15:05")),
            respect_market_hours=bool(monitor.get("respect_market_hours", True)),
            settle_on_start=bool(monitor.get("settle_on_start", True)),
            quote_poll_seconds=float(monitor.get("quote_poll_seconds", 6.5)),
        ),
        web=WebConfig(
            require_basic_auth=bool(web.get("require_basic_auth", False)),
            username=str(web.get("username", "")),
            password=str(web.get("password", "")),
            analysis_start_date=date.fromisoformat(str(web.get("analysis_start_date", "2026-01-01"))),
        ),
    )


def _load_raw_config(path: Path, seen: Optional[set[Path]] = None) -> dict:
    resolved = path.resolve()
    seen = seen or set()
    if resolved in seen:
        raise ValueError(f"配置文件 extends 存在循环引用：{resolved}")
    seen.add(resolved)
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    parent = raw.pop("extends", None)
    if not parent:
        return raw
    base = _load_raw_config(resolved.parent / str(parent), seen)
    return _deep_merge(base, raw)


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _expand_environment(value: object) -> object:
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if not isinstance(value, str):
        return value
    return re.sub(r"\$\{([A-Z0-9_]+)\}", lambda match: os.environ.get(match.group(1), match.group(0)), value)
