from __future__ import annotations

import gzip
import json
import base64
import hmac
from binascii import Error as Base64Error
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .analytics import (
    build_benchmark_comparison,
    build_benchmark_outperformance,
    build_profit_calendar,
    build_profit_leaderboard,
    compute_period_returns,
    fill_daily_snapshots,
)
from .config import AppConfig
from .instrument_detail import build_instrument_detail_payload
from .universe import infer_asset_type, validate_hs_symbol
from .watchlist import add_watchlist_item, effective_watchlist, remove_watchlist_item


ANALYSIS_START_DATE = date(2026, 1, 1)


def build_dashboard_payload(
    config: AppConfig,
    store,
    as_of: date | None = None,
    performance_start: date | None = None,
    performance_end: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
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
                ANALYSIS_START_DATE,
                as_of,
                config.paper_account.initial_cash,
            )
        )
    )
    return payload


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
        ANALYSIS_START_DATE,
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
    selected_start, selected_end = _performance_range(performance_start, performance_end, as_of)
    performance_snapshots = fill_daily_snapshots(
        stored_snapshots if stored_snapshots is not None else store.load_portfolio_snapshots(),
        selected_start,
        selected_end,
        config.paper_account.initial_cash,
    )
    benchmark_names = {item.symbol: item.name for item in config.benchmarks}
    benchmark_bars = {
        item.symbol: store.load_bars(item.symbol, interval="daily")
        for item in config.benchmarks
    }
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
        ANALYSIS_START_DATE,
        as_of,
        config.paper_account.initial_cash,
    )
    return _to_jsonable({"profit_calendar": build_profit_calendar(snapshots)})


def build_dashboard_backtests_payload(store) -> dict[str, Any]:
    runs = store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else []
    return _to_jsonable({"backtest_runs": runs})


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
) -> tuple[date, date]:
    start = max(requested_start or ANALYSIS_START_DATE, ANALYSIS_START_DATE)
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


def confirm_backtest_runs(config: AppConfig, store, run_ids: list[int]) -> dict[str, Any]:
    updated = store.update_backtest_run_status(run_ids, "已确认") if hasattr(store, "update_backtest_run_status") else 0
    return _to_jsonable(
        {
            "updated": updated,
            "backtest_runs": store.load_backtest_runs() if hasattr(store, "load_backtest_runs") else [],
        }
    )


def search_watchlist_instruments(config: AppConfig, store, query: str, provider=None, limit: int = 12) -> list[dict[str, str]]:
    text = str(query).strip().upper()
    if len(text) < 2:
        return []
    catalog_matches = store.search_instrument_catalog(text, limit=limit) if hasattr(store, "search_instrument_catalog") else []
    if catalog_matches:
        return catalog_matches
    direct_code = text.split(".", 1)[0]
    if direct_code.isdigit() and len(direct_code) == 6 and text in {direct_code, f"{direct_code}.SH", f"{direct_code}.SZ"}:
        try:
            symbol = validate_hs_symbol(text)
            return [{"symbol": symbol, "name": "名称待目录同步", "asset_type": infer_asset_type(symbol)}]
        except ValueError:
            return []
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in effective_watchlist(config, store):
        if text not in item.symbol and text not in item.name.upper():
            continue
        results.append({"symbol": item.symbol, "name": item.name, "asset_type": item.asset_type})
        seen.add(item.symbol)
    if results:
        return results[:limit]
    if provider is not None and hasattr(provider, "search_instruments"):
        for item in provider.search_instruments(text, limit=limit):
            symbol = str(item.get("symbol") or "")
            if not symbol or symbol in seen:
                continue
            results.append({
                "symbol": symbol,
                "name": str(item.get("name") or symbol),
                "asset_type": str(item.get("asset_type") or "stock"),
            })
            seen.add(symbol)
            if len(results) >= limit:
                break
    return results[:limit]


def add_dashboard_watchlist_item(config: AppConfig, store, payload: dict[str, Any]) -> dict[str, Any]:
    item = add_watchlist_item(
        config,
        store,
        str(payload.get("symbol") or ""),
        str(payload.get("name") or ""),
        str(payload.get("asset_type") or "") or None,
    )
    return _to_jsonable({"item": item, "dashboard": build_dashboard_overview_payload(config, store)})


def remove_dashboard_watchlist_item(config: AppConfig, store, symbol: str) -> dict[str, Any]:
    removed = remove_watchlist_item(config, store, symbol)
    overview = build_dashboard_overview_payload(config, store)
    return _to_jsonable({"removed": removed, "watchlist": overview["watchlist"], "dashboard": overview})


def serve_dashboard(config: AppConfig, store, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    class DashboardHandler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            if not config.web.require_basic_auth:
                return True
            expected_username = config.web.username
            expected_password = config.web.password
            if not expected_username or not expected_password or expected_username.startswith("${") or expected_password.startswith("${"):
                return False
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                username, password = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)
            except (Base64Error, ValueError, UnicodeDecodeError):
                return False
            return hmac.compare_digest(username, expected_username) and hmac.compare_digest(password, expected_password)

        def _require_authorization(self) -> bool:
            if self._authorized():
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="StockAI"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def do_GET(self) -> None:
            request = urlparse(self.path)
            if request.path == "/healthz":
                _send(self, "application/json; charset=utf-8", b'{"status":"ok"}')
                return
            if not self._require_authorization():
                return
            if request.path == "/":
                _send(self, "text/html; charset=utf-8", render_dashboard_html().encode("utf-8"))
                return
            if request.path == "/api/dashboard/overview":
                payload = build_dashboard_overview_payload(config, store)
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            if request.path == "/api/dashboard/performance":
                try:
                    query = parse_qs(request.query)
                    payload = build_dashboard_performance_payload(
                        config,
                        store,
                        performance_start=_query_date(query, "performance_start"),
                        performance_end=_query_date(query, "performance_end"),
                    )
                except ValueError as exc:
                    _send_error(self, 400, str(exc))
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            if request.path == "/api/dashboard/calendar":
                payload = build_dashboard_calendar_payload(config, store)
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            if request.path == "/api/dashboard/backtests":
                payload = build_dashboard_backtests_payload(store)
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            instrument_prefix = "/api/instruments/"
            if request.path.startswith(instrument_prefix) and request.path.endswith("/detail"):
                symbol = unquote(request.path[len(instrument_prefix):-len("/detail")]).rstrip("/")
                try:
                    payload = _to_jsonable(build_instrument_detail_payload(config, store, symbol))
                except ValueError as exc:
                    _send_error(self, 400, str(exc))
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            if request.path == "/api/dashboard/reports":
                query = parse_qs(request.query)
                try:
                    limit = min(200, max(1, int(query.get("limit", ["60"])[0])))
                    offset = max(0, int(query.get("offset", ["0"])[0]))
                except ValueError:
                    _send_error(self, 400, "limit 和 offset 必须是整数。")
                    return
                payload = build_dashboard_reports_payload(store, limit, offset)
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            report_prefix = "/api/dashboard/reports/"
            if request.path.startswith(report_prefix):
                try:
                    report_date = date.fromisoformat(unquote(request.path[len(report_prefix):]))
                except ValueError:
                    _send_error(self, 400, "日报日期必须使用 YYYY-MM-DD 格式。")
                    return
                payload = build_dashboard_report_payload(store, report_date)
                if payload["daily_report"] is None:
                    _send_error(self, 404, "未找到该日期的日报。")
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            if request.path == "/api/dashboard":
                try:
                    query = parse_qs(request.query)
                    payload_data = build_dashboard_payload(
                        config,
                        store,
                        performance_start=_query_date(query, "performance_start"),
                        performance_end=_query_date(query, "performance_end"),
                    )
                except ValueError as exc:
                    _send_error(self, 400, str(exc))
                    return
                payload = json.dumps(payload_data, ensure_ascii=False).encode("utf-8")
                _send(self, "application/json; charset=utf-8", payload)
                return
            if request.path == "/api/watchlist/search":
                query = parse_qs(request.query).get("q", [""])[0]
                results = search_watchlist_instruments(config, store, query)
                status = store.instrument_catalog_status() if hasattr(store, "instrument_catalog_status") else {"count": 0, "synced_date": ""}
                payload = {"items": results, "catalog": status}
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:
            if not self._require_authorization():
                return
            request = urlparse(self.path)
            if request.path == "/api/backtests/confirm":
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                try:
                    data = json.loads(body)
                    ids = [int(item) for item in data.get("ids", [])]
                except (TypeError, ValueError, json.JSONDecodeError):
                    self.send_error(400, "Bad Request")
                    return
                payload = json.dumps(confirm_backtest_runs(config, store, ids), ensure_ascii=False).encode("utf-8")
                _send(self, "application/json; charset=utf-8", payload)
                return
            if request.path == "/api/watchlist":
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                try:
                    data = json.loads(body)
                    payload = add_dashboard_watchlist_item(config, store, data)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    _send_error(self, 400, str(exc))
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            self.send_error(404, "Not Found")

        def do_DELETE(self) -> None:
            if not self._require_authorization():
                return
            request = urlparse(self.path)
            prefix = "/api/watchlist/"
            if request.path.startswith(prefix):
                try:
                    payload = remove_dashboard_watchlist_item(config, store, unquote(request.path[len(prefix):]))
                except ValueError as exc:
                    _send_error(self, 400, str(exc))
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            self.send_error(404, "Not Found")

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.serve_forever()
    return server


def render_dashboard_html() -> str:
    try:
        return Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    except OSError:
        return _render_dashboard_html_legacy()


def _render_dashboard_html_legacy() -> str:
    return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI-Agent 实时交易驾驶舱</title>
  <link rel="stylesheet" href="https://unpkg.com/antd@5.29.3/dist/reset.css">
  <style>
    :root { color-scheme: light; --ink:#23252b; --sub:#6f7682; --ghost:#9aa0aa; --line:#e8ebef; --buy:#ef3348; --sell:#00a66a; --gold:#b58a4d; --paper:#ffffff; --wash:#f6f7f9; --tint:#fff4f5; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:"DIN Alternate","Avenir Next","PingFang SC","Microsoft YaHei",sans-serif; background:var(--wash); color:var(--ink); overflow-x:hidden; }
    button { font:inherit; }
    header { background:var(--paper); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }
    .bar, main { width:100%; margin:0; }
    .bar { padding:13px clamp(14px, 2vw, 28px); display:flex; align-items:center; justify-content:space-between; gap:12px; }
    h1 { font-size:19px; margin:0; font-weight:800; letter-spacing:0; }
    .app-tabs { display:flex; gap:0; padding:0 clamp(10px, 2vw, 28px) 10px; border-top:1px solid var(--line); }
    .app-tab { min-width:112px; padding:10px 18px; border:1px solid #cfd3d9; border-right:0; background:#fff; color:var(--ghost); font-weight:800; cursor:pointer; }
    .app-tab:last-child { border-right:1px solid #cfd3d9; }
    .app-tab.active { color:var(--buy); background:var(--tint); outline:1px solid var(--buy); }
    main { padding:12px clamp(10px, 2vw, 28px) 28px; }
    .view { display:grid; gap:12px; }
    .view.hidden { display:none; }
    section { background:var(--paper); border:1px solid var(--line); border-radius:8px; padding:14px; min-width:0; }
    h2 { margin:0 0 12px; font-size:19px; line-height:1.15; font-weight:850; }
    h2::before { content:""; display:inline-block; width:5px; height:24px; margin-right:10px; background:var(--buy); vertical-align:-5px; }
    .market-ribbon { padding:0; overflow:hidden; border-color:#dfe3e8; }
    .ticker-track { display:flex; width:max-content; animation:tape 34s linear infinite; }
    .ticker-item { display:flex; align-items:center; gap:7px; padding:10px 18px; border-right:1px solid var(--line); white-space:nowrap; color:var(--sub); }
    .ticker-item strong { color:var(--ink); }
    .ticker-dot { width:7px; height:7px; border-radius:50%; background:var(--buy); box-shadow:0 0 0 5px rgba(239,51,72,.08); }
    @keyframes tape { from { transform:translateX(0); } to { transform:translateX(-50%); } }
    .hero-board { padding:0; overflow:hidden; }
    .hero-top { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(220px,.75fr); gap:0; }
    .asset-panel { padding:18px 16px 16px; background:linear-gradient(180deg,#fff,#fff7f8); border-right:1px solid var(--line); }
    .eyebrow { color:var(--ghost); font-size:12px; letter-spacing:.04em; }
    .asset-value { margin-top:6px; font-size:34px; line-height:1; color:var(--buy); font-weight:850; font-variant-numeric:tabular-nums; }
    .asset-sub { display:flex; gap:14px; margin-top:12px; color:var(--sub); flex-wrap:wrap; }
    .pulse-panel { padding:16px; display:grid; gap:8px; align-content:center; }
    .pulse-line { display:flex; justify-content:space-between; gap:14px; border-bottom:1px solid var(--line); padding-bottom:8px; }
    .pulse-line:last-child { border-bottom:0; padding-bottom:0; }
    .metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; background:var(--line); border-top:1px solid var(--line); }
    .metric { background:#fff; padding:11px 10px; min-height:72px; }
    .metric span { color:var(--ghost); font-size:12px; }
    .metric strong { display:block; margin-top:7px; font-size:18px; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
    .tabs, .sort-bar { display:flex; justify-content:center; margin:2px auto 12px; max-width:560px; border:1px solid #cfd3d9; background:#fff; }
    .tab, .sort-btn { flex:1; min-width:0; padding:10px 8px; text-align:center; color:var(--ghost); border:0; border-right:1px solid #cfd3d9; background:transparent; font-weight:700; cursor:pointer; }
    .tab:last-child, .sort-btn:last-child { border-right:0; }
    .tab.active, .sort-btn.active { color:var(--buy); background:var(--tint); outline:1px solid var(--buy); }
    .chart-summary { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:6px; }
    .legend-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }
    canvas { display:block; width:100%; max-width:100%; height:340px; border:0; background:#fff; }
    .table-wrap { width:100%; overflow-x:auto; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { padding:9px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align:left; }
    th { color:var(--ghost); cursor:pointer; user-select:none; font-weight:650; }
    .rank-list .rank-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; padding:14px 0; border-bottom:1px solid var(--line); align-items:center; }
    .rank-name { font-size:21px; font-weight:850; }
    .rank-code { color:var(--ghost); margin-top:2px; }
    .rank-profit { font-size:26px; color:var(--buy); text-align:right; font-variant-numeric:tabular-nums; }
    .calendar-tools { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:4px 0 14px; flex-wrap:wrap; }
    .calendar-tabs { display:flex; gap:4px; padding:5px; border-radius:6px; background:#f0f1f4; }
    .calendar-tabs .tab { min-width:64px; border:0; border-radius:4px; padding:8px 16px; }
    .calendar-tabs .tab.active { background:#fff; color:var(--buy); outline:0; box-shadow:0 1px 3px rgba(35,37,43,.08); }
    .antd-picker-mount { min-width:138px; }
    .calendar-tools .ant-picker { width:138px; height:38px; border-radius:6px; font-family:inherit; box-shadow:0 1px 2px rgba(35,37,43,.04); }
    .calendar-tools .ant-picker .ant-picker-input > input { font:inherit; font-size:16px; font-weight:800; color:var(--ink); }
    .calendar-tools .ant-picker-focused { box-shadow:0 0 0 3px rgba(22,119,255,.12); }
    .calendar-period-popup .ant-picker-header { height:48px; }
    .calendar-period-popup .ant-picker-header-view { font-size:18px; font-weight:850; }
    .calendar-period-popup .ant-picker-cell-inner { font-size:18px; font-weight:700; }
    .calendar-period-fallback { height:38px; min-width:138px; border:1px solid #d9d9d9; border-radius:6px; background:#fff; color:var(--ink); font-size:16px; font-weight:800; }
    .calendar-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
    .month-income { font-size:25px; color:var(--buy); font-weight:850; font-variant-numeric:tabular-nums; }
    .value-toggle { border:0; background:transparent; color:#c48b32; padding:6px 0; font-size:16px; font-weight:800; cursor:pointer; }
    .weekdays, .calendar { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:3px; }
    .weekdays div { text-align:center; color:#666; padding:8px 0; background:#f3f4f6; }
    .cell { background:#f7f7f7; min-height:86px; padding:8px 5px; text-align:center; overflow:hidden; }
    .cell.blank { background:#fbfbfc; }
    .cell.win { background:#fdebed; }
    .cell.loss { background:#e8f6ef; }
    .cell .day { font-size:18px; }
    .cell .pnl { margin-top:8px; font-size:13px; white-space:nowrap; }
    .year-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
    .year-cell { background:#f7f7f7; padding:12px; min-height:82px; border-left:4px solid transparent; }
    .year-cell.win { background:#fdebed; border-left-color:var(--buy); }
    .year-cell.loss { background:#e8f6ef; border-left-color:var(--sell); }
    .backtest-toolbar { display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
    .primary-btn, .confirm-btn { border:1px solid var(--buy); background:var(--buy); color:#fff; padding:8px 12px; font-weight:800; cursor:pointer; border-radius:6px; }
    .confirm-btn { padding:6px 10px; font-size:12px; }
    .primary-btn:disabled, .confirm-btn:disabled { opacity:.45; cursor:not-allowed; }
    .status-badge { display:inline-block; padding:4px 8px; border-radius:999px; background:var(--tint); color:var(--buy); font-weight:750; }
    .param-list { display:flex; gap:6px; justify-content:flex-end; flex-wrap:wrap; }
    .param-pill { border:1px solid var(--line); background:#fafafa; border-radius:999px; padding:3px 7px; color:var(--sub); }
    .pos { color:var(--buy); }
    .neg { color:var(--sell); }
    .muted { color:var(--ghost); font-size:12px; }
    .empty { color:var(--ghost); padding:12px 0; }
    :focus-visible { outline:2px solid var(--buy); outline-offset:2px; }
    @media (prefers-reduced-motion: reduce) { .ticker-track { animation:none; } }
    @media (min-width: 1280px) { .metric-grid { grid-template-columns:repeat(6,minmax(0,1fr)); } .chart-summary { grid-template-columns:repeat(4,minmax(0,1fr)); } .year-grid { grid-template-columns:repeat(6,minmax(0,1fr)); } }
    @media (max-width: 760px) { .hero-top { grid-template-columns:1fr; } .asset-panel { border-right:0; border-bottom:1px solid var(--line); } .metric-grid, .chart-summary { grid-template-columns:1fr 1fr; } .bar { align-items:flex-start; flex-direction:column; } canvas { height:310px; } .cell { min-height:74px; } }
    @media (max-width: 520px) { .metric-grid, .chart-summary, .year-grid { grid-template-columns:1fr 1fr; } section { padding:12px 10px; } .asset-value { font-size:30px; } .calendar-tools { align-items:flex-start; flex-direction:column; } .cell { min-height:60px; padding:6px 2px; } .cell .day { font-size:16px; } .cell .pnl { font-size:11px; } }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <h1>AI-Agent 实时交易驾驶舱</h1>
      <div class="muted" id="updated">加载中</div>
    </div>
    <div class="app-tabs" id="appTabs">
      <button class="app-tab active" data-view="dashboardView">交易看板</button>
      <button class="app-tab" data-view="backtestView">回测记录</button>
    </div>
  </header>
  <main>
    <div class="view" id="dashboardView">
      <section class="market-ribbon"><div class="ticker-track" id="tradeTape"></div></section>
      <section class="hero-board">
        <div class="hero-top">
          <div class="asset-panel">
            <div class="eyebrow">模拟盘总资产</div>
            <div class="asset-value" id="totalAsset">--</div>
            <div class="asset-sub"><span id="cashLine">现金 --</span><span id="exposureLine">仓位 --</span><span id="positionLine">持仓 --</span></div>
          </div>
          <div class="pulse-panel">
            <div class="pulse-line"><span class="muted">盯盘状态</span><strong id="watchStatus">模拟盯盘中</strong></div>
            <div class="pulse-line"><span class="muted">今日决策</span><strong id="decisionCount">0 条</strong></div>
            <div class="pulse-line"><span class="muted">回测候选</span><strong id="backtestCount">0 组</strong></div>
          </div>
        </div>
        <div class="metric-grid" id="metrics"></div>
      </section>
      <section>
        <h2>盈亏分析</h2>
        <div class="tabs" id="chartTabs">
          <button class="tab" data-mode="pnl">收益</button>
          <button class="tab active" data-mode="return">收益率</button>
          <button class="tab" data-mode="asset">资产轨迹</button>
        </div>
        <div class="chart-summary" id="chartSummary"></div>
        <canvas id="lineChart" width="860" height="420"></canvas>
      </section>
      <section><h2>实时持仓</h2><div id="positions"></div></section>
      <section><h2>盈亏排行榜</h2><div id="leaderboard"></div></section>
      <section>
        <h2>盈亏日历</h2>
        <div class="calendar-tools">
          <div class="calendar-tabs" id="calendarTabs">
            <button class="tab" data-mode="yearly">年</button>
            <button class="tab active" data-mode="monthly">月</button>
          </div>
          <div class="antd-picker-mount" id="calendarPeriodPicker"></div>
        </div>
        <div class="calendar-head"><div><span id="calendarPeriodLabel">月总收益</span>：<span class="month-income" id="monthIncome">0.00</span></div><button class="value-toggle" id="calendarValueToggle" onclick="toggleCalendarValue()">⇄ 看收益率</button></div>
        <div class="weekdays"><div>日</div><div>一</div><div>二</div><div>三</div><div>四</div><div>五</div><div>六</div></div>
        <div class="calendar" id="calendarGrid"></div>
      </section>
    </div>
    <div class="view hidden" id="backtestView">
      <section>
        <h2>回测记录</h2>
        <div class="backtest-toolbar">
          <div class="muted">确认后的参数仍需在配置中显式启用，不会自动替换当前策略。</div>
          <button class="primary-btn" id="confirmSelectedBtn" onclick="confirmSelectedBacktests()">批量确认</button>
        </div>
        <div id="backtests"></div>
      </section>
    </div>
  </main>
  <script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
  <script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/dayjs@1.11.22/dayjs.min.js"></script>
  <script src="https://unpkg.com/dayjs@1.11.22/locale/zh-cn.js"></script>
  <script src="https://unpkg.com/antd@5.29.3/dist/antd.min.js"></script>
  <script>
    const fmtMoney = v => Number(v || 0).toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
    const fmtPct = v => (Number(v || 0) * 100).toFixed(2) + '%';
    const tone = v => Number(v) >= 0 ? 'pos' : 'neg';
    let rankRows = [], sortKey = 'profit_amount', sortAsc = false, chartMode = 'return', calendarMode = 'monthly', calendarValueMode = 'amount', calendarPeriod = null, calendarPickerRoot = null, latestData = null;
    async function load() {
      const res = await fetch('/api/dashboard');
      const data = await res.json();
      latestData = data;
      document.getElementById('updated').textContent = '最近刷新：' + new Date().toLocaleString('zh-CN');
      renderHero(data); renderMetrics(data); renderPositions(data); renderLine(data); renderLeaderboard(data); renderCalendar(data); renderBacktests(data);
    }
    function bindTabs() {
      document.querySelectorAll('#appTabs .app-tab').forEach(btn => btn.addEventListener('click', () => {
        const target = btn.dataset.view;
        document.querySelectorAll('#appTabs .app-tab').forEach(x => x.classList.toggle('active', x === btn));
        document.querySelectorAll('.view').forEach(x => x.classList.toggle('hidden', x.id !== target));
      }));
      document.querySelectorAll('#chartTabs .tab').forEach(btn => btn.addEventListener('click', () => {
        chartMode = btn.dataset.mode;
        document.querySelectorAll('#chartTabs .tab').forEach(x => x.classList.toggle('active', x === btn));
        if (latestData) renderLine(latestData);
      }));
      document.querySelectorAll('#calendarTabs .tab').forEach(btn => btn.addEventListener('click', () => {
        calendarMode = btn.dataset.mode;
        calendarPeriod = null;
        document.querySelectorAll('#calendarTabs .tab').forEach(x => x.classList.toggle('active', x === btn));
        if (latestData) renderCalendar(latestData);
      }));
    }
    function renderHero(data) {
      const p = data.portfolio;
      const asset = Number(p.total_asset || 0), market = Number(p.total_market_value || 0);
      document.getElementById('totalAsset').textContent = fmtMoney(asset);
      document.getElementById('cashLine').textContent = '现金 ' + fmtMoney(p.cash);
      document.getElementById('exposureLine').textContent = '仓位 ' + fmtPct(asset ? market / asset : 0);
      document.getElementById('positionLine').textContent = '持仓 ' + p.positions.length + ' 个';
      document.getElementById('decisionCount').textContent = (data.today_decisions || []).length + ' 条';
      document.getElementById('backtestCount').textContent = (data.backtest_runs || []).length + ' 组';
      const fills = data.recent_fills || [];
      const tape = [
        ['盯盘', '模拟盘实时运行'],
        ['总资产', fmtMoney(p.total_asset)],
        ['现金', fmtMoney(p.cash)],
        ['持仓市值', fmtMoney(p.total_market_value)],
        ['最近成交', fills.length ? `${fills[fills.length - 1].direction} ${fills[fills.length - 1].symbol}` : '暂无成交'],
        ['回测', (data.backtest_runs || [])[0]?.status || '待同步']
      ];
      const html = tape.concat(tape).map(x => `<div class="ticker-item"><i class="ticker-dot"></i><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
      document.getElementById('tradeTape').innerHTML = html;
    }
    function renderMetrics(data) {
      const p = data.portfolio;
      const lastReturn = (data.period_returns.daily || []).slice(-1)[0]?.return_rate || 0;
      document.getElementById('metrics').innerHTML = [
        ['今日收益率', fmtPct(lastReturn)], ['现金余额', fmtMoney(p.cash) + ' 元'],
        ['持仓市值', fmtMoney(p.total_market_value) + ' 元'], ['最近成交', (data.recent_fills || []).length + ' 笔']
      ].map(x => `<div class="metric"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
    }
    function renderPositions(data) {
      const rows = data.portfolio.positions || [];
      document.getElementById('positions').innerHTML = table(['证券代码','数量','可卖','成本','最新价','市值','浮盈浮亏'], rows.map(x => [
        x.symbol, x.quantity, x.available_quantity, x.average_cost, x.last_price, fmtMoney(x.market_value), `<span class="${tone(x.unrealized_pnl)}">${fmtMoney(x.unrealized_pnl)}</span>`
      ]));
    }
    function renderLine(data) {
      const canvas = document.getElementById('lineChart'), ctx = canvas.getContext('2d');
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(320, Math.floor(rect.width * ratio));
      canvas.height = Math.floor(310 * ratio);
      ctx.setTransform(ratio,0,0,ratio,0,0);
      const w = canvas.width / ratio, h = canvas.height / ratio;
      ctx.clearRect(0,0,w,h);
      const points = chartPoints(data);
      const series = [...new Set(points.map(p => p.series))];
      const colors = ['#ef5b5b','#b98a4b','#09a66d','#7c3aed','#d97706','#0891b2'];
      const values = points.map(p => Number(p.value));
      let min = chartMode === 'return' ? Math.min(-0.01, ...values) : Math.min(...values);
      let max = chartMode === 'return' ? Math.max(0.01, ...values) : Math.max(...values);
      if (!Number.isFinite(min) || !Number.isFinite(max)) { min = -0.01; max = 0.01; }
      if (min === max) {
        const pad = chartMode === 'return' ? 0.01 : Math.max(1, Math.abs(max) * 0.02);
        min -= pad; max += pad;
      }
      const dates = points.map(p => new Date(p.day + 'T00:00:00').getTime());
      const minDate = Math.min(...dates), maxDate = Math.max(...dates);
      const left = 46, right = 16, top = 18, bottom = 34;
      const chartW = w - left - right, chartH = h - top - bottom;
      ctx.strokeStyle = '#e5e7eb'; ctx.lineWidth = 1; ctx.font = '12px sans-serif'; ctx.fillStyle = '#8a8f98';
      for (let i=0; i<5; i++) {
        const y = top + i * chartH / 4;
        const label = max - i * (max - min) / 4;
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w-right, y); ctx.stroke();
        ctx.fillText(chartLabel(label), 4, y + 4);
      }
      ctx.fillText(new Date(minDate).toISOString().slice(0,10), left, h - 8);
      ctx.fillText(new Date(maxDate).toISOString().slice(0,10), Math.max(left, w - 112), h - 8);
      const summary = series.slice(0, 6).map((name, idx) => {
        const rows = points.filter(p => p.series === name);
        const last = rows[rows.length - 1];
        return `<div class="metric"><span><i class="legend-dot" style="background:${colors[idx % colors.length]}"></i>${name}</span><strong class="${tone(last?.value || 0)}">${chartLabel(last?.value || 0)}</strong></div>`;
      }).join('');
      document.getElementById('chartSummary').innerHTML = summary;
      series.forEach((name, idx) => {
        const rows = points.filter(p => p.series === name);
        ctx.strokeStyle = colors[idx % colors.length]; ctx.lineWidth = 2; ctx.beginPath();
        rows.forEach((p, i) => {
          const t = new Date(p.day + 'T00:00:00').getTime();
          const x = left + (maxDate === minDate ? 0 : (t - minDate) * chartW / (maxDate - minDate));
          const y = top + chartH - (Number(p.value) - min) * chartH / (max - min);
          if (i === 0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        });
        ctx.stroke();
      });
    }
    function chartPoints(data) {
      if (chartMode === 'return') return (data.benchmark_comparison || []).map(x => ({series:x.series, day:x.day, value:Number(x.return_rate)}));
      const curve = data.equity_curve || [];
      const base = Number(curve[0]?.total_asset || 0);
      return curve.map(x => ({
        series: chartMode === 'asset' ? 'AI-Agent 资产' : 'AI-Agent 收益',
        day: x.day,
        value: chartMode === 'asset' ? Number(x.total_asset || 0) : Number(x.total_asset || 0) - base
      }));
    }
    function chartLabel(v) {
      if (chartMode === 'return') return fmtPct(v);
      return fmtMoney(v);
    }
    function renderLeaderboard(data) {
      rankRows = data.profit_leaderboard || rankRows;
      const rows = [...rankRows].sort((a,b) => {
        const va = a[sortKey], vb = b[sortKey];
        const result = typeof va === 'string' ? va.localeCompare(vb, 'zh-CN') : Number(va) - Number(vb);
        return sortAsc ? result : -result;
      });
      const tabs = '<div class="tabs"><button class="tab active">全部</button><button class="tab">股票盈亏</button><button class="tab">ETF盈亏</button></div>';
      const sorts = `<div class="sort-bar"><button class="sort-btn ${sortKey === 'profit_amount' ? 'active' : ''}" onclick="sortRank('profit_amount')">按盈亏</button><button class="sort-btn ${sortKey === 'return_rate' ? 'active' : ''}" onclick="sortRank('return_rate')">按收益率</button><button class="sort-btn ${sortKey === 'holding_days' ? 'active' : ''}" onclick="sortRank('holding_days')">按持仓天数</button></div>`;
      const list = rows.length ? `<div class="rank-list">${rows.map(x => `<div class="rank-row"><div><div class="rank-name">${x.name}</div><div class="rank-code">${x.symbol}</div><div class="muted">持仓 ${x.holding_days} 天 · 收益率 ${fmtPct(x.return_rate)}</div></div><div class="rank-profit">${fmtMoney(x.profit_amount)}</div></div>`).join('')}</div>` : '<div class="muted">暂无持仓盈亏数据</div>';
      document.getElementById('leaderboard').innerHTML = tabs + sorts + list;
    }
    function renderCalendar(data) {
      const options = calendarOptions(data);
      if (!calendarPeriod || !options.includes(calendarPeriod)) calendarPeriod = options[options.length - 1] || '2026-01';
      document.getElementById('calendarValueToggle').textContent = calendarValueMode === 'amount' ? '⇄ 看收益率' : '⇄ 看收益额';
      mountCalendarPeriodPicker(data, options);
      if (calendarMode === 'yearly') {
        renderYearCalendar(data);
        return;
      }
      renderMonthCalendar(data);
    }
    function renderMonthCalendar(data) {
      document.querySelector('.weekdays').style.display = 'grid';
      document.getElementById('calendarGrid').className = 'calendar';
      const rows = data.profit_calendar.daily || [];
      const monthRows = rows.filter(x => x.period.startsWith(calendarPeriod));
      const monthCell = (data.profit_calendar.monthly || []).find(x => x.period === calendarPeriod) || {pnl:0, return_rate:0};
      const [year, month] = calendarPeriod.split('-').map(Number);
      const first = new Date(year, month - 1, 1);
      const daysInMonth = new Date(year, month, 0).getDate();
      const byDay = Object.fromEntries(monthRows.map(x => [Number(x.period.slice(8,10)), x]));
      const leading = Array(first.getDay()).fill('<div class="cell blank"></div>').join('');
      const trailingCount = (7 - ((first.getDay() + daysInMonth) % 7)) % 7;
      const trailing = Array(trailingCount).fill('<div class="cell blank"></div>').join('');
      document.getElementById('calendarPeriodLabel').textContent = `${month}月${calendarValueMode === 'amount' ? '总收益' : '收益率'}`;
      document.getElementById('monthIncome').textContent = calendarValueMode === 'amount' ? fmtMoney(monthCell.pnl) : fmtPct(monthCell.return_rate);
      const days = Array.from({length: daysInMonth}, (_, index) => {
        const day = index + 1;
        const x = byDay[day] || {pnl:0, return_rate:0};
        const pnl = Number(x.pnl || 0);
        const cls = pnl > 0 ? 'win' : pnl < 0 ? 'loss' : '';
        const text = calendarValueMode === 'amount' ? fmtMoney(pnl) : fmtPct(x.return_rate || 0);
        return `<div class="cell ${cls}"><div class="day">${String(day).padStart(2,'0')}</div><div class="pnl ${tone(pnl)}">${text}</div></div>`;
      }).join('');
      document.getElementById('calendarGrid').innerHTML = leading + days + trailing;
    }
    function renderYearCalendar(data) {
      document.querySelector('.weekdays').style.display = 'none';
      document.getElementById('calendarGrid').className = 'year-grid';
      const rows = data.profit_calendar.monthly || [];
      const byMonth = Object.fromEntries(rows.filter(x => x.period.startsWith(calendarPeriod + '-')).map(x => [Number(x.period.slice(5,7)), x]));
      const yearlyCell = (data.profit_calendar.yearly || []).find(x => x.period === calendarPeriod) || {pnl:0, return_rate:0};
      document.getElementById('calendarPeriodLabel').textContent = `${calendarPeriod}年${calendarValueMode === 'amount' ? '总收益' : '收益率'}`;
      document.getElementById('monthIncome').textContent = calendarValueMode === 'amount' ? fmtMoney(yearlyCell.pnl) : fmtPct(yearlyCell.return_rate);
      document.getElementById('calendarGrid').innerHTML = Array.from({length: 12}, (_, index) => {
        const month = index + 1;
        const x = byMonth[month] || {pnl:0, return_rate:0};
        const pnl = Number(x.pnl || 0);
        const cls = pnl > 0 ? 'win' : pnl < 0 ? 'loss' : '';
        const value = calendarValueMode === 'amount' ? fmtMoney(pnl) : fmtPct(x.return_rate || 0);
        return `<div class="year-cell ${cls}"><div class="muted">${month}月</div><strong class="${tone(pnl)}">${value}</strong></div>`;
      }).join('');
    }
    function toggleCalendarValue() {
      calendarValueMode = calendarValueMode === 'amount' ? 'rate' : 'amount';
      if (latestData) renderCalendar(latestData);
    }
    function zhDatePickerLocale() {
      return {
        lang: {
          locale: 'zh_CN',
          placeholder: '请选择日期',
          yearPlaceholder: '请选择年份',
          monthPlaceholder: '请选择月份',
          rangePlaceholder: ['开始日期', '结束日期'],
          today: '今天',
          now: '此刻',
          backToToday: '返回今天',
          ok: '确定',
          clear: '清除',
          month: '月',
          year: '年',
          timeSelect: '选择时间',
          dateSelect: '选择日期',
          weekSelect: '选择周',
          monthSelect: '选择月份',
          yearSelect: '选择年份',
          decadeSelect: '选择年代',
          yearFormat: 'YYYY年',
          dateFormat: 'YYYY年M月D日',
          dayFormat: 'D日',
          dateTimeFormat: 'YYYY年M月D日 HH时mm分ss秒',
          monthBeforeYear: false,
          previousMonth: '上个月',
          nextMonth: '下个月',
          previousYear: '上一年',
          nextYear: '下一年',
          previousDecade: '上一年代',
          nextDecade: '下一年代',
          previousCentury: '上一世纪',
          nextCentury: '下一世纪',
          shortWeekDays: ['日', '一', '二', '三', '四', '五', '六'],
          shortMonths: ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']
        },
        timePickerLocale: { placeholder: '请选择时间' }
      };
    }
    function mountCalendarPeriodPicker(data, options) {
      const target = document.getElementById('calendarPeriodPicker');
      if (!window.React || !window.ReactDOM || !window.dayjs || !window.antd?.DatePicker) {
        target.innerHTML = `<button class="calendar-period-fallback" type="button">${calendarOptionLabel(calendarPeriod)}</button>`;
        return;
      }
      window.dayjs.locale('zh-cn');
      const React = window.React, DatePicker = window.antd.DatePicker, ConfigProvider = window.antd.ConfigProvider;
      const antdLocale = window.antd.locale?.zh_CN || window.antd.locales?.zh_CN || window.antd.zh_CN;
      const pickerLocale = zhDatePickerLocale();
      const optionSet = new Set(options);
      const picker = calendarMode === 'yearly' ? 'year' : 'month';
      const value = dayjs(calendarPeriod + (calendarMode === 'yearly' ? '-01-01' : '-01'));
      const disabledDate = current => {
        if (!current) return false;
        const key = calendarMode === 'yearly' ? current.format('YYYY') : current.format('YYYY-MM');
        return !optionSet.has(key);
      };
      const onChange = value => {
        if (!value) return;
        calendarPeriod = calendarMode === 'yearly' ? value.format('YYYY') : value.format('YYYY-MM');
        if (latestData) renderCalendar(latestData);
      };
      const pickerNode = React.createElement(DatePicker, {
        picker,
        value,
        allowClear: false,
        inputReadOnly: true,
        format: calendarMode === 'yearly' ? 'YYYY年' : 'YYYY-MM',
        locale: pickerLocale,
        popupClassName: 'calendar-period-popup',
        getPopupContainer: () => target,
        disabledDate,
        onChange
      });
      if (!calendarPickerRoot) calendarPickerRoot = ReactDOM.createRoot(target);
      calendarPickerRoot.render(ConfigProvider && antdLocale
        ? React.createElement(ConfigProvider, {locale: antdLocale}, pickerNode)
        : pickerNode);
    }
    function calendarOptions(data) {
      const curve = data.equity_curve || [];
      const firstDay = curve[0]?.day || '2026-01-01';
      const lastDay = curve[curve.length - 1]?.day || firstDay;
      const startYear = Number(firstDay.slice(0,4));
      const endYear = Number(lastDay.slice(0,4));
      if (calendarMode === 'yearly') {
        return Array.from({length: endYear - startYear + 1}, (_, index) => String(startYear + index));
      }
      const [startY, startM] = firstDay.slice(0,7).split('-').map(Number);
      const [endY, endM] = lastDay.slice(0,7).split('-').map(Number);
      const result = [];
      for (let year = startY; year <= endY; year++) {
        const from = year === startY ? startM : 1;
        const to = year === endY ? endM : 12;
        for (let month = from; month <= to; month++) result.push(`${year}-${String(month).padStart(2,'0')}`);
      }
      return result;
    }
    function calendarOptionLabel(item) {
      if (calendarMode === 'yearly') return `${item}年`;
      const [year, month] = item.split('-');
      return `${year}-${month}`;
    }
    function renderBacktests(data) {
      const rows = data.backtest_runs || [];
      if (!rows.length) {
        document.getElementById('backtests').innerHTML = '<div class="empty">暂无回测记录。运行 optimize-strategy 后会在这里审批候选参数。</div>';
        return;
      }
      document.getElementById('backtests').innerHTML = `<div class="table-wrap"><table><thead><tr><th><input type="checkbox" onchange="toggleAllBacktests(this.checked)"></th><th>策略</th><th>参数</th><th>状态</th><th>操作栏</th></tr></thead><tbody>${rows.map(run => {
        const confirmed = run.status === '已确认';
        return `<tr><td><input class="backtest-check" type="checkbox" value="${run.id}" ${confirmed ? 'disabled' : ''}></td><td>${strategyName(run.strategy_id)}<div class="muted">${escapeHtml(run.strategy_id)}</div></td><td><div class="param-list">${parameterPills(run.parameters)}</div></td><td><span class="status-badge">${escapeHtml(run.status)}</span></td><td><button class="confirm-btn" onclick="confirmBacktests([${run.id}])" ${confirmed ? 'disabled' : ''}>确认</button></td></tr>`;
      }).join('')}</tbody></table></div>`;
    }
    function strategyName(id) {
      return {momentum_grid:'动量网格策略', mean_reversion_grid:'均值回归策略', relative_strength:'相对强弱轮动'}[id] || id;
    }
    function parameterPills(parameters) {
      return Object.entries(parameters || {}).map(([key, value]) => `<span class="param-pill">${escapeHtml(key)}：${escapeHtml(value)}</span>`).join('');
    }
    function toggleAllBacktests(checked) {
      document.querySelectorAll('.backtest-check:not(:disabled)').forEach(item => item.checked = checked);
    }
    function selectedBacktestIds() {
      return [...document.querySelectorAll('.backtest-check:checked')].map(item => Number(item.value));
    }
    async function confirmSelectedBacktests() {
      await confirmBacktests(selectedBacktestIds());
    }
    async function confirmBacktests(ids) {
      if (!ids.length) return;
      const res = await fetch('/api/backtests/confirm', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids})});
      const payload = await res.json();
      latestData.backtest_runs = payload.backtest_runs || latestData.backtest_runs;
      renderBacktests(latestData);
      renderHero(latestData);
    }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    function table(headers, rows, sortable=false) {
      const head = headers.map(h => Array.isArray(h) ? h : [null,h]).map(h => `<th ${sortable ? `onclick="sortRank('${h[0]}')"` : ''}>${h[1]}</th>`).join('');
      const body = rows.length ? rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('') : '<tr><td colspan="8" class="muted">暂无数据</td></tr>';
      return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }
    function sortRank(key) { if (!key) return; sortAsc = sortKey === key ? !sortAsc : false; sortKey = key; renderLeaderboard({profit_leaderboard: rankRows}); }
    bindTabs(); load(); setInterval(load, 30000);
  </script>
</body>
</html>
"""

def _send(handler: BaseHTTPRequestHandler, content_type: str, body: bytes, status: int = 200) -> None:
    try:
        headers = getattr(handler, "headers", {})
        accept_encoding = headers.get("Accept-Encoding", "") if hasattr(headers, "get") else ""
        if len(body) >= 1024 and "gzip" in accept_encoding.lower():
            body = gzip.compress(body, compresslevel=5)
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Encoding", "gzip")
            handler.send_header("Vary", "Accept-Encoding")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
        # Browsers, health checks, and reverse proxies may cancel a request
        # after receiving enough data; the server has no work left to do.
        return


def _send_error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    body = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
    _send(handler, "application/json; charset=utf-8", body, status)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        data = asdict(value)
        if "market_value" not in data and hasattr(value, "market_value"):
            data["market_value"] = value.market_value
        if "unrealized_pnl" not in data and hasattr(value, "unrealized_pnl"):
            data["unrealized_pnl"] = value.unrealized_pnl
        return _to_jsonable(data)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
