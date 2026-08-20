from __future__ import annotations

import time
from typing import Any, Callable, List

from ..config import AppConfig
from ..models import Bar
from .akshare_provider import AKShareAdapter
from .biying import BiyingAPIAdapter
from .eastmoney import EastmoneyPublicAdapter


class HistoryDataError(RuntimeError):
    """Raised when every configured historical data source fails."""


class FallbackHistoryDataProvider:
    def __init__(
        self,
        providers: list[tuple[str, Any]],
        attempts: int = 2,
        backoff_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.providers = providers
        self.attempts = max(1, int(attempts))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.sleep_fn = sleep_fn
        self.last_source = ""

    def get_bars(self, symbol: str, interval: str = "daily", start: str = "20240101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        return self._call(
            "get_bars",
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            adjust=adjust,
        )

    def get_index_bars(self, symbol: str, akshare_symbol: str, start: str = "20240101", end: str = "20500101") -> List[Bar]:
        return self._call(
            "get_index_bars",
            symbol=symbol,
            akshare_symbol=akshare_symbol,
            start=start,
            end=end,
        )

    def _call(self, method_name: str, **kwargs: object) -> List[Bar]:
        failures: list[str] = []
        for source_name, provider in self.providers:
            call_kwargs = dict(kwargs)
            method = getattr(provider, method_name, None)
            if method is None and method_name == "get_index_bars":
                method = getattr(provider, "get_bars", None)
                if method is not None:
                    call_kwargs = {
                        "symbol": call_kwargs["symbol"],
                        "interval": "daily",
                        "start": call_kwargs["start"],
                        "end": call_kwargs["end"],
                        "adjust": "qfq",
                    }
            if method is None:
                failures.append(f"{source_name}: 不支持 {method_name}")
                continue
            for attempt in range(self.attempts):
                try:
                    bars = method(**call_kwargs)
                    if not bars:
                        raise HistoryDataError(f"{source_name} 返回空 K 线")
                    self.last_source = source_name
                    return bars
                except Exception as exc:  # noqa: BLE001 - external providers raise mixed exceptions
                    failures.append(f"{source_name} 第 {attempt + 1}/{self.attempts} 次失败：{exc}")
                    if attempt + 1 < self.attempts and self.backoff_seconds > 0:
                        self.sleep_fn(self.backoff_seconds * (2**attempt))
        detail = "；".join(failures)
        raise HistoryDataError(f"历史 K 线所有数据源均失败：{detail}")


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
    if provider_name:
        return create_market_data_provider(config, provider_name)
    names = [config.data.history_provider, *config.data.history_fallback_providers]
    providers = [(name, create_market_data_provider(config, name)) for name in dict.fromkeys(names)]
    history = config.data.history
    return FallbackHistoryDataProvider(
        providers,
        attempts=int(history.get("retry_attempts", 2)),
        backoff_seconds=float(history.get("retry_backoff_seconds", 1)),
    )
