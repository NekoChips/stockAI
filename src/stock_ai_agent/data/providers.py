from __future__ import annotations

from ..config import AppConfig
from .akshare_provider import AKShareAdapter
from .biying import BiyingAPIAdapter
from .eastmoney import EastmoneyPublicAdapter


def create_market_data_provider(config: AppConfig, provider_name: str | None = None):
    name = provider_name or config.data.provider
    if name == "akshare":
        return AKShareAdapter(config.data.providers.get("akshare", {}), config.data.freshness_seconds)
    if name == "biying":
        return BiyingAPIAdapter(config.data.providers.get("biying", {}), config.data.freshness_seconds)
    if name == "eastmoney_public":
        return EastmoneyPublicAdapter(config.data.freshness_seconds)
    raise ValueError(f"暂不支持的行情数据源：{name}")


def create_history_data_provider(config: AppConfig, provider_name: str | None = None):
    return create_market_data_provider(config, provider_name or config.data.history_provider)
