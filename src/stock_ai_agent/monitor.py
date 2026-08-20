from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as clock_time
from decimal import Decimal
from threading import Thread
from typing import Callable, List, Optional, Protocol
from zoneinfo import ZoneInfo

from .config import AppConfig
from .data.providers import create_history_data_provider, create_market_data_provider
from .features import build_features
from .journal import build_daily_report
from .models import Bar, Decision, Fill, Portfolio
from .paper_broker import PaperBroker, PaperBrokerError
from .quant_strategies import (
    DrawdownControlStrategy,
    MeanReversionStrategy,
    QuantContext,
    RelativeStrengthRotationStrategy,
    TimeSeriesMomentumStrategy,
    VolatilityTargetStrategy,
)
from .risk import RiskEngine
from .reference_data import sync_benchmark_history, sync_instrument_catalog
from .strategy import StrategyContext, TechnicalCompositeStrategy, aggregate_signals
from .universe import Universe
from .watchlist import effective_watchlist


class PaperTradingStore(Protocol):
    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> List[Bar]:
        ...

    def load_portfolio(self, initial_cash: Decimal) -> Portfolio:
        ...

    def save_portfolio(self, portfolio: Portfolio) -> None:
        ...

    def record_decision(self, decision: Decision, trade_date: date) -> None:
        ...

    def load_decisions(self, trade_date: date) -> List[Decision]:
        ...

    def record_fill(self, fill: Fill, trade_date: date | None = None) -> None:
        ...

    def load_fills(self, trade_date: date) -> List[Fill]:
        ...

    def count_fills(self, trade_date: date) -> int:
        ...

    def settle_t_plus_one(self, settle_date: date | None = None) -> bool:
        ...

    def save_daily_report(self, report: dict) -> None:
        ...

    def load_portfolio_snapshots(self) -> list[tuple[date, Decimal]]:
        ...


@dataclass(frozen=True)
class MonitorIterationResult:
    status: str
    message: str
    portfolio: Portfolio
    decisions: List[Decision]
    fills: List[Fill]
    report: Optional[dict] = None
    warnings: List[str] = field(default_factory=list)


class RealTimePaperTradingMonitor:
    def __init__(
        self,
        config: AppConfig,
        store: PaperTradingStore,
        quote_provider=None,
        history_provider=None,
    ) -> None:
        self.config = config
        self.store = store
        self.quote_provider = quote_provider or create_market_data_provider(config)
        self.history_provider = history_provider or create_history_data_provider(config)
        self.timezone = ZoneInfo(config.timezone)
        self._reported_dates: set[date] = set()
        self._reference_sync_attempted_dates: set[date] = set()
        self._trading_data_ready = False
        self._initialization_warnings: list[str] = []

    def run_iteration(self, now: datetime | None = None, ignore_market_hours: bool = False) -> MonitorIterationResult:
        local_now = self._local_now(now)
        trade_date = local_now.date()
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)

        self._sync_daily_reference_data(trade_date)

        if self.config.monitor.settle_on_start:
            self.store.settle_t_plus_one(trade_date)
            portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)

        if self.config.monitor.respect_market_hours and not ignore_market_hours and not is_trading_time(local_now):
            return MonitorIterationResult("skipped", "当前不在 A 股连续竞价交易时段，跳过本轮盯盘。", portfolio, [], [])

        universe = Universe.from_config(effective_watchlist(self.config, self.store))
        risk = RiskEngine(self.config.risk, universe)
        broker = PaperBroker(portfolio, self.config.paper_account.fee_rate, self.config.paper_account.slippage_rate)
        interval = str(self.config.data.history.get("interval", "daily"))
        history_limit = int(self.config.data.history.get("monitor_history_limit", 80))
        minimum_history_bars = int(self.config.data.history.get("monitor_minimum_bars", 35))
        bars_by_symbol = {
            instrument.symbol: self.store.load_bars(instrument.symbol, interval=interval, limit=history_limit)
            for instrument in universe.instruments
        }
        histories = {symbol: [bar.close_price for bar in bars] for symbol, bars in bars_by_symbol.items()}
        decisions: List[Decision] = []
        fills: List[Fill] = []
        warnings: List[str] = []

        for instrument in universe.instruments:
            bars = bars_by_symbol.get(instrument.symbol, [])
            if len(bars) < minimum_history_bars:
                warnings.append(
                    f"{instrument.symbol} 历史 K 线不足，至少需要 {minimum_history_bars} 条，当前 {len(bars)} 条。"
                )
                continue
            try:
                quote = self.quote_provider.get_quote(instrument.symbol)
            except Exception as exc:  # noqa: BLE001 - provider errors must not stop the monitor loop
                warnings.append(f"{instrument.symbol} 实时行情获取失败：{exc}")
                continue
            if instrument.symbol in portfolio.positions:
                portfolio.positions[instrument.symbol].last_price = quote.latest_price
            try:
                features = build_features(instrument.symbol, bars, quote)
            except Exception as exc:  # noqa: BLE001 - malformed external data is isolated per symbol
                warnings.append(f"{instrument.symbol} 指标计算失败：{exc}")
                continue
            current_weights = {symbol: portfolio.position_weight(symbol) for symbol in portfolio.positions}
            strategy_context = StrategyContext(current_weights)
            quant_context = QuantContext(
                histories=histories,
                current_weights=current_weights,
                peak_values={instrument.symbol: Decimal("1")},
                current_values={instrument.symbol: Decimal("1")},
            )
            signals = [
                TechnicalCompositeStrategy().evaluate(features, strategy_context),
                TimeSeriesMomentumStrategy(self.config.strategy.quant.get("lookback_days", 20)).evaluate(instrument.symbol, features, quant_context),
                MeanReversionStrategy(Decimal(str(self.config.strategy.quant.get("mean_reversion_z", "-1.2")))).evaluate(instrument.symbol, features, quant_context),
                RelativeStrengthRotationStrategy(self.config.strategy.quant.get("lookback_days", 20)).evaluate(instrument.symbol, features, quant_context),
                VolatilityTargetStrategy(self.config.risk.high_atr_ratio).evaluate(instrument.symbol, features, quant_context),
                DrawdownControlStrategy(Decimal(str(self.config.strategy.quant.get("drawdown_stop", "0.08")))).evaluate(instrument.symbol, features, quant_context),
            ]
            aggregate = aggregate_signals(signals, self.config.strategy.weights)
            daily_trade_count = self.store.count_fills(trade_date) + len(fills)
            risk_result = risk.evaluate(aggregate, portfolio, quote, daily_trade_count=daily_trade_count)
            decisions.append(risk_result.decision)
            self.store.record_decision(risk_result.decision, trade_date)
            if not risk_result.order:
                continue
            try:
                fill = broker.execute(risk_result.order)
            except PaperBrokerError as exc:
                rejected = Decision(
                    risk_result.order.symbol,
                    risk_result.order.direction,
                    risk_result.decision.target_weight,
                    False,
                    [str(exc)],
                    aggregate,
                )
                decisions.append(rejected)
                self.store.record_decision(rejected, trade_date)
                continue
            fills.append(fill)
            self.store.record_fill(fill, trade_date)

        self.store.save_portfolio(portfolio)
        status = "degraded" if warnings else "traded"
        message = f"已完成 {trade_date.isoformat()} 一轮实时盯盘模拟。"
        if warnings:
            message += " 告警：" + "；".join(warnings)
        return MonitorIterationResult(status, message, portfolio, decisions, fills, warnings=warnings)

    def generate_post_close_report(self, report_date: date | None = None) -> dict:
        report_date = report_date or datetime.now(self.timezone).date()
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
        snapshots = self.store.load_portfolio_snapshots() if hasattr(self.store, "load_portfolio_snapshots") else []
        previous_total_asset = next(
            (value for snapshot_date, value in reversed(snapshots) if snapshot_date < report_date),
            self.config.paper_account.initial_cash,
        )
        if hasattr(self.store, "record_portfolio_snapshot"):
            self.store.record_portfolio_snapshot(report_date, portfolio)
        decisions = self.store.load_decisions(report_date)
        fills = self.store.load_fills(report_date)
        system_notes = list(self._initialization_warnings)
        if not self._trading_data_ready and not system_notes:
            system_notes.append("观察池历史数据尚未完成初始化，当日未进入策略执行阶段。")
        report = build_daily_report(
            report_date,
            portfolio,
            decisions,
            fills,
            previous_total_asset,
            system_notes=system_notes,
        )
        self.store.save_daily_report(report)
        return report

    def initialize_trading_data(self, trade_date: date | None = None) -> tuple[bool, list[str]]:
        """Prepare persistent reference data before the monitor may evaluate a strategy."""
        trade_date = trade_date or datetime.now(self.timezone).date()
        warnings: list[str] = []
        warnings.extend(self._sync_watchlist_history(force=True))
        missing = self._symbols_with_insufficient_history()
        if missing:
            warnings.append("观察池历史 K 线未就绪：" + "、".join(missing))
            self._initialization_warnings = warnings
            self._trading_data_ready = False
            return False, warnings
        self._initialization_warnings = warnings
        self._trading_data_ready = True
        self._reference_sync_attempted_dates.add(trade_date)
        Thread(
            target=self._sync_reference_data_in_background,
            args=(trade_date, False),
            daemon=True,
        ).start()
        return True, warnings

    def run_forever(
        self,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        on_update: Callable[[MonitorIterationResult], None] | None = None,
        ignore_market_hours: bool = False,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            local_now = self._local_now(now_fn() if now_fn else None)
            if is_post_close_report_time(local_now, self.config.monitor.post_close_report_time) and local_now.date() not in self._reported_dates:
                report = self.generate_post_close_report(local_now.date())
                portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                result = MonitorIterationResult("reported", "收盘日报已归档到数据库。", portfolio, [], [], report)
                self._reported_dates.add(local_now.date())
            elif not self._trading_data_ready:
                ready, warnings = self.initialize_trading_data(local_now.date())
                if not ready:
                    portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                    result = MonitorIterationResult(
                        "initializing",
                        "交易数据尚未就绪，本轮不执行策略；monitor 将自动重试。",
                        portfolio,
                        [],
                        [],
                        warnings=warnings,
                    )
                else:
                    result = self.run_iteration(local_now, ignore_market_hours=ignore_market_hours)
                    if warnings:
                        result = MonitorIterationResult(
                            "degraded",
                            result.message + " 启动数据存在非阻断告警。",
                            result.portfolio,
                            result.decisions,
                            result.fills,
                            result.report,
                            [*warnings, *result.warnings],
                        )
            else:
                result = self.run_iteration(local_now, ignore_market_hours=ignore_market_hours)
            if on_update:
                on_update(result)
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            sleep_fn(float(self.config.monitor.poll_seconds))

    def _local_now(self, now: datetime | None = None) -> datetime:
        current = now or datetime.now(self.timezone)
        if current.tzinfo is None:
            return current.replace(tzinfo=self.timezone)
        return current.astimezone(self.timezone)

    def _sync_daily_reference_data(self, trade_date: date) -> None:
        if trade_date in self._reference_sync_attempted_dates:
            return
        self._reference_sync_attempted_dates.add(trade_date)
        Thread(target=self._sync_reference_data_in_background, args=(trade_date,), daemon=True).start()

    def _sync_reference_data_in_background(self, trade_date: date, refresh_history: bool = True) -> None:
        """Reference data must not delay a market-hours trading iteration."""
        if hasattr(self.quote_provider, "list_instruments"):
            try:
                sync_instrument_catalog(self.config, self.store, self.quote_provider, trade_date.isoformat())
            except Exception:
                pass
        if refresh_history:
            try:
                self._sync_watchlist_history(force=True)
            except Exception:
                pass
        try:
            sync_benchmark_history(self.config, self.store, self.history_provider)
        except Exception:
            pass

    def _sync_watchlist_history(self, force: bool) -> list[str]:
        history = self.config.data.history
        interval = str(history.get("interval", "daily"))
        start = str(history.get("start", "20240101"))
        end = str(history.get("end", "20500101"))
        adjust = str(history.get("adjust", "qfq"))
        minimum = int(history.get("monitor_minimum_bars", 35))
        warnings: list[str] = []
        for instrument in effective_watchlist(self.config, self.store):
            if not force and len(self.store.load_bars(instrument.symbol, interval=interval, limit=minimum)) >= minimum:
                continue
            try:
                bars = self.history_provider.get_bars(
                    instrument.symbol,
                    interval=interval,
                    start=start,
                    end=end,
                    adjust=adjust,
                )
                source = getattr(self.history_provider, "last_source", "") or self.config.data.history_provider
                self.store.save_bars(bars, interval=interval, source=source)
            except Exception as exc:  # noqa: BLE001 - retry is handled by the monitor lifecycle
                warnings.append(f"{instrument.symbol} 历史 K 线同步失败：{exc}")
        return warnings

    def _symbols_with_insufficient_history(self) -> list[str]:
        interval = str(self.config.data.history.get("interval", "daily"))
        minimum = int(self.config.data.history.get("monitor_minimum_bars", 35))
        return [
            instrument.symbol
            for instrument in effective_watchlist(self.config, self.store)
            if len(self.store.load_bars(instrument.symbol, interval=interval, limit=minimum)) < minimum
        ]


def is_trading_time(now: datetime) -> bool:
    local_time = now.timetz().replace(tzinfo=None)
    if now.weekday() >= 5:
        return False
    morning = clock_time(9, 30) <= local_time <= clock_time(11, 30)
    afternoon = clock_time(13, 0) <= local_time <= clock_time(15, 0)
    return morning or afternoon


def is_post_close_report_time(now: datetime, configured_time: str) -> bool:
    hour, minute = [int(part) for part in configured_time.split(":", 1)]
    return now.weekday() < 5 and now.timetz().replace(tzinfo=None) >= clock_time(hour, minute)
