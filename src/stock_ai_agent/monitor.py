from __future__ import annotations

import time
import logging
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time as clock_time, timedelta
from decimal import Decimal
from threading import Thread
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

from .config import AppConfig
from .data.providers import create_history_data_provider, create_market_data_provider, fetch_quotes
from .data.analysis_sources import default_quant_seats, fetch_futures_positions, fetch_korea_market_data, fetch_lhb_data, fetch_us_market_data
from .data.external_market import DEFAULT_US_SPECS, sync_external_market_data
from .lhb_backtest import refresh_lhb_seat_profiles
from .features import build_features
from .history_sync import sync_watchlist_history
from .journal import build_daily_report
from .models import Bar, Decision, Direction, Fill, OrderStatus, Portfolio
from .paper_broker import PaperBroker, PaperBrokerError
from .quant_strategies import QuantContext
from .risk import RiskEngine
from .risk_config import resolve_risk_config
from .reference_data import sync_benchmark_history, sync_instrument_catalog, sync_sector_mappings
from .strategy import StrategyContext, aggregate_signals
from .strategy_runtime import evaluate_strategy_profile, load_external_strategy_context, resolve_strategy_profile
from .storage.base import MarketDataStore
from .trading_round import execute_order_state_machine
from .trading_calendar import AShareTradingCalendar
from .universe import Universe
from .watchlist import effective_watchlist


logger = logging.getLogger(__name__)
MAX_TRACKED_DATES = 90


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
        store: MarketDataStore,
        quote_provider=None,
        history_provider=None,
        trading_day_checker: Callable[[date], bool] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.quote_provider = quote_provider or create_market_data_provider(config)
        self.history_provider = history_provider or create_history_data_provider(config)
        self.external_history_provider = create_market_data_provider(config, "alphafeed")
        self.timezone = ZoneInfo(config.timezone)
        self._reported_dates: deque[date] = deque(maxlen=MAX_TRACKED_DATES)
        self._decision_compaction_attempted_dates: deque[date] = deque(maxlen=MAX_TRACKED_DATES)
        self._decision_history_compaction_done = False
        self._quote_prune_attempted_dates: deque[date] = deque(maxlen=MAX_TRACKED_DATES)
        self._scheduled_task_dates: set[tuple[date, str]] = set()
        self._daily_kline_sync_attempted_windows: set[tuple[date, str]] = set()
        self._daily_kline_completed_dates: set[date] = set()
        self._automatic_backtest_started_dates: deque[date] = deque(maxlen=MAX_TRACKED_DATES)
        self._automatic_backtest_pending_dates: set[date] = set()
        self._last_strategy_run_at: datetime | None = None
        self._trading_data_ready = False
        self._initialization_warnings: list[str] = []
        if hasattr(store, "ensure_strategy_defaults"):
            store.ensure_strategy_defaults(config)
        if hasattr(store, "save_quant_seats"):
            store.save_quant_seats(default_quant_seats())
        calendar = AShareTradingCalendar(store) if config.environment == "release" else None
        self._is_trading_day = trading_day_checker or (calendar.is_trading_day if calendar else lambda value: value.weekday() < 5)

    def run_iteration(
        self,
        now: datetime | None = None,
        ignore_market_hours: bool = False,
        preloaded_quotes: dict[str, object] | None = None,
    ) -> MonitorIterationResult:
        local_now = self._local_now(now)
        trade_date = local_now.date()
        self._apply_pending_strategy_changes()
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)

        if (
            self.config.monitor.respect_market_hours
            and not ignore_market_hours
            and not is_trading_time(local_now, self._is_trading_day)
        ):
            return MonitorIterationResult("skipped", "当前不在 A 股连续竞价交易时段，跳过本轮盯盘。", portfolio, [], [])

        self._compact_watch_decisions(trade_date)
        self._prepare_intraday_quote_store(local_now)

        if self.config.monitor.settle_on_start:
            self.store.settle_t_plus_one(trade_date)
            portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)

        watchlist = effective_watchlist(self.config, self.store)
        held_symbols = set(portfolio.positions)
        universe = Universe.from_config(
            [
                item
                for item in watchlist
                if item.lifecycle_status != "dormant" and (item.trading_enabled or item.symbol in held_symbols)
            ]
        )
        active_risk = resolve_risk_config(self.config, self.store)
        risk = RiskEngine(active_risk, universe)
        strategy_profiles = {
            instrument.symbol: resolve_strategy_profile(
                self.config,
                self.store,
                instrument.symbol,
                instrument.asset_type,
            )
            for instrument in universe.instruments
        }
        broker = PaperBroker(
            portfolio,
            self.config.paper_account.fee_rate,
            self.config.paper_account.slippage_rate,
            min_commission=self.config.paper_account.min_commission,
            stock_sell_stamp_tax=self.config.paper_account.stock_sell_stamp_tax,
        )
        interval = str(self.config.data.history.get("interval", "daily"))
        history_limit = int(self.config.data.history.get("monitor_history_limit", 80))
        minimum_history_bars = int(self.config.data.history.get("monitor_minimum_bars", 35))
        symbols = [instrument.symbol for instrument in universe.instruments]
        bars_by_symbol = self.store.load_watchlist_bars_batch(symbols, interval=interval, limit=history_limit)
        histories = {symbol: [bar.close_price for bar in bars] for symbol, bars in bars_by_symbol.items()}
        decisions: List[Decision] = []
        fills: List[Fill] = []
        warnings: List[str] = []
        pending_symbols: set[str] = set()
        eligible_instruments = [
            instrument
            for instrument in universe.instruments
            if len(bars_by_symbol.get(instrument.symbol, [])) >= minimum_history_bars
        ]
        symbols = [instrument.symbol for instrument in universe.instruments]
        batch_quotes = preloaded_quotes
        batch_requested = bool(symbols and hasattr(self.quote_provider, "get_quotes"))
        if batch_requested and batch_quotes is None:
            try:
                batch_quotes = fetch_quotes(self.quote_provider, symbols)
            except Exception as exc:  # noqa: BLE001 - fallback provider errors are isolated from the loop
                warnings.extend([f"{symbol} 实时行情获取失败：{exc}" for symbol in symbols])
        if batch_quotes and preloaded_quotes is None:
            self.store.save_quotes(list(batch_quotes.values()))

        # Resume persisted submitted/partial orders before creating any fresh order.
        # This keeps a monitor restart from duplicating the same trade decision.
        if hasattr(self.store, "load_open_orders"):
            for pending in self.store.load_open_orders():
                pending_symbols.add(pending.symbol)
                if pending.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
                    warnings.append(f"{pending.symbol} 订单 {pending.order_id} 状态为 {pending.status.value}，等待后续处理。")
                    continue
                quote = batch_quotes.get(pending.symbol) if batch_quotes else None
                if quote is None:
                    continue
                attempt = broker.try_fill(pending, quote)
                if hasattr(self.store, "save_order"):
                    self.store.save_order(attempt.order, trade_date)
                if attempt.fill is not None:
                    fills.append(attempt.fill)
                    self.store.record_fill(attempt.fill, trade_date)

        snapshots = self.store.load_portfolio_snapshots()
        historical_peak = max((value for _, value in snapshots), default=self.config.paper_account.initial_cash)
        previous_total_asset = next(
            (value for snapshot_date, value in reversed(snapshots) if snapshot_date < trade_date),
            self.config.paper_account.initial_cash,
        )
        portfolio_daily_loss_hit = (
            previous_total_asset > 0
            and portfolio.total_asset() <= previous_total_asset * (Decimal("1") - active_risk.portfolio_daily_loss)
        )
        daily_trade_count = self.store.count_fills(trade_date)

        for instrument in universe.instruments:
            if instrument.symbol in pending_symbols:
                continue
            bars = bars_by_symbol.get(instrument.symbol, [])
            if len(bars) < minimum_history_bars:
                warnings.append(
                    f"{instrument.symbol} 历史 K 线不足，至少需要 {minimum_history_bars} 条，当前 {len(bars)} 条。"
                )
                continue
            if batch_requested:
                if batch_quotes is None:
                    continue
                quote = batch_quotes.get(instrument.symbol)
                if quote is None:
                    warnings.append(f"{instrument.symbol} 实时行情返回缺少标的。")
                    continue
            else:
                try:
                    quote = self.quote_provider.get_quote(instrument.symbol)
                except Exception as exc:  # noqa: BLE001 - provider errors must not stop the monitor loop
                    warnings.append(f"{instrument.symbol} 实时行情获取失败：{exc}")
                    continue
                self.store.save_quotes([quote])
            if instrument.symbol in portfolio.positions:
                portfolio.positions[instrument.symbol].last_price = quote.latest_price
            try:
                features = build_features(instrument.symbol, bars, quote)
            except Exception as exc:  # noqa: BLE001 - malformed external data is isolated per symbol
                warnings.append(f"{instrument.symbol} 指标计算失败：{exc}")
                continue
            current_weights = {symbol: portfolio.position_weight(symbol) for symbol in portfolio.positions}
            strategy_context = StrategyContext(current_weights)
            current_value = portfolio.total_asset()
            quant_context = QuantContext(
                histories=histories,
                current_weights=current_weights,
                peak_values={instrument.symbol: max(historical_peak, current_value)},
                current_values={instrument.symbol: current_value},
            )
            profile = strategy_profiles[instrument.symbol]
            signals = evaluate_strategy_profile(
                profile,
                instrument.symbol,
                features,
                strategy_context,
                quant_context,
                active_risk.high_atr_ratio,
                load_external_strategy_context(self.store, instrument.symbol, quote, as_of=trade_date),
            )
            aggregate = aggregate_signals(signals, profile["weights"], profile["aggregator"])
            symbol_operations = self.store.count_symbol_operations(trade_date, instrument.symbol) if hasattr(self.store, "count_symbol_operations") else self.store.count_fills(trade_date, instrument.symbol)
            risk_result = risk.evaluate(
                aggregate,
                portfolio,
                quote,
                daily_trade_count=daily_trade_count,
                symbol_daily_operation_count=symbol_operations,
                portfolio_daily_loss_hit=portfolio_daily_loss_hit,
                historical_peak=historical_peak,
            )
            decisions.append(risk_result.decision)
            self.store.record_decision(risk_result.decision, trade_date, portfolio)
            if not risk_result.order:
                continue
            try:
                order = replace(risk_result.order, asset_type=instrument.asset_type)
                fill = execute_order_state_machine(
                    broker,
                    order,
                    quote,
                    store=self.store,
                    trade_date=trade_date,
                )
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
                self.store.record_decision(rejected, trade_date, portfolio)
                continue
            fills.append(fill)
            self.store.record_fill(fill, trade_date)
            daily_trade_count += 1

        self.store.save_portfolio(portfolio)
        status = "degraded" if warnings else "traded"
        message = f"已完成 {trade_date.isoformat()} 一轮实时盯盘模拟。"
        if warnings:
            message = "".join([message, " 告警：", "；".join(warnings)])
        return MonitorIterationResult(status, message, portfolio, decisions, fills, warnings=warnings)

    def _apply_pending_strategy_changes(self) -> None:
        """Apply confirmed backtest drafts once, before the next monitor evaluation."""
        if not hasattr(self.store, "apply_pending_strategy_profiles"):
            return
        applied = self.store.apply_pending_strategy_profiles()
        run_ids = [int(item["source_backtest_id"]) for item in applied if item.get("source_backtest_id")]
        if run_ids and hasattr(self.store, "mark_backtest_runs_applied"):
            self.store.mark_backtest_runs_applied(run_ids)

    def generate_post_close_report(self, report_date: date | None = None) -> dict:
        report_date = report_date or datetime.now(self.timezone).date()
        if not self._is_trading_day(report_date):
            return {"report_date": report_date.isoformat(), "status": "skipped", "summary": "非交易日不生成日报。"}
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
        snapshots = self.store.load_portfolio_snapshots()
        previous_total_asset = next(
            (value for snapshot_date, value in reversed(snapshots) if snapshot_date < report_date),
            self.config.paper_account.initial_cash,
        )
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
        if hasattr(self.store, "load_decision_events"):
            report["decision_timeline"] = self.store.load_decision_events(report_date)
        self.store.save_daily_report(report)
        self._update_dormant_watchlist(report_date, portfolio)
        return report

    def _update_dormant_watchlist(self, report_date: date, portfolio: Portfolio) -> None:
        """Dormant symbols retain daily K-line sync but leave intraday trading until manually re-enabled."""
        if not hasattr(self.store, "load_recent_decisions") or not hasattr(self.store, "update_watchlist_lifecycle"):
            return
        for instrument in effective_watchlist(self.config, self.store):
            if instrument.symbol in portfolio.positions or instrument.lifecycle_status == "dormant":
                continue
            recent = self.store.load_recent_decisions(instrument.symbol, limit=20)
            if len(recent) == 20 and all(item.direction in {Direction.WATCH, Direction.HOLD} for item in recent):
                self.store.update_watchlist_lifecycle(instrument.symbol, "dormant", report_date)

    def initialize_trading_data(self, trade_date: date | None = None) -> tuple[bool, list[str]]:
        """Check persisted data readiness without making a historical-data request.

        Historical/reference synchronization is owned by the non-trading-window
        scheduler.  This method is intentionally read-only so a late monitor
        start cannot consume AlphaFeed K-line quota during market hours.
        """
        trade_date = trade_date or datetime.now(self.timezone).date()
        warnings: list[str] = list(self._initialization_warnings)
        missing = self._symbols_with_insufficient_history()
        if missing:
            warnings.append("观察池历史 K 线未就绪：" + "、".join(missing))
            self._initialization_warnings = warnings
            self._trading_data_ready = False
            return False, warnings
        self._initialization_warnings = warnings
        self._trading_data_ready = True
        return True, warnings

    def run_forever(
        self,
        max_iterations: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        on_update: Callable[[MonitorIterationResult], None] | None = None,
        ignore_market_hours: bool = False,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if not self.store.acquire_monitor_lock():
            raise RuntimeError("已有 monitor 实例持有 MySQL 运行锁，拒绝启动重复实例。")
        iteration = 0
        try:
            while max_iterations is None or iteration < max_iterations:
                local_now = self._local_now(now_fn() if now_fn else None)
                if is_daily_kline_window(local_now):
                    self._schedule_daily_kline_sync(local_now)
                scheduled = self._run_scheduled_task(local_now)
                if scheduled is not None:
                    result = scheduled
                elif self._report_is_due(local_now) and local_now.date() not in self._reported_dates:
                    report = None
                    report_warnings: list[str] = []
                    report_started_at = datetime.now(self.timezone)
                    try:
                        report = self.generate_post_close_report(local_now.date())
                        if hasattr(self.store, "save_data_task_status"):
                            self.store.save_data_task_status(
                                "daily_report",
                                local_now.date(),
                                "success",
                                1,
                                0,
                                "",
                                report_started_at,
                                datetime.now(self.timezone),
                            )
                    except Exception as exc:  # noqa: BLE001 - report failure must not stop monitoring
                        report_warnings.append(f"日报生成失败：{exc}")
                        if hasattr(self.store, "save_data_task_status"):
                            self.store.save_data_task_status(
                                "daily_report",
                                local_now.date(),
                                "failed",
                                0,
                                1,
                                str(exc),
                                report_started_at,
                                datetime.now(self.timezone),
                            )
                    self._automatic_backtest_pending_dates.add(local_now.date())
                    self._maybe_start_automatic_backtest(local_now.date())
                    portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                    result = MonitorIterationResult(
                        "reported" if report is not None else "degraded",
                        "收盘日报已归档到数据库。" if report is not None else "收盘日报生成失败，已记录告警并继续运行。",
                        portfolio,
                        [],
                        [],
                        report,
                        report_warnings,
                    )
                    if report is not None:
                        self._reported_dates.append(local_now.date())
                elif ignore_market_hours:
                    if not self._trading_data_ready:
                        ready, warnings = self.initialize_trading_data(local_now.date())
                    else:
                        ready, warnings = True, self._initialization_warnings
                    if not ready:
                        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                        result = MonitorIterationResult("initializing", "交易数据尚未就绪，本轮不执行策略；monitor 将自动重试。", portfolio, [], [], warnings=warnings)
                    else:
                        result = self.run_iteration(local_now, ignore_market_hours=True)
                        self._last_strategy_run_at = local_now
                elif is_realtime_collection_time(local_now, self._is_trading_day):
                    quotes = self.collect_realtime_quotes(local_now)
                    if is_strategy_time(local_now, self._is_trading_day) and self._strategy_is_due(local_now):
                        if not self._trading_data_ready:
                            ready, warnings = self.initialize_trading_data(local_now.date())
                        else:
                            ready, warnings = True, self._initialization_warnings
                        if not ready:
                            portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                            result = MonitorIterationResult("initializing", "交易数据尚未就绪，本轮不执行策略；monitor 将自动重试。", portfolio, [], [], warnings=warnings)
                        else:
                            result = self.run_iteration(local_now, preloaded_quotes=quotes)
                            self._last_strategy_run_at = local_now
                            if warnings:
                                result = replace(result, status="degraded", warnings=[*warnings, *result.warnings], message=result.message + " 启动数据存在非阻断告警。")
                    else:
                        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                        result = MonitorIterationResult("quoted", "已完成实时行情采集，等待下一次策略评估。", portfolio, [], [])
                elif is_daily_kline_window(local_now):
                    self._schedule_daily_kline_sync(local_now)
                    portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                    result = MonitorIterationResult("sleeping", "非交易时段，monitor 保持低频唤醒并同步日 K。", portfolio, [], [])
                else:
                    portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
                    result = MonitorIterationResult("sleeping", "非交易时段，monitor 进入休眠。", portfolio, [], [])
                if on_update:
                    on_update(result)
                iteration += 1
                if max_iterations is not None and iteration >= max_iterations:
                    break
                sleep_fn(self._sleep_seconds(local_now))
        finally:
            self.store.release_monitor_lock()

    def _sleep_seconds(self, now: datetime) -> float:
        """Sleep at the quote cadence in-session and otherwise until a boundary."""
        if not self.config.monitor.respect_market_hours:
            return float(self.config.monitor.poll_seconds)
        if is_realtime_collection_time(now, self._is_trading_day):
            return max(1.0, float(self.config.monitor.quote_poll_seconds))
        local_time = now.timetz().replace(tzinfo=None)
        if self._is_trading_day(now.date()):
            if local_time < clock_time(8, 30):
                target = datetime.combine(now.date(), clock_time(8, 30), tzinfo=now.tzinfo)
            elif local_time < clock_time(9, 15):
                target = datetime.combine(now.date(), clock_time(9, 15), tzinfo=now.tzinfo)
            elif local_time < clock_time(13, 0):
                target = datetime.combine(now.date(), clock_time(13, 0), tzinfo=now.tzinfo)
            elif local_time < clock_time(15, 30):
                target = datetime.combine(now.date(), clock_time(15, 30), tzinfo=now.tzinfo)
            elif local_time < clock_time(19, 0):
                target = datetime.combine(now.date(), clock_time(19, 0), tzinfo=now.tzinfo)
            elif local_time < clock_time(19, 30):
                target = datetime.combine(now.date(), clock_time(19, 30), tzinfo=now.tzinfo)
            else:
                target = self._next_trading_open(now.date(), now.tzinfo)
        else:
            target = self._next_trading_open(now.date(), now.tzinfo)
        return max(1.0, (target - now).total_seconds())

    def _is_active_monitor_window(self, now: datetime) -> bool:
        return is_realtime_collection_time(now, self._is_trading_day)

    def _strategy_is_due(self, now: datetime) -> bool:
        if self._last_strategy_run_at is None:
            return True
        return (now - self._last_strategy_run_at).total_seconds() >= max(1, self.config.monitor.poll_seconds)

    def collect_realtime_quotes(self, now: datetime | None = None) -> dict[str, object]:
        """Collect and persist the latest snapshot for active A-share symbols only."""
        local_now = self._local_now(now)
        if self.config.monitor.respect_market_hours and not is_realtime_collection_time(local_now, self._is_trading_day):
            return {}
        self._prepare_intraday_quote_store(local_now)
        symbols = [
            item.symbol
            for item in effective_watchlist(self.config, self.store)
            if item.lifecycle_status not in {"dormant", "removed"}
        ]
        if not symbols:
            return {}
        try:
            quotes = fetch_quotes(self.quote_provider, symbols)
        except Exception as exc:  # noqa: BLE001 - one failed source must not stop the scheduler
            logger.warning("实时行情采集失败（%s）：%s", local_now.isoformat(), exc)
            return {}
        if quotes:
            self.store.save_quotes(list(quotes.values()))
        return quotes

    def _schedule_daily_kline_sync(self, now: datetime) -> None:
        completed_date = self._completed_trading_date(now)
        window = "after_close" if now.timetz().replace(tzinfo=None) >= clock_time(15, 30) else "preopen"
        key = (completed_date, window)
        if key in self._daily_kline_sync_attempted_windows:
            return
        self._daily_kline_sync_attempted_windows.add(key)
        self._start_background(self._run_daily_kline_sync, completed_date)

    def _run_daily_kline_sync(self, completed_date: date) -> None:
        success = self._sync_reference_data_in_background(completed_date, True, completed_date)
        us_result = self._sync_external_us(completed_date)
        if us_result.get("failure_count"):
            success = False
            logger.warning("美股外围数据有 %s 个标的失败（%s）", us_result["failure_count"], completed_date.isoformat())
        try:
            korea_rows = fetch_korea_market_data()
            self.store.save_overseas_market_data(korea_rows)
        except Exception as exc:  # noqa: BLE001 - external daily data is fail-closed for dependent strategies
            success = False
            logger.warning("韩股外围数据同步失败（%s）：%s", completed_date.isoformat(), exc)
        if success:
            self._daily_kline_completed_dates.add(completed_date)
            self._maybe_start_automatic_backtest(completed_date)

    def _maybe_start_automatic_backtest(self, trade_date: date) -> None:
        if trade_date not in self._automatic_backtest_pending_dates or trade_date not in self._daily_kline_completed_dates:
            return
        self._automatic_backtest_pending_dates.discard(trade_date)
        if trade_date not in self._automatic_backtest_started_dates:
            self._automatic_backtest_started_dates.append(trade_date)
            self._start_background(self._run_automatic_backtest, trade_date)

    def _completed_trading_date(self, now: datetime) -> date:
        candidate = now.date()
        local_time = now.timetz().replace(tzinfo=None)
        if local_time < clock_time(9, 0) or not self._is_trading_day(candidate):
            candidate -= timedelta(days=1)
        while not self._is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def _report_is_due(self, now: datetime) -> bool:
        hour, minute = [int(part) for part in self.config.monitor.post_close_report_time.split(":", 1)]
        return self._is_trading_day(now.date()) and now.timetz().replace(tzinfo=None) >= clock_time(hour, minute)

    def _run_scheduled_task(self, now: datetime) -> MonitorIterationResult | None:
        """Run each pre/post-market job once. Failures remain visible and fail related strategies closed."""
        if not self._is_trading_day(now.date()):
            return None
        local_time, day = now.timetz().replace(tzinfo=None), now.date()
        task = None
        if clock_time(8, 30) <= local_time < clock_time(9, 0):
            task = "premarket"
        elif clock_time(9, 25) <= local_time < clock_time(9, 30):
            task = "auction_check"
        elif clock_time(19, 0) <= local_time < clock_time(19, 30):
            task = "postmarket_lhb"
        elif clock_time(19, 30) <= local_time < clock_time(20, 0):
            task = "postmarket_futures"
        if not task or (day, task) in self._scheduled_task_dates:
            return None
        self._scheduled_task_dates.add((day, task))
        warnings: list[str] = []
        completed: list[str] = []
        retry_task = False
        task_started_at = datetime.now(self.timezone)
        try:
            if task == "premarket":
                self._prepare_intraday_quote_store(now)
                completed.append("交易前行情存储已准备")
            elif task == "auction_check":
                completed.append("集合竞价条件将在 09:30 首轮行情中使用")
            elif task == "postmarket_lhb":
                self.store.save_lhb_records(fetch_lhb_data(day))
                refresh_lhb_seat_profiles(self.store)
                completed.append("龙虎榜数据")
            elif task == "postmarket_futures":
                rows = fetch_futures_positions(day)
                if rows:
                    self.store.save_futures_positions(rows)
                    completed.append("期指持仓数据")
                else:
                    warnings.append("期指持仓接口未返回可校验的 IC 前十持仓，策略将保持失效。")
        except Exception as exc:  # noqa: BLE001
            retry_task = True
            warnings.append(f"{task} 失败：{exc}")
        portfolio = self.store.load_portfolio(self.config.paper_account.initial_cash)
        if hasattr(self.store, "save_data_task_status"):
            try:
                self.store.save_data_task_status(
                    task,
                    day,
                    "failed" if retry_task and not completed else "degraded" if warnings else "success",
                    len(completed),
                    len(warnings),
                    "；".join(warnings),
                    task_started_at,
                    datetime.now(self.timezone),
                )
            except Exception as exc:  # noqa: BLE001 - status persistence must not stop the monitor
                logger.warning("任务状态写入失败（%s）：%s", task, exc)
        if retry_task:
            self._scheduled_task_dates.discard((day, task))
        return MonitorIterationResult("scheduled" if not warnings else "degraded", "；".join(completed) or f"{task} 未完成", portfolio, [], [], warnings=warnings)

    def _run_automatic_backtest(self, trade_date: date) -> None:
        """Backtests create pending candidates only; they never alter an active profile."""
        from .app import optimize_strategy_from_store
        started_at = datetime.now(self.timezone)
        try:
            optimize_strategy_from_store(self.config, self.store)
            if hasattr(self.store, "save_data_task_status"):
                self.store.save_data_task_status(
                    "automatic_backtest",
                    trade_date,
                    "success",
                    1,
                    0,
                    "",
                    started_at,
                    datetime.now(self.timezone),
                )
        except Exception as exc:  # noqa: BLE001 - background failure is persisted and isolated
            if hasattr(self.store, "save_data_task_status"):
                self.store.save_data_task_status(
                    "automatic_backtest",
                    trade_date,
                    "failed",
                    0,
                    1,
                    str(exc),
                    started_at,
                    datetime.now(self.timezone),
                )
            raise

    def _next_trading_open(self, current: date, timezone) -> datetime:
        candidate = current + timedelta(days=1)
        while not self._is_trading_day(candidate):
            candidate += timedelta(days=1)
        return datetime.combine(candidate, clock_time(9, 30), tzinfo=timezone)

    def _local_now(self, now: datetime | None = None) -> datetime:
        current = now or datetime.now(self.timezone)
        if current.tzinfo is None:
            return current.replace(tzinfo=self.timezone)
        return current.astimezone(self.timezone)

    def _start_background(self, func: Callable, *args) -> None:
        Thread(target=self._safe_background_task, args=(func, *args), daemon=True).start()

    def _safe_background_task(self, func: Callable, *args) -> None:
        try:
            func(*args)
        except Exception as exc:  # noqa: BLE001 - background work must not terminate the monitor
            logger.error("后台任务 %s 失败：%s", getattr(func, "__name__", repr(func)), exc, exc_info=True)

    def _compact_watch_decisions(self, trade_date: date) -> None:
        if trade_date in self._decision_compaction_attempted_dates:
            return
        self._decision_compaction_attempted_dates.append(trade_date)
        self.store.compact_watch_decisions()
        full_history_compaction = False
        if hasattr(self.store, "compact_decision_events"):
            if not self._decision_history_compaction_done:
                removed = self.store.compact_decision_events()
                self._decision_history_compaction_done = True
                full_history_compaction = True
            else:
                removed = self.store.compact_decision_events(trade_date)
            if removed:
                scope = "历史" if full_history_compaction else trade_date.isoformat()
                logger.info("已压缩%s重复业务事件：%s 条", scope, removed)
        if hasattr(self.store, "purge_decision_events") and self._decision_history_compaction_done:
            purged = self.store.purge_decision_events(trade_date)
            if purged:
                logger.info("已清理过期业务事件：%s 条", purged)

    def _prepare_intraday_quote_store(self, local_now: datetime) -> None:
        """Discard the previous trading day's snapshots before a new A-share session."""
        trade_date = local_now.date()
        if not self._is_trading_day(trade_date) or trade_date in self._quote_prune_attempted_dates:
            return
        self._quote_prune_attempted_dates.append(trade_date)
        self.store.prune_market_quotes(trade_date)

    def _sync_catalog_in_background(self, trade_date: date) -> None:
        if hasattr(self.quote_provider, "list_instruments"):
            try:
                sync_instrument_catalog(self.config, self.store, self.quote_provider, trade_date.isoformat())
            except Exception as exc:  # noqa: BLE001 - background refresh must not stop trading
                logger.warning("证券目录同步失败（%s）：%s", trade_date.isoformat(), exc)

    def _sync_external_us(self, trade_date: date) -> dict:
        def fallback(spec):
            rows = fetch_us_market_data((spec.canonical_symbol,))
            return rows[0] if rows else None

        try:
            return sync_external_market_data(
                self.store,
                self.external_history_provider,
                DEFAULT_US_SPECS,
                as_of=trade_date,
                fallback_fetcher=fallback,
                now_fn=lambda: datetime.now(self.timezone),
            )
        except Exception as exc:  # noqa: BLE001 - status is returned to monitor, not raised
            logger.warning("美股外围数据同步失败（%s）：%s", trade_date.isoformat(), exc)
            return {"success_count": 0, "skipped_count": 0, "failure_count": len(DEFAULT_US_SPECS), "failures": [{"symbol": "*", "reason": str(exc)}]}

    def _sync_reference_data_in_background(
        self,
        trade_date: date,
        refresh_history: bool = True,
        history_as_of: date | None = None,
    ) -> bool:
        """Synchronize all non-snapshot data inside the daily K-line window."""
        success = True
        self._sync_catalog_in_background(trade_date)
        history_as_of = history_as_of or trade_date
        if refresh_history:
            try:
                self._sync_watchlist_history(force=True, as_of=history_as_of)
            except Exception as exc:  # noqa: BLE001 - retry occurs on the next scheduled refresh
                success = False
                logger.warning("观察池历史同步失败（%s）：%s", trade_date.isoformat(), exc)
        try:
            sync_benchmark_history(self.config, self.store, self.history_provider, as_of=history_as_of)
        except Exception as exc:  # noqa: BLE001 - benchmark failure is non-blocking but observable
            success = False
            logger.warning("基准指数历史同步失败（%s）：%s", trade_date.isoformat(), exc)
        try:
            sync_sector_mappings(self.config, self.store, as_of=trade_date)
        except Exception as exc:  # noqa: BLE001 - missing sector data degrades only external strategies
            success = False
            logger.warning("板块映射同步失败（%s）：%s", trade_date.isoformat(), exc)
        return success

    def _sync_watchlist_history(self, force: bool, as_of: date | None = None) -> list[str]:
        result = sync_watchlist_history(
            self.config,
            self.store,
            self.history_provider,
            as_of=as_of,
            force=force,
            only_incomplete=True,
        )
        return result.warnings

    def _symbols_with_insufficient_history(self) -> list[str]:
        interval = str(self.config.data.history.get("interval", "daily"))
        minimum = int(self.config.data.history.get("monitor_minimum_bars", 35))
        return [
            instrument.symbol
            for instrument in effective_watchlist(self.config, self.store)
            if len(self.store.load_watchlist_bars(instrument.symbol, interval=interval, limit=minimum)) < minimum
        ]


def is_realtime_collection_time(now: datetime, trading_day_checker: Callable[[date], bool] | None = None) -> bool:
    """A-share snapshot window, including the 09:15-09:30 auction period."""
    local_time = now.timetz().replace(tzinfo=None)
    if not (trading_day_checker or (lambda value: value.weekday() < 5))(now.date()):
        return False
    return (clock_time(9, 15) <= local_time <= clock_time(11, 30)) or (clock_time(13, 0) <= local_time <= clock_time(15, 0))


def is_strategy_time(now: datetime, trading_day_checker: Callable[[date], bool] | None = None) -> bool:
    return is_trading_time(now, trading_day_checker)


def is_daily_kline_window(now: datetime) -> bool:
    """Daily K-line synchronization window: 15:30-24:00 and 00:00-09:00."""
    local_time = now.timetz().replace(tzinfo=None)
    return local_time >= clock_time(15, 30) or local_time < clock_time(9, 0)


def is_trading_time(now: datetime, trading_day_checker: Callable[[date], bool] | None = None) -> bool:
    local_time = now.timetz().replace(tzinfo=None)
    if not (trading_day_checker or (lambda value: value.weekday() < 5))(now.date()):
        return False
    morning = clock_time(9, 30) <= local_time <= clock_time(11, 30)
    afternoon = clock_time(13, 0) <= local_time <= clock_time(15, 0)
    return morning or afternoon


def is_post_close_report_time(
    now: datetime,
    configured_time: str,
    trading_day_checker: Callable[[date], bool] | None = None,
) -> bool:
    hour, minute = [int(part) for part in configured_time.split(":", 1)]
    local_time = now.timetz().replace(tzinfo=None)
    report_time = clock_time(hour, minute)
    # Only generate the scheduled report in a narrow close window.  Starting a
    # monitor late at night must not fabricate a second report for that date.
    close_window_end = clock_time(min(23, hour), min(59, minute + 10))
    return (trading_day_checker or (lambda value: value.weekday() < 5))(now.date()) and report_time <= local_time <= close_window_end
