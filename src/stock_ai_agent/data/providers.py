from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable, List

from ..config import AppConfig
from ..models import Bar, Quote
from .akshare_provider import AKShareAdapter
from .alphafeed import AlphaFeedAdapter
from .biying import BiyingAPIAdapter
from .eastmoney import EastmoneyPublicAdapter


class HistoryDataError(RuntimeError):
    """Raised when every configured historical data source fails."""


class CircuitBreaker:
    """Fail fast for a provider during an outage, then allow a later probe."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 120.0, monotonic_fn: Callable[[], float] = time.monotonic) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.monotonic_fn = monotonic_fn
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = Lock()

    def allow_request(self) -> bool:
        now = self.monotonic_fn()
        with self._lock:
            if self._opened_at is None:
                return True
            if self._probe_in_flight:
                return False
            if now - self._opened_at >= self.cooldown_seconds:
                self._probe_in_flight = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self, rate_limited: bool = False, cooldown_seconds: float | None = None) -> None:
        with self._lock:
            self._failures = self.failure_threshold if rate_limited else self._failures + 1
            if self._failures >= self.failure_threshold:
                if cooldown_seconds is not None:
                    self.cooldown_seconds = max(0.0, float(cooldown_seconds))
                self._opened_at = self.monotonic_fn()
                self._probe_in_flight = False


def _failure_cooldown(exc: Exception, network: float, rate_limit: float, capability: float) -> float:
    if bool(getattr(exc, "rate_limited", False)):
        return max(rate_limit, float(getattr(exc, "retry_after_seconds", 0) or 0))
    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status_code == 429:
        return max(rate_limit, float(getattr(exc, "retry_after_seconds", 0) or 0))
    if status_code is not None and int(status_code) >= 500:
        return network
    text = f"{type(exc).__name__} {exc}".lower()
    if any(token in text for token in ("unsupported", "not support", "capability", "missing api key", "缺少", "不支持")):
        return capability
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
        token in text for token in ("remote disconnected", "connection reset", "timeout", "timed out", "temporarily unavailable")
    ):
        return network
    return network


class FallbackHistoryDataProvider:
    def __init__(
        self,
        providers: list[tuple[str, Any]],
        attempts: int = 2,
        backoff_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        failure_threshold: int = 3,
        cooldown_seconds: float = 120.0,
        fallback_attempts: int = 2,
        fallback_backoff_seconds: float = 15.0,
        network_cooldown_seconds: float = 15.0,
        rate_limit_cooldown_seconds: float = 60.0,
        capability_cooldown_seconds: float = 300.0,
    ) -> None:
        self.providers = providers
        self.attempts = max(1, int(attempts))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.sleep_fn = sleep_fn
        self.last_source = ""
        self._breakers = {name: CircuitBreaker(failure_threshold, cooldown_seconds) for name, _ in providers}
        self.fallback_attempts = max(1, int(fallback_attempts))
        self.fallback_backoff_seconds = max(0.0, float(fallback_backoff_seconds))
        self.network_cooldown_seconds = max(0.0, float(network_cooldown_seconds))
        self.rate_limit_cooldown_seconds = max(0.0, float(rate_limit_cooldown_seconds))
        self.capability_cooldown_seconds = max(0.0, float(capability_cooldown_seconds))

    def get_bars(self, symbol: str, interval: str = "daily", start: str = "20200101", end: str = "20500101", adjust: str = "qfq") -> List[Bar]:
        return self._call(
            "get_bars",
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            adjust=adjust,
        )

    def get_index_bars(self, symbol: str, akshare_symbol: str, start: str = "20200101", end: str = "20500101") -> List[Bar]:
        return self._call(
            "get_index_bars",
            symbol=symbol,
            akshare_symbol=akshare_symbol,
            start=start,
            end=end,
        )

    def get_bars_batch(
        self,
        symbols: list[str],
        interval: str = "daily",
        start: str = "20200101",
        end: str = "20500101",
        adjust: str = "qfq",
    ) -> dict[str, List[Bar]]:
        failures: list[str] = []
        for source_name, provider in self.providers:
            breaker = self._breakers[source_name]
            if not breaker.allow_request():
                failures.append(f"{source_name}: 熔断冷却中")
                continue
            method = getattr(provider, "get_bars_batch", None)
            try:
                if method is not None:
                    result = method(symbols, interval=interval, start=start, end=end, adjust=adjust)
                else:
                    result = {
                        symbol: provider.get_bars(symbol, interval=interval, start=start, end=end, adjust=adjust)
                        for symbol in symbols
                    }
                if not result or any(not result.get(symbol) for symbol in symbols):
                    raise HistoryDataError(f"{source_name} 返回不完整 K 线")
                breaker.record_success()
                self.last_source = source_name
                return result
            except Exception as exc:  # noqa: BLE001 - external providers raise mixed exceptions
                breaker.record_failure(
                    rate_limited=bool(getattr(exc, "rate_limited", False)),
                    cooldown_seconds=_failure_cooldown(
                        exc,
                        self.network_cooldown_seconds,
                        self.rate_limit_cooldown_seconds,
                        self.capability_cooldown_seconds,
                    ),
                )
                failures.append(f"{source_name}: {exc}")
        raise HistoryDataError(f"历史 K 线所有数据源均失败：{'；'.join(failures)}")

    def _call(self, method_name: str, **kwargs: object) -> List[Bar]:
        failures: list[str] = []
        for provider_index, (source_name, provider) in enumerate(self.providers):
            breaker = self._breakers[source_name]
            if not breaker.allow_request():
                failures.append(f"{source_name}: 熔断冷却中")
                continue
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
            attempt_limit = self.attempts if provider_index == 0 else self.fallback_attempts
            backoff_seconds = self.backoff_seconds if provider_index == 0 else self.fallback_backoff_seconds
            for attempt in range(attempt_limit):
                try:
                    bars = method(**call_kwargs)
                    if not bars:
                        raise HistoryDataError(f"{source_name} 返回空 K 线")
                    breaker.record_success()
                    self.last_source = source_name
                    return bars
                except Exception as exc:  # noqa: BLE001 - external providers raise mixed exceptions
                    failures.append(f"{source_name} 第 {attempt + 1}/{attempt_limit} 次失败：{exc}")
                    rate_limited = bool(getattr(exc, "rate_limited", False))
                    breaker.record_failure(
                        rate_limited=rate_limited,
                        cooldown_seconds=_failure_cooldown(
                            exc,
                            self.network_cooldown_seconds,
                            self.rate_limit_cooldown_seconds,
                            self.capability_cooldown_seconds,
                        ),
                    )
                    if rate_limited:
                        break
                    if attempt + 1 < attempt_limit and backoff_seconds > 0:
                        self.sleep_fn(backoff_seconds * (2**attempt))
        detail = "；".join(failures)
        raise HistoryDataError(f"历史 K 线所有数据源均失败：{detail}")


class FallbackMarketDataProvider:
    """Try the primary quote source, then fall back to configured providers."""

    def __init__(
        self,
        providers: list[tuple[str, Any]],
        failure_threshold: int = 3,
        cooldown_seconds: float = 120.0,
        network_cooldown_seconds: float = 15.0,
        rate_limit_cooldown_seconds: float = 60.0,
        capability_cooldown_seconds: float = 300.0,
    ) -> None:
        self.providers = providers
        self.last_source = ""
        self._breakers = {name: CircuitBreaker(failure_threshold, cooldown_seconds) for name, _ in providers}
        self.network_cooldown_seconds = max(0.0, float(network_cooldown_seconds))
        self.rate_limit_cooldown_seconds = max(0.0, float(rate_limit_cooldown_seconds))
        self.capability_cooldown_seconds = max(0.0, float(capability_cooldown_seconds))

    def get_quote(self, symbol: str):
        return self.get_quotes([symbol])[symbol]

    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        failures: list[str] = []
        remaining = list(dict.fromkeys(symbols))
        merged: dict[str, Any] = {}
        for source_name, provider in self.providers:
            if not remaining:
                break
            breaker = self._breakers[source_name]
            if not breaker.allow_request():
                failures.append(f"{source_name}: 熔断冷却中")
                continue
            try:
                method = getattr(provider, "get_quotes", None)
                if method is not None:
                    quotes = method(remaining)
                else:
                    quotes = {}
                    for symbol in remaining:
                        try:
                            quotes[symbol] = provider.get_quote(symbol)
                        except Exception as exc:  # noqa: BLE001 - fall through per symbol
                            failures.append(f"{source_name}/{symbol}: {exc}")
                valid = {symbol: quote for symbol, quote in (quotes or {}).items() if isinstance(quote, Quote) and symbol in remaining}
                if valid:
                    merged.update(valid)
                    remaining = [symbol for symbol in remaining if symbol not in valid]
                    breaker.record_success()
                    self.last_source = source_name
                if remaining:
                    failures.append(f"{source_name} 返回不完整实时行情，缺少：{','.join(remaining)}")
                    continue
                return merged
            except Exception as exc:  # noqa: BLE001 - external providers raise mixed exceptions
                breaker.record_failure(
                    rate_limited=bool(getattr(exc, "rate_limited", False)),
                    cooldown_seconds=_failure_cooldown(
                        exc,
                        self.network_cooldown_seconds,
                        self.rate_limit_cooldown_seconds,
                        self.capability_cooldown_seconds,
                    ),
                )
                failures.append(f"{source_name}: {exc}")
        if merged and not remaining:
            return merged
        raise RuntimeError(f"实时行情所有数据源均失败：{'；'.join(failures)}")

    def list_instruments(self):
        failures: list[str] = []
        for source_name, provider in self.providers:
            breaker = self._breakers[source_name]
            if not breaker.allow_request():
                failures.append(f"{source_name}: 熔断冷却中")
                continue
            method = getattr(provider, "list_instruments", None)
            if method is None:
                continue
            try:
                items = method()
                if items:
                    breaker.record_success()
                    self.last_source = source_name
                    return items
                failures.append(f"{source_name}: 返回空目录")
            except Exception as exc:  # noqa: BLE001 - external providers raise mixed exceptions
                breaker.record_failure(
                    rate_limited=bool(getattr(exc, "rate_limited", False)),
                    cooldown_seconds=_failure_cooldown(exc, self.network_cooldown_seconds, self.rate_limit_cooldown_seconds, self.capability_cooldown_seconds),
                )
                failures.append(f"{source_name}: {exc}")
        raise RuntimeError(f"证券目录所有数据源均失败：{'；'.join(failures)}")


def fetch_quotes(provider: Any, symbols: list[str]) -> dict[str, Any]:
    method = getattr(provider, "get_quotes", None)
    if method is not None:
        return method(symbols)
    return {symbol: provider.get_quote(symbol) for symbol in symbols}


def _create_provider(config: AppConfig, name: str):
    if name == "alphafeed":
        return AlphaFeedAdapter(config.data.providers.get("alphafeed", {}), config.data.freshness_seconds)
    if name == "akshare":
        return AKShareAdapter(config.data.providers.get("akshare", {}), config.data.freshness_seconds)
    if name == "biying":
        return BiyingAPIAdapter(config.data.providers.get("biying", {}), config.data.freshness_seconds)
    if name == "eastmoney_public":
        return EastmoneyPublicAdapter(config.data.freshness_seconds)
    raise ValueError(f"暂不支持的行情数据源：{name}")


def create_market_data_provider(config: AppConfig, provider_name: str | None = None):
    if provider_name:
        return _create_provider(config, provider_name)
    names = [config.data.provider, *config.data.market_fallback_providers]
    provider_options = config.data.providers.get(config.data.provider, {})
    return FallbackMarketDataProvider(
        [(name, _create_provider(config, name)) for name in dict.fromkeys(names)],
        failure_threshold=int(provider_options.get("circuit_breaker_failure_threshold", 3)),
        cooldown_seconds=float(provider_options.get("circuit_breaker_cooldown_seconds", 120)),
        network_cooldown_seconds=float(provider_options.get("network_circuit_breaker_cooldown_seconds", 15)),
        rate_limit_cooldown_seconds=float(provider_options.get("rate_limit_circuit_breaker_cooldown_seconds", provider_options.get("circuit_breaker_cooldown_seconds", 60))),
        capability_cooldown_seconds=float(provider_options.get("capability_circuit_breaker_cooldown_seconds", 300)),
    )


def create_history_data_provider(config: AppConfig, provider_name: str | None = None):
    if provider_name:
        return create_market_data_provider(config, provider_name)
    names = [config.data.history_provider, *config.data.history_fallback_providers]
    providers = [(name, create_market_data_provider(config, name)) for name in dict.fromkeys(names)]
    history = config.data.history
    provider_options = config.data.providers.get(config.data.history_provider, {})
    return FallbackHistoryDataProvider(
        providers,
        attempts=int(history.get("retry_attempts", 2)),
        backoff_seconds=float(history.get("retry_backoff_seconds", 1)),
        failure_threshold=int(history.get("circuit_breaker_failure_threshold", 3)),
        cooldown_seconds=float(history.get("circuit_breaker_cooldown_seconds", 120)),
        fallback_attempts=int(history.get("fallback_retry_attempts", 2)),
        fallback_backoff_seconds=float(history.get("fallback_retry_backoff_seconds", 15)),
        network_cooldown_seconds=float(provider_options.get("network_circuit_breaker_cooldown_seconds", 15)),
        rate_limit_cooldown_seconds=float(provider_options.get("rate_limit_circuit_breaker_cooldown_seconds", history.get("circuit_breaker_cooldown_seconds", 60))),
        capability_cooldown_seconds=float(provider_options.get("capability_circuit_breaker_cooldown_seconds", 300)),
    )
