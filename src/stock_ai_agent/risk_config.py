"""Persistence and validation helpers for manually configurable risk limits."""

from __future__ import annotations

from dataclasses import asdict, replace
from decimal import Decimal
from typing import Any

from .config import AppConfig, RiskConfig


RISK_FIELDS = (
    "max_symbol_weight",
    "max_etf_weight",
    "max_stock_weight",
    "max_etf_total_weight",
    "max_stock_total_weight",
    "max_total_exposure",
    "min_cash_ratio",
    "max_operations_per_symbol",
    "max_drawdown",
    "single_position_loss",
    "trailing_drawdown",
    "portfolio_daily_loss",
    "high_atr_ratio",
)


def risk_config_payload(config: RiskConfig, status: str = "active", pending_confirmation: bool = False) -> dict[str, Any]:
    payload = {key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(config).items()}
    payload.update({"status": status, "pending_confirmation": pending_confirmation})
    return payload


def parse_risk_config(base: RiskConfig, payload: dict[str, Any]) -> RiskConfig:
    values = {field: getattr(base, field) for field in RISK_FIELDS}
    for field in RISK_FIELDS:
        if field not in payload:
            continue
        values[field] = int(payload[field]) if field == "max_operations_per_symbol" else Decimal(str(payload[field]))
    result = replace(base, **values)
    _validate(result)
    return result


def _validate(config: RiskConfig) -> None:
    if not Decimal("0") < config.max_symbol_weight <= Decimal("0.30"):
        raise ValueError("单只标的总上限必须在 0% 到 30% 之间。")
    if not Decimal("0") < config.max_etf_weight <= Decimal("0.30"):
        raise ValueError("单只 ETF 上限必须在 0% 到 30% 之间。")
    if not Decimal("0") < config.max_stock_weight <= Decimal("0.30"):
        raise ValueError("单只股票上限必须在 0% 到 30% 之间。")
    if not Decimal("0") < config.max_etf_total_weight <= Decimal("0.50"):
        raise ValueError("ETF 总仓位上限必须在 0% 到 50% 之间。")
    if not Decimal("0") < config.max_stock_total_weight <= Decimal("0.40"):
        raise ValueError("个股总仓位上限必须在 0% 到 40% 之间。")
    if not Decimal("0") < config.max_total_exposure <= Decimal("0.90"):
        raise ValueError("组合总仓位上限必须在 0% 到 90% 之间。")
    if not Decimal("0.10") <= config.min_cash_ratio < Decimal("1"):
        raise ValueError("最低现金比例不能低于 10%。")
    if not 1 <= config.max_operations_per_symbol <= 10:
        raise ValueError("单标的每日操作上限必须在 1 到 10 笔之间。")
    for field, label in (
        ("max_drawdown", "组合最大回撤"),
        ("single_position_loss", "单标的止损阈值"),
        ("trailing_drawdown", "移动回撤阈值"),
        ("portfolio_daily_loss", "组合单日亏损阈值"),
        ("high_atr_ratio", "高波动 ATR 阈值"),
    ):
        value = getattr(config, field)
        if not Decimal("0") < value < Decimal("1"):
            raise ValueError(f"{label}必须在 0% 到 100% 之间。")


def resolve_risk_config(config: AppConfig, store: Any) -> RiskConfig:
    if not hasattr(store, "load_active_risk_config"):
        return config.risk
    payload = store.load_active_risk_config()
    if not payload:
        return config.risk
    try:
        return parse_risk_config(config.risk, payload)
    except (TypeError, ValueError):
        return config.risk
