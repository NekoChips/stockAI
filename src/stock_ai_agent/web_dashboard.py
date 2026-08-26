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
from .strategy_catalog import strategy_definitions
from .strategy_runtime import resolve_strategy_profile


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
            "pending_backtest_count": sum(item.get("status") not in {"已确认", "已应用", "已拒绝"} for item in backtest_runs),
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


def build_dashboard_data_health_payload(config: AppConfig, store, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    watchlist = effective_watchlist(config, store)
    latest_external = store.load_latest_overseas_data() if hasattr(store, "load_latest_overseas_data") else []
    sectors = {
        item.symbol: (store.load_instrument_sector(item.symbol) if hasattr(store, "load_instrument_sector") else None)
        for item in watchlist
    }
    return _to_jsonable(
        {
            "as_of": as_of,
            "tasks": store.load_data_task_status() if hasattr(store, "load_data_task_status") else [],
            "external_market": latest_external,
            "sector_mapping": sectors,
        }
    )


def build_dashboard_sectors_payload(store, symbol: str | None = None) -> dict[str, Any]:
    rows = store.load_sector_mappings(symbol=symbol) if hasattr(store, "load_sector_mappings") else []
    return _to_jsonable({"sectors": rows, "symbol": symbol or ""})


def build_dashboard_lhb_records_payload(store, trade_date: date | None = None, symbol: str | None = None) -> dict[str, Any]:
    rows = store.load_lhb_records(start=trade_date, end=trade_date, symbol=symbol) if hasattr(store, "load_lhb_records") else []
    return _to_jsonable({"records": rows, "trade_date": trade_date, "symbol": symbol or ""})


def build_dashboard_lhb_raw_payload(store, record_id: str) -> dict[str, Any]:
    try:
        raw_date, symbol = record_id.split("|", 1)
        trade_date = date.fromisoformat(raw_date)
    except (ValueError, TypeError) as exc:
        raise ValueError("龙虎榜记录 ID 必须使用 YYYY-MM-DD|证券代码 格式。") from exc
    rows = store.load_lhb_records(start=trade_date, end=trade_date, symbol=symbol) if hasattr(store, "load_lhb_records") else []
    if not rows:
        raise ValueError("未找到对应的龙虎榜记录。")
    row = rows[0]
    return _to_jsonable({"record_id": record_id, "raw": row.get("raw_data") or row})


def build_strategy_readiness_payload(config: AppConfig, store, symbol: str, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    watchlist = {item.symbol: item for item in effective_watchlist(config, store)}
    instrument = watchlist.get(symbol)
    if instrument is None:
        raise ValueError(f"标的 {symbol} 不在观察池中。")
    bars = store.load_bars(symbol, interval="daily", limit=int(config.data.history.get("monitor_minimum_bars", 35))) if hasattr(store, "load_bars") else []
    quote = store.load_latest_quotes([symbol]).get(symbol) if hasattr(store, "load_latest_quotes") else None
    external = store.load_latest_overseas_data() if hasattr(store, "load_latest_overseas_data") else []
    external_map = {str(row.get("symbol")): row for row in external}
    lhb = store.load_lhb_records(symbol=symbol) if hasattr(store, "load_lhb_records") else []
    sector = store.load_instrument_sector(symbol) if hasattr(store, "load_instrument_sector") else None
    futures = store.load_latest_futures_position() if hasattr(store, "load_latest_futures_position") else None
    sector_row = (store.load_sector_mappings(symbol=symbol) if hasattr(store, "load_sector_mappings") else [])[:1]
    task_rows = store.load_data_task_status() if hasattr(store, "load_data_task_status") else []
    profile = resolve_strategy_profile(config, store, symbol, instrument.asset_type)
    broad_ready = all(str(external_map.get(item, {}).get("data_status", "")) == "ready" for item in ("^IXIC", "^GSPC", "^DJI"))
    history_ready = len(bars) >= int(config.data.history.get("monitor_minimum_bars", 35))
    quote_ready = bool(quote)
    seat_ready = any(bool(row.get("seat_detail_available")) for row in lhb)
    weights = {str(key): float(value) for key, value in (profile.get("weights") or {}).items() if str(value).replace(".", "", 1).isdigit()}
    details = []
    for definition in strategy_definitions():
        strategy_id = definition["strategy_id"]
        if strategy_id not in profile.get("enabled", []):
            continue
        if strategy_id in {"technical_composite", "time_series_momentum", "mean_reversion", "relative_strength", "volatility_target", "drawdown_control"}:
            state, reason = ("READY", "日 K 历史数据满足最小长度。") if history_ready else ("UNAVAILABLE", "日 K 历史数据不足。")
        elif strategy_id == "futures_position_sentiment":
            state, reason = ("READY", "期指情绪数据可用。") if futures else ("UNAVAILABLE", "期指情绪数据缺失或已过期。")
        elif strategy_id == "overseas_market_sentiment":
            state, reason = ("READY", "海外大盘数据完整。") if broad_ready else ("UNAVAILABLE", "海外大盘数据缺失。")
            if not sector:
                reason = "板块映射缺失，使用综合板块，仅参考海外大盘。" if broad_ready else reason
        elif strategy_id.startswith("lhb_"):
            if strategy_id == "lhb_reverse_institutional" and lhb:
                state, reason = "READY", "使用龙虎榜汇总净卖额与集合竞价条件。"
            elif strategy_id == "lhb_consensus" and any(row.get("seat_detail_available") or (row.get("star_net_buy") is not None and row.get("institution_net_buy") is not None) for row in lhb):
                state, reason = "READY", "使用龙虎榜席位明细或游资/机构净买额汇总。"
            else:
                state, reason = ("READY", "龙虎榜席位明细可用。") if seat_ready else ("UNAVAILABLE", "龙虎榜席位明细不可用，席位策略已禁用。")
        else:
            state, reason = "READY", "数据依赖已满足。"
        details.append({"strategy_id": strategy_id, "name_zh": definition["name_zh"], "name_en": definition["name_en"], "status": state, "reason": reason, "configured_weight": weights.get(strategy_id, 0), "normalized_weight": 0, "source": "数据库快照", "last_success_at": None, "trade_allowed": state in {"READY", "NEUTRAL"}})
    effective_weight = sum(item["configured_weight"] for item in details if item["status"] in {"READY", "NEUTRAL"})
    source_by_strategy = {
        "technical_composite": "A 股日 K",
        "time_series_momentum": "A 股日 K",
        "mean_reversion": "A 股日 K",
        "relative_strength": "A 股日 K",
        "volatility_target": "A 股日 K",
        "drawdown_control": "组合净值",
        "futures_position_sentiment": str((futures or {}).get("source") or "期指数据库") if futures else "期指数据库",
        "overseas_market_sentiment": ", ".join(sorted({str(row.get("source") or "外部市场") for row in external})) or "外部市场数据库",
        "lhb_follow_star_seats": "龙虎榜数据库",
        "lhb_reverse_institutional": "龙虎榜数据库",
        "lhb_seat_profile": "龙虎榜数据库",
        "lhb_consensus": "龙虎榜数据库",
        "lhb_quant_sector": "龙虎榜数据库",
    }
    task_by_strategy = {
        "technical_composite": {"watchlist_history"},
        "time_series_momentum": {"watchlist_history"},
        "mean_reversion": {"watchlist_history"},
        "relative_strength": {"watchlist_history"},
        "volatility_target": {"watchlist_history"},
        "drawdown_control": {"daily_report"},
        "futures_position_sentiment": {"postmarket_futures"},
        "overseas_market_sentiment": {"external_us_daily", "external_korea_daily"},
        "lhb_follow_star_seats": {"postmarket_lhb"},
        "lhb_reverse_institutional": {"postmarket_lhb"},
        "lhb_seat_profile": {"postmarket_lhb"},
        "lhb_consensus": {"postmarket_lhb"},
        "lhb_quant_sector": {"postmarket_lhb"},
    }
    latest_success_by_task = {}
    for task in task_rows:
        if task.get("status") not in {"success", "degraded"}:
            continue
        task_name = str(task.get("task_name") or "")
        finished_at = task.get("finished_at")
        if finished_at and str(finished_at) > str(latest_success_by_task.get(task_name) or ""):
            latest_success_by_task[task_name] = finished_at
    for item in details:
        if effective_weight:
            item["normalized_weight"] = round(item["configured_weight"] / effective_weight, 6) if item["status"] in {"READY", "NEUTRAL"} else 0
        item["source"] = source_by_strategy.get(item["strategy_id"], "数据库快照")
        item["last_success_at"] = max(
            (str(latest_success_by_task[name]) for name in task_by_strategy.get(item["strategy_id"], set()) if name in latest_success_by_task),
            default=None,
        )
    return _to_jsonable(
        {
            "symbol": symbol,
            "name": instrument.name,
            "trading_enabled": instrument.trading_enabled,
            "quote": {"status": "READY" if quote_ready else "UNAVAILABLE", "reason": "实时行情可用。" if quote_ready else "等待实时行情。"},
            "daily_bars": {"status": "READY" if history_ready else "UNAVAILABLE", "points": len(bars)},
            "sector": {"value": sector or "综合", "defaulted": not bool(sector), "status": "READY" if sector else "DEGRADED", "source": (sector_row[0].get("source") if sector_row else "heuristic")},
            "strategies": details,
            "tasks": store.load_data_task_status() if hasattr(store, "load_data_task_status") else [],
        }
    )


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
