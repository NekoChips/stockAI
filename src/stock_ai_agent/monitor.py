from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time
from decimal import Decimal
from pathlib import Path
from typing import Callable, List, Optional, Protocol
from zoneinfo import ZoneInfo

from .config import AppConfig
from .data.providers import create_market_data_provider
from .features import build_features
from .journal import generate_daily_report
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
from .strategy import StrategyContext, TechnicalCompositeStrategy, aggregate_signals
from .universe import Universe


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


@dataclass(frozen=True)
class MonitorIterationResult:
    status: str
    message: str
    portfolio: Portfolio
    decisions: List[Decision]
    fills: List[Fill]
    report_path: Optional[Path] = None


class RealTimePaperTradingMonitor:
    def __init__(
        self,
        config: AppConfig,
        store: PaperTradingStore,
        quote_provider=None,
        output_dir: str | Path = "reports",
    ) -> None:
        self.config = config
        self.store = store
        self.quote_provider = quote_provider or create_market_data_provider(config)
        self.output_dir = output_dir
        self.timezone = ZoneInfo(config.timezone)
        self._reported_dates: set[date] = set()

    def run_iteration(self, now: datetime | None = None, ignore_market_hours: bool = False) -> MonitorIterationResult:
        local_now = self._local_now(now)
        trade_date = local_now.date()
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)

        if self.config.monitor.settle_on_start:
            self.store.settle_t_plus_one(trade_date)
            portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)

        if self.config.monitor.respect_market_hours and not ignore_market_hours and not is_trading_time(local_now):
            return MonitorIterationResult("skipped", "当前不在 A 股连续竞价交易时段，跳过本轮盯盘。", portfolio, [], [])

        universe = Universe.from_config(self.config.universe)
        risk = RiskEngine(self.config.risk, universe)
        broker = PaperBroker(portfolio, self.config.paper_account.fee_rate, self.config.paper_account.slippage_rate)
        interval = str(self.config.data.history.get("interval", "daily"))
        history_limit = int(self.config.data.history.get("monitor_history_limit", 80))
        bars_by_symbol = {
            instrument.symbol: self.store.load_bars(instrument.symbol, interval=interval, limit=history_limit)
            for instrument in universe.instruments
        }
        histories = {symbol: [bar.close_price for bar in bars] for symbol, bars in bars_by_symbol.items()}
        decisions: List[Decision] = []
        fills: List[Fill] = []

        for instrument in universe.instruments:
            bars = bars_by_symbol.get(instrument.symbol, [])
            if not bars:
                continue
            quote = self.quote_provider.get_quote(instrument.symbol)
            if instrument.symbol in portfolio.positions:
                portfolio.positions[instrument.symbol].last_price = quote.latest_price
            features = build_features(instrument.symbol, bars, quote)
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
        return MonitorIterationResult("traded", f"已完成 {trade_date.isoformat()} 一轮实时盯盘模拟。", portfolio, decisions, fills)

    def generate_post_close_report(self, report_date: date | None = None) -> Path:
        report_date = report_date or datetime.now(self.timezone).date()
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
        if hasattr(self.store, "record_portfolio_snapshot"):
            self.store.record_portfolio_snapshot(report_date, portfolio)
        decisions = self.store.load_decisions(report_date)
        fills = self.store.load_fills(report_date)
        return generate_daily_report(report_date, portfolio, decisions, fills, self.output_dir)

    def run_forever(
        self,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        on_update: Callable[[MonitorIterationResult], None] | None = None,
        ignore_market_hours: bool = False,
    ) -> None:
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            local_now = self._local_now()
            if is_post_close_report_time(local_now, self.config.monitor.post_close_report_time) and local_now.date() not in self._reported_dates:
                report_path = self.generate_post_close_report(local_now.date())
                portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                result = MonitorIterationResult("reported", "已生成收盘日报。", portfolio, [], [], report_path)
                self._reported_dates.add(local_now.date())
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
