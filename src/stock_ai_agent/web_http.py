"""HTTP transport and route dispatch for the dashboard."""

from __future__ import annotations

import base64
import hmac
import json
import logging
import re
from binascii import Error as Base64Error
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .config import AppConfig
from .instrument_detail import build_instrument_detail_payload
from .web_actions import (
    add_dashboard_watchlist_item,
    confirm_backtest_runs,
    confirm_dashboard_strategy_profile,
    remove_dashboard_watchlist_item,
    save_dashboard_strategy_profile,
    search_watchlist_instruments,
)
from .web_assets import render_dashboard_html
from .web_dashboard import (
    build_dashboard_backtests_payload,
    build_dashboard_calendar_payload,
    build_dashboard_overview_payload,
    build_dashboard_payload,
    build_dashboard_performance_payload,
    build_dashboard_report_payload,
    build_dashboard_reports_payload,
    build_dashboard_strategies_payload,
    _query_date,
)
from .web_health import build_ready_payload
from .web_support import MAX_BODY_SIZE, _send, _send_error, _to_jsonable


logger = logging.getLogger(__name__)
PLACEHOLDER_PATTERN = re.compile(r"^\$\{[A-Z0-9_]+\}$")


class BoundedThreadingHTTPServer(HTTPServer):
    """HTTP server with a bounded worker pool so clients cannot exhaust threads."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args, max_workers: int = 16, **kwargs):
        super().__init__(*args, **kwargs)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="stockai-web")

    def process_request(self, request, client_address) -> None:
        self._executor.submit(self._handle_request, request, client_address)

    def _handle_request(self, request, client_address) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self) -> None:
        super().server_close()
        self._executor.shutdown(wait=True)


def serve_dashboard(config: AppConfig, store, host: str = "127.0.0.1", port: int = 8765) -> BoundedThreadingHTTPServer:
    class DashboardHandler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            if not config.web.require_basic_auth:
                return True
            expected_username = config.web.username
            expected_password = config.web.password
            if (
                not expected_username
                or not expected_password
                or PLACEHOLDER_PATTERN.fullmatch(expected_username)
                or PLACEHOLDER_PATTERN.fullmatch(expected_password)
            ):
                return False
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                username, password = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)
            except (Base64Error, ValueError, UnicodeDecodeError):
                return False
            username_match = hmac.compare_digest(username, expected_username)
            password_match = hmac.compare_digest(password, expected_password)
            return username_match and password_match

        def _read_json_body(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self.send_error(400, "Invalid Content-Length")
                return None
            if length < 0 or length > MAX_BODY_SIZE:
                self.send_error(413, "Request Entity Too Large")
                return None
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                value = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400, "Invalid JSON")
                return None
            if not isinstance(value, dict):
                self.send_error(400, "JSON body must be an object")
                return None
            return value

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
            if request.path == "/readyz":
                status, payload = build_ready_payload(config, store)
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"), status)
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
                    logger.warning("盈亏分析参数无效：%s", exc)
                    _send_error(self, 400, "请求参数无效。")
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
            if request.path == "/api/dashboard/strategies":
                payload = build_dashboard_strategies_payload(config, store)
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            instrument_prefix = "/api/instruments/"
            if request.path.startswith(instrument_prefix) and request.path.endswith("/detail"):
                symbol = unquote(request.path[len(instrument_prefix):-len("/detail")]).rstrip("/")
                try:
                    payload = _to_jsonable(build_instrument_detail_payload(config, store, symbol))
                except ValueError as exc:
                    logger.warning("标的详情参数无效：%s", exc)
                    _send_error(self, 400, "请求参数无效。")
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
                    logger.warning("Dashboard 参数无效：%s", exc)
                    _send_error(self, 400, "请求参数无效。")
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
                data = self._read_json_body()
                if data is None:
                    return
                try:
                    ids = [int(item) for item in data.get("ids", [])]
                except (TypeError, ValueError):
                    self.send_error(400, "Bad Request")
                    return
                payload = json.dumps(confirm_backtest_runs(config, store, ids), ensure_ascii=False).encode("utf-8")
                _send(self, "application/json; charset=utf-8", payload)
                return
            if request.path == "/api/strategies/profiles":
                data = self._read_json_body()
                if data is None:
                    return
                try:
                    payload = save_dashboard_strategy_profile(config, store, data)
                except (TypeError, ValueError) as exc:
                    _send_error(self, 400, str(exc))
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            strategy_confirm_prefix = "/api/strategies/profiles/"
            if request.path.startswith(strategy_confirm_prefix) and request.path.endswith("/confirm"):
                profile_id = unquote(request.path[len(strategy_confirm_prefix):-len("/confirm")]).strip("/")
                try:
                    payload = confirm_dashboard_strategy_profile(config, store, profile_id)
                except (TypeError, ValueError) as exc:
                    _send_error(self, 400, str(exc))
                    return
                _send(self, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                return
            if request.path == "/api/watchlist":
                data = self._read_json_body()
                if data is None:
                    return
                try:
                    payload = add_dashboard_watchlist_item(config, store, data)
                except (TypeError, ValueError) as exc:
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

    server = BoundedThreadingHTTPServer((host, port), DashboardHandler)
    server.serve_forever()
    return server

