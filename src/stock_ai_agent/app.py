from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from typing import List, Optional

from .backtest import BacktestResult, optimize_strategy_parameters
from .config import AppConfig, load_config
from .learning import propose_parameter_changes, summarize_learning
from .monitor import RealTimePaperTradingMonitor
from .storage.base import MarketDataStore
from .storage.mock import MockMarketDataStore
from .storage.mysql import MySQLMarketDataStore
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


def create_market_data_store(config: AppConfig) -> MarketDataStore:
    if config.storage.driver == "mock":
        return MockMarketDataStore()
    if config.storage.driver == "mysql":
        return MySQLMarketDataStore(config.storage.mysql)
    raise ValueError(f"暂不支持的数据存储驱动：{config.storage.driver}")


def optimize_strategy_from_store(config: AppConfig, store: MarketDataStore) -> object:
    """Run the page/monitor backtest workflow and persist review candidates."""
    watchlist = effective_watchlist(config, store)
    portfolio = store.load_portfolio(config.paper_account.initial_cash)
    universe = Universe.from_config([item for item in watchlist if item.trading_enabled or item.symbol in portfolio.positions])
    symbols = [instrument.symbol for instrument in universe.instruments]
    interval = str(config.data.history.get("interval", "daily"))
    bars_by_symbol = store.load_watchlist_bars_batch(symbols, interval=interval)
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
                "default",
            )
        proposals = propose_parameter_changes(result.best.metrics.strategy_contributions, result.best.metrics)
        store.record_backtest_run(
            "learning_review",
            {"based_on": result.best.strategy_id, "parameters": result.best.parameters},
            {
                "summary": summarize_learning(result.best.metrics.strategy_contributions, result.best.metrics),
                "proposals": [
                    {
                        "strategy_id": item.strategy_id,
                        "suggestion": item.suggestion,
                        "evidence": item.evidence,
                        "status": item.status,
                    }
                    for item in proposals
                ],
            },
            "待人工确认",
            "default",
        )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股沪深模拟盘 AI-Agent")
    parser.add_argument(
        "command",
        choices=["monitor", "web"],
        help="启动实时 monitor 或 Web 服务；业务操作请通过 Web 页面完成",
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
    return 2


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
