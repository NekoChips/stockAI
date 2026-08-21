"""Shared Web response, serialization, and cache helpers."""

from __future__ import annotations

import gzip
import json
import time
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from threading import Lock
from typing import Any


MAX_BODY_SIZE = 10 * 1024 * 1024


class TTLCache:
    def __init__(self, ttl_seconds: float = 45.0, max_entries: int = 64) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._entries: dict[tuple, tuple[float, Any]] = {}
        self._lock = Lock()

    def get_or_compute(self, key: tuple, compute) -> Any:
        now = time.monotonic()
        with self._lock:
            cached = self._entries.get(key)
            if cached and now - cached[0] < self.ttl_seconds:
                return cached[1]
        value = compute()
        with self._lock:
            self._entries[key] = (time.monotonic(), value)
            while len(self._entries) > self.max_entries:
                oldest = min(self._entries, key=lambda item: self._entries[item][0])
                del self._entries[oldest]
        return value

    def invalidate_store(self, store_id: int) -> None:
        with self._lock:
            for key in list(self._entries):
                if key and key[0] == store_id:
                    del self._entries[key]


_DASHBOARD_CACHE = TTLCache(ttl_seconds=45)


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

