"""Composition root for the StockAI Web application."""

from .instrument_detail import build_instrument_detail_payload
from .web_actions import (
    add_dashboard_watchlist_item,
    confirm_backtest_runs,
    confirm_dashboard_strategy_profile,
    confirm_dashboard_risk_config,
    remove_dashboard_watchlist_item,
    save_dashboard_strategy_profile,
    save_dashboard_risk_config,
    search_watchlist_instruments,
    set_dashboard_watchlist_trading,
)
from .web_assets import render_dashboard_html
from .web_dashboard import (
    ANALYSIS_START_DATE,
    build_dashboard_backtests_payload,
    build_dashboard_calendar_payload,
    build_dashboard_overview_payload,
    build_dashboard_payload,
    build_dashboard_performance_payload,
    build_dashboard_report_payload,
    build_dashboard_reports_payload,
    build_dashboard_strategies_payload,
    _performance_range,
    _query_date,
)
from .web_health import build_ready_payload
from .web_http import BoundedThreadingHTTPServer, PLACEHOLDER_PATTERN, serve_dashboard
from .web_support import MAX_BODY_SIZE, TTLCache, _send, _send_error, _to_jsonable


__all__ = [
    "ANALYSIS_START_DATE",
    "BoundedThreadingHTTPServer",
    "MAX_BODY_SIZE",
    "PLACEHOLDER_PATTERN",
    "TTLCache",
    "add_dashboard_watchlist_item",
    "build_dashboard_backtests_payload",
    "build_dashboard_calendar_payload",
    "build_dashboard_overview_payload",
    "build_dashboard_payload",
    "build_dashboard_performance_payload",
    "build_dashboard_report_payload",
    "build_dashboard_reports_payload",
    "build_dashboard_strategies_payload",
    "build_ready_payload",
    "build_instrument_detail_payload",
    "confirm_backtest_runs",
    "confirm_dashboard_strategy_profile",
    "confirm_dashboard_risk_config",
    "remove_dashboard_watchlist_item",
    "save_dashboard_strategy_profile",
    "save_dashboard_risk_config",
    "render_dashboard_html",
    "search_watchlist_instruments",
    "set_dashboard_watchlist_trading",
    "serve_dashboard",
    "_send",
    "_send_error",
    "_to_jsonable",
    "_performance_range",
    "_query_date",
]
