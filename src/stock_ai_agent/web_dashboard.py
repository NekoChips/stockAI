"""Dashboard payload builders.

These functions only assemble response data; HTTP parsing and side effects
live in the route and action modules.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from .analytics import (
    build_benchmark_comparison,
    build_benchmark_outperformance,
    build_profit_calendar,
    build_profit_leaderboard,
    compute_period_returns,
    fill_daily_snapshots,
)
from .config import AppConfig
from .web_support import _DASHBOARD_CACHE, _to_jsonable
from .watchlist import effective_watchlist
from .risk_config import parse_risk_config, resolve_risk_config, risk_config_payload


ANALYSIS_START_DATE = date(2026, 1, 1)


def build_dashboard_payload(
    config: AppConfig,
    store,
    as_of: date | None = None,
    performance_start: date | None = None,
    performance_end: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    cache_key = (id(store), id(config), as_of, performance_start, performance_end)

    def compute() -> dict[str, Any]:
        stored_snapshots = store.load_portfolio_snapshots()
        payload = {
            **build_dashboard_overview_payload(config, store, as_of, stored_snapshots),
            **build_dashboard_performance_payload(
                config,
                store,
                as_of,
                performance_start,
                performance_end,
                stored_snapshots,
            ),
            **build_dashboard_calendar_payload(config, store, as_of, stored_snapshots),
            **build_dashboard_backtests_payload(store),
        }
        payload["period_returns"] = _to_jsonable(
            compute_period_returns(
                fill_daily_snapshots(
                    stored_snapshots,
                    config.web.analysis_start_date,
                    as_of,
                    config.paper_account.initial_cash,
                )
            )
        )
        return payload

    return _DASHBOARD_CACHE.get_or_compute(cache_key, compute)


def build_dashboard_overview_payload(
    config: AppConfig,
    store,
    as_of: date | None = None,
    stored_snapshots=None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    portfolio = store.load_portfolio(config.paper_account.initial_cash)
    snapshots = fill_daily_snapshots(
        stored_snapshots if stored_snapshots is not None else store.load_portfolio_snapshots(),
        config.web.analysis_start_date,
        as_of,
        config.paper_account.initial_cash,
    )
    watchlist = effective_watchlist(config, store)
    configured = {item.symbol for item in config.universe}
    watchlist_rows = [
        {**asdict(item), "source": "默认配置" if item.symbol in configured else "手动添加"}
        for item in watchlist
    ]
    names = {item.symbol: item.name for item in watchlist}
    latest_quotes = (
        store.load_latest_quotes([item.symbol for item in watchlist])
        if hasattr(store, "load_latest_quotes")
        else {}
    )
    all_fills = store.load_all_fills() if hasattr(store, "load_all_fills") else []
    backtest_runs = store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else []
    period_returns = compute_period_returns(snapshots)
    daily_returns = period_returns.get("daily", [])
    draft = store.load_risk_config_draft() if hasattr(store, "load_risk_config_draft") else None
    if draft:
        try:
            risk_payload = risk_config_payload(parse_risk_config(config.risk, draft), status="draft", pending_confirmation=True)
        except (TypeError, ValueError):
            risk_payload = risk_config_payload(resolve_risk_config(config, store))
    else:
        risk_payload = risk_config_payload(resolve_risk_config(config, store))
    return _to_jsonable(
        {
            "portfolio": {
                "cash": portfolio.cash,
                "total_asset": portfolio.total_asset(),
                "total_market_value": portfolio.total_market_value(),
                "positions": list(portfolio.positions.values()),
            },
            "recent_fills": all_fills[-20:],
            "today_decisions": store.load_decisions(as_of) if hasattr(store, "load_decisions") else [],
            "daily_return": daily_returns[-1].return_rate if daily_returns else 0,
            "profit_leaderboard": build_profit_leaderboard(portfolio, all_fills, names, as_of=as_of),
            "watchlist": watchlist_rows,
            "market_quotes": latest_quotes,
            "pending_backtest_count": sum(item.get("status") != "已确认" for item in backtest_runs),
            "risk_config": risk_payload,
        }
    )


def build_dashboard_performance_payload(
    config: AppConfig,
    store,
    as_of: date | None = None,
    performance_start: date | None = None,
    performance_end: date | None = None,
    stored_snapshots=None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    selected_start, selected_end = _performance_range(
        performance_start,
        performance_end,
        as_of,
        config.web.analysis_start_date,
    )
    performance_snapshots = fill_daily_snapshots(
        stored_snapshots if stored_snapshots is not None else store.load_portfolio_snapshots(),
        selected_start,
        selected_end,
        config.paper_account.initial_cash,
    )
    benchmark_names = {item.symbol: item.name for item in config.benchmarks}
    symbols = [item.symbol for item in config.benchmarks]
    benchmark_bars = store.load_bars_batch(
        symbols,
        interval="daily",
        start=selected_start,
        end=selected_end,
    )
    benchmark_comparison = build_benchmark_comparison(
        performance_snapshots,
        benchmark_bars,
        benchmark_names,
        start_date=selected_start,
        end_date=selected_end,
    )
    benchmark_outperformance = build_benchmark_outperformance(
        benchmark_comparison,
        [item.name for item in config.benchmarks],
    )
    benchmark_status = [
        {
            "symbol": item.symbol,
            "name": item.name,
            "state": "可用" if benchmark_bars[item.symbol] else "待同步",
            "points": len(benchmark_bars[item.symbol]),
            "latest_day": benchmark_bars[item.symbol][-1].timestamp.date() if benchmark_bars[item.symbol] else None,
        }
        for item in config.benchmarks
    ]
    return _to_jsonable(
        {
            "equity_curve": [{"day": day, "total_asset": value} for day, value in performance_snapshots],
            "benchmark_comparison": benchmark_comparison,
            "benchmark_outperformance": benchmark_outperformance,
            "performance_range": {"start_date": selected_start, "end_date": selected_end},
            "benchmark_status": benchmark_status,
            "benchmarks": benchmark_names,
        }
    )


def build_dashboard_calendar_payload(
    config: AppConfig,
    store,
    as_of: date | None = None,
    stored_snapshots=None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    snapshots = fill_daily_snapshots(
        stored_snapshots if stored_snapshots is not None else store.load_portfolio_snapshots(),
        config.web.analysis_start_date,
        as_of,
        config.paper_account.initial_cash,
    )
    return _to_jsonable({"profit_calendar": build_profit_calendar(snapshots)})


def build_dashboard_backtests_payload(store) -> dict[str, Any]:
    runs = store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else []
    return _to_jsonable({"backtest_runs": runs})


def build_dashboard_orders_payload(store, limit: int = 100) -> dict[str, Any]:
    orders = store.load_orders(limit) if hasattr(store, "load_orders") else []
    return _to_jsonable({"orders": orders})


def build_dashboard_strategies_payload(config: AppConfig, store) -> dict[str, Any]:
    if hasattr(store, "load_strategy_center"):
        return _to_jsonable({"strategies": store.load_strategy_center(config)})
    return _to_jsonable({"strategies": {"definitions": [], "profiles": [], "changes": []}})


def build_dashboard_reports_payload(store, limit: int = 60, offset: int = 0) -> dict[str, Any]:
    reports = store.load_daily_reports(limit=limit, offset=offset) if hasattr(store, "load_daily_reports") else []
    return _to_jsonable({"daily_reports": reports})


def build_dashboard_report_payload(store, report_date: date) -> dict[str, Any]:
    report = store.load_daily_report(report_date) if hasattr(store, "load_daily_report") else None
    return _to_jsonable({"daily_report": report})


def _performance_range(
    requested_start: date | None,
    requested_end: date | None,
    as_of: date,
    analysis_start: date = ANALYSIS_START_DATE,
) -> tuple[date, date]:
    start = max(requested_start or analysis_start, analysis_start)
    end = min(requested_end or as_of, as_of)
    if end < start:
        raise ValueError("盈亏分析结束日期不能早于开始日期。")
    return start, end


def _query_date(values: dict[str, list[str]], name: str) -> date | None:
    raw = values.get(name, [""])[0].strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须使用 YYYY-MM-DD 格式。") from exc
