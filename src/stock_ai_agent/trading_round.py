from __future__ import annotations

from datetime import date
from typing import Any

from .models import Fill, PaperOrder, Quote
from .paper_broker import PaperBroker, PaperBrokerError


def execute_order_state_machine(
    broker: PaperBroker,
    order: PaperOrder,
    quote: Quote,
    *,
    store: Any | None = None,
    trade_date: date | None = None,
) -> Fill:
    """Run the canonical paper-order lifecycle used by every execution path."""
    order = broker.create(order)
    _save_order(store, order, trade_date)
    order = broker.approve(order)
    _save_order(store, order, trade_date)
    order = broker.submit(order)
    _save_order(store, order, trade_date)
    attempt = broker.try_fill(order, quote)
    _save_order(store, attempt.order, trade_date)
    if attempt.fill is None:
        raise PaperBrokerError(attempt.order.rejected_reason or "订单尚未成交。")
    return attempt.fill


def _save_order(store: Any | None, order: PaperOrder, trade_date: date | None) -> None:
    if store is not None and hasattr(store, "save_order"):
        store.save_order(order, trade_date)
