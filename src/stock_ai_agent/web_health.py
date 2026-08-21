"""Health and readiness checks for the Web service."""

from __future__ import annotations

import logging
from typing import Any

from .config import AppConfig


logger = logging.getLogger(__name__)


def build_ready_payload(config: AppConfig, store) -> tuple[int, dict[str, Any]]:
    checks: dict[str, Any] = {}
    try:
        store.ping()
        checks["database"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - readiness must report dependency failures
        logger.warning("数据库就绪检查失败：%s", exc)
        checks["database"] = {"status": "failed"}

    try:
        age = store.last_quote_age_seconds()
        max_age = max(600, config.monitor.poll_seconds * 3)
        checks["market_data"] = {
            "status": "ok" if age is not None and age <= max_age else "stale",
            "age_seconds": age,
            "max_age_seconds": max_age,
        }
    except Exception as exc:  # noqa: BLE001 - readiness must report dependency failures
        logger.warning("行情就绪检查失败：%s", exc)
        checks["market_data"] = {"status": "failed"}

    ready = all(item["status"] == "ok" for item in checks.values())
    return (200 if ready else 503), {"status": "ready" if ready else "not_ready", "checks": checks}

