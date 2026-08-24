from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .backtest import BacktestResult, optimize_strategy_parameters
from .config import AppConfig, load_config
from .data.providers import create_history_data_provider, create_market_data_provider, fetch_quotes
from .features import build_features
from .history_sync import missing_history_range
from .journal import build_daily_report
from .learning import propose_parameter_changes, summarize_learning
from .models import Bar, Decision, Fill, Portfolio
from .monitor import RealTimePaperTradingMonitor
from .paper_broker import PaperBroker, PaperBrokerError
from .quant_strategies import QuantContext
from .risk import RiskEngine
from .reference_data import sync_benchmark_history, sync_instrument_catalog
from .storage.base import MarketDataStore
from .storage.mock import MockMarketDataStore
from .storage.mysql import MySQLMarketDataStore
from .strategy import StrategyContext, aggregate_signals
from .strategy_runtime import evaluate_strategy_profile, profile_from_config
from .universe import Universe
from .web import serve_dashboard
from .watchlist import effective_watchlist


logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=getattr(logging, os.environ.get("STOCK_AI_LOG_LEVEL", "INFO").upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )


@dataclass
class RunResult:
    portfolio: Portfolio
    decisions: List[Decision]
    fills: List[Fill]
    report: Optional[dict] = None


def create_market_data_store(config: AppConfig) -> MarketDataStore:
    if config.storage.driver == "mock":
        return MockMarketDataStore()
    if config.storage.driver == "mysql":
        return MySQLMarketDataStore(config.storage.mysql)
    raise ValueError(f"暂不支持的数据存储驱动：{config.storage.driver}")


def run_once(
    config: AppConfig,
    bars_by_symbol: Dict[str, List[Bar]],
    histories: Dict[str, List[Decimal]],
    quote_provider=None,
    report_date: Optional[date] = None,
) -> RunResult:
    universe = Universe.from_config(config.universe)
    portfolio = Portfolio(config.paper_account.initial_cash)
    broker = PaperBroker(portfolio, config.paper_account.fee_rate, config.paper_account.slippage_rate)
    risk = RiskEngine(config.risk, universe)
    quote_provider = quote_provider or create_market_data_provider(config)
    decisions: List[Decision] = []
    fills: List[Fill] = []
    symbol_operations: dict[str, int] = {}
    minimum_history_bars = int(config.data.history.get("monitor_minimum_bars", 35))
    quotes = fetch_quotes(quote_provider, [instrument.symbol for instrument in universe.instruments if instrument.trading_enabled or instrument.symbol in portfolio.positions])

    for instrument in universe.instruments:
        if not instrument.trading_enabled and instrument.symbol not in portfolio.positions:
            continue
        quote = quotes[instrument.symbol]
        bars = bars_by_symbol.get(instrument.symbol)
        if not bars or len(bars) < minimum_history_bars:
            continue
        features = build_features(instrument.symbol, bars, quote)
        current_weights = {symbol: portfolio.position_weight(symbol) for symbol in portfolio.positions}
        strategy_context = StrategyContext(current_weights)
        current_value = portfolio.total_asset()
        quant_context = QuantContext(
            histories=histories,
            current_weights=current_weights,
            peak_values={instrument.symbol: max(config.paper_account.initial_cash, current_value)},
            current_values={instrument.symbol: current_value},
        )
        profile = profile_from_config(config, asset_type=instrument.asset_type)
        signals = evaluate_strategy_profile(
            profile,
            instrument.symbol,
            features,
            strategy_context,
            quant_context,
            config.risk.high_atr_ratio,
        )
        aggregate = aggregate_signals(signals, profile["weights"], profile["aggregator"])
        risk_result = risk.evaluate(
            aggregate,
            portfolio,
            quote,
            daily_trade_count=len(fills),
            symbol_daily_operation_count=symbol_operations.get(instrument.symbol, 0),
        )
        decisions.append(risk_result.decision)
        if risk_result.order:
            try:
                fills.append(broker.execute(risk_result.order))
                symbol_operations[instrument.symbol] = symbol_operations.get(instrument.symbol, 0) + 1
            except PaperBrokerError as exc:
                decisions.append(
                    Decision(
                        risk_result.order.symbol,
                        risk_result.order.direction,
                        risk_result.decision.target_weight,
                        False,
                        [str(exc)],
                        aggregate,
                    )
                )

    report = build_daily_report(
        report_date or date.today(),
        portfolio,
        decisions,
        fills,
        config.paper_account.initial_cash,
        status="临时运行",
    )
    return RunResult(portfolio, decisions, fills, report)


def run_once_from_store(
    config: AppConfig,
    store: MarketDataStore,
    quote_provider=None,
    report_date: Optional[date] = None,
    history_limit: int = 80,
) -> RunResult:
    config = replace(config, universe=effective_watchlist(config, store))
    universe = Universe.from_config(config.universe)
    symbols = [instrument.symbol for instrument in universe.instruments]
    interval = str(config.data.history.get("interval", "daily"))
    bars_by_symbol = store.load_bars_batch(symbols, interval=interval, limit=history_limit)
    histories = {
        symbol: [bar.close_price for bar in bars]
        for symbol, bars in bars_by_symbol.items()
    }
    return run_once(config, bars_by_symbol, histories, quote_provider, report_date)


def sync_history(config: AppConfig, store: MarketDataStore, adapter=None, as_of: date | None = None) -> dict[str, int]:
    config = replace(config, universe=effective_watchlist(config, store))
    universe = Universe.from_config(config.universe)
    adapter = adapter or create_history_data_provider(config)
    history_config = config.data.history
    interval = str(history_config.get("interval", "daily"))
    adjust = str(history_config.get("adjust", "qfq"))
    configured_start = str(history_config.get("start", "20240101"))
    configured_end = str(history_config.get("end", "20500101"))
    counts: dict[str, int] = {}
    for instrument in universe.instruments:
        symbol = instrument.symbol
        range_to_sync = missing_history_range(
            store,
            symbol,
            interval,
            configured_start,
            configured_end,
            as_of,
        )
        if range_to_sync is None:
            counts[symbol] = 0
            continue
        start, end = range_to_sync
        bars = adapter.get_bars(symbol, interval=interval, start=start, end=end, adjust=adjust)
        source = getattr(adapter, "last_source", "") or config.data.history_provider
        counts[symbol] = store.save_bars(bars, interval=interval, source=source)
    return counts


def sync_benchmarks(config: AppConfig, store: MarketDataStore, adapter=None) -> dict[str, int]:
    return sync_benchmark_history(config, store, adapter)


def optimize_strategy_from_store(config: AppConfig, store: MarketDataStore) -> object:
    watchlist = effective_watchlist(config, store)
    portfolio = store.load_portfolio(config.paper_account.initial_cash)
    universe = Universe.from_config([item for item in watchlist if item.trading_enabled or item.symbol in portfolio.positions])
    symbols = [instrument.symbol for instrument in universe.instruments]
    interval = str(config.data.history.get("interval", "daily"))
    bars_by_symbol = store.load_bars_batch(symbols, interval=interval)
    result = optimize_strategy_parameters(
        bars_by_symbol,
        fee_rate=config.paper_account.fee_rate,
        slippage_rate=config.paper_account.slippage_rate,
    )
    if hasattr(store, "record_backtest_run"):
        for candidate in result.candidates:
            store.record_backtest_run(
                candidate.strategy_id,
                candidate.parameters,
                _metrics_dict(candidate.metrics),
                candidate.status,
            )
        proposals = propose_parameter_changes(result.best.metrics.strategy_contributions, result.best.metrics)
        store.record_backtest_run(
            "learning_review",
            {"based_on": result.best.strategy_id, "parameters": result.best.parameters},
            {
                "summary": summarize_learning(result.best.metrics.strategy_contributions, result.best.metrics),
                "proposals": [
                    {"strategy_id": item.strategy_id, "suggestion": item.suggestion, "evidence": item.evidence, "status": item.status}
                    for item in proposals
                ],
            },
            "待人工确认",
        )
    return result


def post_close(portfolio: Portfolio, decisions: Iterable[Decision], fills: Iterable[Fill], report_date: Optional[date] = None) -> dict:
    return build_daily_report(report_date or date.today(), portfolio, decisions, fills)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股沪深模拟盘 AI-Agent")
    parser.add_argument(
        "command",
        choices=["sync-history", "sync-benchmarks", "sync-instruments", "run-once", "monitor", "post-close", "optimize-strategy", "web"],
        help="同步行情、运行模拟、实时盯盘、收盘日报、回测优化或启动 Web",
    )
    parser.add_argument("--config", default="config/default.yaml", help="配置文件路径")
    parser.add_argument("--poll-seconds", type=int, default=None, help="实时盯盘轮询间隔秒数，默认读取配置")
    parser.add_argument("--max-iterations", type=int, default=None, help="实时盯盘最多执行轮数，默认持续运行")
    parser.add_argument("--ignore-market-hours", action="store_true", help="忽略 A 股交易时段限制，便于本地验证")
    parser.add_argument("--host", default="127.0.0.1", help="Web 服务监听地址")
    parser.add_argument("--port", type=int, default=8765, help="Web 服务监听端口")
    args = parser.parse_args(argv)
    _configure_logging()

    config = load_config(args.config)
    if args.poll_seconds is not None:
        config = replace(config, monitor=replace(config.monitor, poll_seconds=args.poll_seconds))
    store = create_market_data_store(config)
    if args.command == "sync-history":
        try:
            counts = sync_history(config, store)
        except Exception as exc:
            logger.error("同步历史 K 线失败：%s", exc)
            return 1
        for symbol, count in counts.items():
            logger.info("已同步 %s 历史 K 线 %s 条。", symbol, count)
        return 0
    if args.command == "sync-benchmarks":
        try:
            counts = sync_benchmarks(config, store)
        except Exception as exc:
            logger.error("同步大盘指数历史 K 线失败：%s", exc)
            return 1
        for symbol, count in counts.items():
            logger.info("已同步 %s 指数历史 K 线 %s 条。", symbol, count)
        return 0
    if args.command == "sync-instruments":
        try:
            count = sync_instrument_catalog(config, store)
        except Exception as exc:
            logger.error("同步全量证券目录失败：%s", exc)
            return 1
        logger.info("已同步沪深股票/ETF 目录 %s 条。", count)
        return 0
    if args.command == "run-once":
        try:
            result = run_once_from_store(config, store)
        except Exception as exc:
            logger.error("模拟运行失败：%s", exc)
            return 1
        logger.info("已完成一次临时模拟运行：%s（不会覆盖正式日报归档）", result.report["report_date"])
        return 0
    if args.command == "monitor":
        monitor = RealTimePaperTradingMonitor(config, store)

        def print_update(result) -> None:
            detail = f"；本轮成交 {len(result.fills)} 笔，决策 {len(result.decisions)} 条"
            if result.report:
                detail = f"；日报归档：{result.report['report_date']}"
            logger.info("%s：%s%s", result.status, result.message, detail)

        try:
            monitor.run_forever(args.max_iterations, on_update=print_update, ignore_market_hours=args.ignore_market_hours)
        except KeyboardInterrupt:
            logger.info("已停止实时盯盘模拟。")
        except Exception as exc:
            logger.error("实时盯盘模拟失败：%s", exc, exc_info=True)
            return 1
        return 0
    if args.command == "optimize-strategy":
        try:
            result = optimize_strategy_from_store(config, store)
        except Exception as exc:
            logger.error("自动回测优化失败：%s", exc, exc_info=True)
            return 1
        best = result.best
        logger.info("已完成自动回测优化，最佳候选仍需人工确认。")
        logger.info("策略：%s；参数：%s", best.strategy_id, best.parameters)
        logger.info("收益率：%.2f%%，最大回撤：%.2f%%，胜率：%.2f%%", best.metrics.total_return * 100, best.metrics.max_drawdown * 100, best.metrics.win_rate * 100)
        return 0
    if args.command == "web":
        try:
            logger.info("Web 驾驶舱已启动：http://%s:%s", args.host, args.port)
            serve_dashboard(config, store, args.host, args.port)
        except KeyboardInterrupt:
            logger.info("已停止 Web 驾驶舱。")
        except Exception as exc:
            logger.error("启动 Web 驾驶舱失败：%s", exc, exc_info=True)
            return 1
        return 0
    monitor = RealTimePaperTradingMonitor(config, store)
    report = monitor.generate_post_close_report()
    logger.info("收盘日报已归档到数据库：%s", report["report_date"])
    return 0


def _metrics_dict(metrics: BacktestResult) -> dict[str, str]:
    return {
        "total_return": str(metrics.total_return),
        "max_drawdown": str(metrics.max_drawdown),
        "win_rate": str(metrics.win_rate),
        "profit_loss_ratio": str(metrics.profit_loss_ratio),
        "turnover": str(metrics.turnover),
        "max_consecutive_losses": str(metrics.max_consecutive_losses),
    }


if __name__ == "__main__":
    raise SystemExit(main())
