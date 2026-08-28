from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Iterable

from .models import Decision, Fill, PaperOrder, Portfolio

MAX_DECISION_REASON_ITEMS = 20
NEUTRAL_DIRECTIONS = {"持有", "观望"}


def _merge_unique(items: list, additions: list) -> list:
    merged = []
    for item in [*items, *additions]:
        if item not in merged:
            merged.append(item)
    return merged[-MAX_DECISION_REASON_ITEMS:]


def persisted_decision_event_state(
    direction: object,
    target_weight: object,
    approved: object,
    strategy_id: object,
) -> tuple[str, str, bool, str]:
    """Normalize a decision to the state that should create a business event.

    Repeated approved neutral evaluations are not business transitions. Their
    calculated target weight and participating strategy can vary slightly from
    round to round, but the observable state remains "held" or "watching".
    """
    direction_value = getattr(direction, "value", direction)
    direction_value = str(direction_value or "")
    approved_value = bool(approved)
    if approved_value and direction_value in NEUTRAL_DIRECTIONS:
        return direction_value, "neutral", True, ""
    return direction_value, str(target_weight), approved_value, str(strategy_id or "")


def decision_event_state(decision: Decision) -> tuple[str, str, bool, str]:
    """Return the normalized business state that should create a new event."""
    signal = decision.source_signal
    return persisted_decision_event_state(
        decision.direction,
        decision.target_weight,
        decision.approved,
        signal.strategy_id if signal else "",
    )


def order_event_state(order: PaperOrder) -> tuple[str, str, int]:
    """Return the order state that should create a new execution event."""
    return (order.direction.value, order.status.value, int(order.filled_quantity))


def decision_position_context(portfolio: Portfolio | None, symbol: str) -> tuple[int, Decimal, str]:
    """Return compact position context for a persisted business decision."""
    if portfolio is None:
        return 0, Decimal("0"), "unknown"
    position = portfolio.positions.get(symbol)
    quantity = int(position.quantity) if position and position.quantity > 0 else 0
    weight = portfolio.position_weight(symbol) if quantity else Decimal("0")
    return quantity, weight, "held" if quantity else "empty"


def make_business_event_key(
    phase: str,
    trade_date: date | str,
    symbol: str,
    state: tuple,
    previous_event_id: int | str | None = None,
) -> str:
    """Create an idempotency key while allowing a state to recur after a transition."""
    day = trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    raw = "|".join(
        [phase, day, symbol, str(previous_event_id or "initial"), *(str(item) for item in state)]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def deduplicate_decision_rows(rows: Iterable[dict]) -> list[dict]:
    """Keep one final decision row per symbol while preserving all evidence."""
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for index, row in enumerate(rows):
        current = dict(row)
        symbol = str(current.get("symbol") or "")
        key = symbol or f"__row_{index}"
        previous = grouped.get(key)
        if previous is not None:
            for field in ("risk_reasons", "evidence", "objections"):
                previous[field] = _merge_unique(
                    list(previous.get(field) or []),
                    list(current.get(field) or []),
                )
        else:
            current["risk_reasons"] = list(current.get("risk_reasons") or [])
            current["evidence"] = list(current.get("evidence") or [])
            current["objections"] = list(current.get("objections") or [])
            grouped[key] = current
            order.append(key)
            continue
        current["risk_reasons"] = previous["risk_reasons"]
        current["evidence"] = previous["evidence"]
        current["objections"] = previous["objections"]
        grouped[key] = current
    return [grouped[key] for key in order]


def _timeline_state(row: dict) -> tuple:
    phase = str(row.get("phase") or "")
    if phase == "order":
        return (
            phase,
            str(row.get("order_id") or ""),
            str(row.get("direction") or ""),
            str(row.get("status") or ""),
            int(row.get("filled_quantity") or 0),
        )
    return (
        phase,
        str(row.get("symbol") or ""),
        *persisted_decision_event_state(
            row.get("direction"),
            row.get("target_weight"),
            row.get("approved") if row.get("approved") is not None else False,
            row.get("strategy_id"),
        ),
    )


def deduplicate_decision_timeline(rows: Iterable[dict]) -> list[dict]:
    """Collapse consecutive repeats while preserving meaningful state changes."""
    result: list[dict] = []
    last_by_stream: dict[tuple, tuple] = {}
    index_by_stream: dict[tuple, int] = {}
    for row in rows:
        current = dict(row)
        stream = (
            str(current.get("trade_date") or ""),
            str(current.get("phase") or ""),
            str(current.get("order_id") or current.get("symbol") or ""),
        )
        state = _timeline_state(current)
        if last_by_stream.get(stream) == state:
            result[index_by_stream[stream]] = current
            continue
        last_by_stream[stream] = state
        index_by_stream[stream] = len(result)
        result.append(current)
    return result


def normalize_daily_report(report: dict) -> dict:
    """Normalize persisted report snapshots without mutating the stored object."""
    normalized = dict(report)
    normalized["decisions"] = deduplicate_decision_rows(report.get("decisions") or [])
    normalized["decision_timeline"] = deduplicate_decision_timeline(report.get("decision_timeline") or [])
    return normalized


def build_daily_report(
    report_date: date,
    portfolio: Portfolio,
    decisions: Iterable[Decision],
    fills: Iterable[Fill],
    previous_total_asset: Decimal | None = None,
    status: str = "已归档",
    system_notes: Iterable[str] = (),
) -> dict:
    """Build a database-ready, provider-neutral daily paper-trading report."""
    decisions = list(decisions)
    fills = list(fills)
    total_asset = portfolio.total_asset()
    previous_asset = previous_total_asset if previous_total_asset is not None else total_asset
    daily_pnl = (total_asset - previous_asset).quantize(Decimal("0.01"))
    daily_return = daily_pnl / previous_asset if previous_asset else Decimal("0")
    total_market_value = portfolio.total_market_value()
    position_ratio = total_market_value / total_asset if total_asset else Decimal("0")

    position_rows = [
        {
            "symbol": position.symbol,
            "quantity": position.quantity,
            "available_quantity": position.available_quantity,
            "average_cost": str(position.average_cost),
            "last_price": str(position.last_price),
            "market_value": str(position.market_value),
            "position_weight": str(portfolio.position_weight(position.symbol)),
            "realized_pnl": str(position.realized_pnl),
            "unrealized_pnl": str(position.unrealized_pnl),
        }
        for position in sorted(portfolio.positions.values(), key=lambda item: item.symbol)
    ]
    fill_rows = [
        {
            "symbol": fill.symbol,
            "direction": fill.direction.value,
            "quantity": fill.quantity,
            "price": str(fill.price),
            "fee": str(fill.fee),
            "slippage": str(fill.slippage),
            "gross_amount": str(fill.gross_amount),
            "timestamp": fill.timestamp.isoformat(),
        }
        for fill in fills
    ]
    decision_rows = []
    for decision in decisions:
        signal = decision.source_signal
        decision_rows.append(
            {
                "symbol": decision.symbol,
                "direction": decision.direction.value,
                "target_weight": str(decision.target_weight),
                "approved": decision.approved,
                "risk_reasons": list(decision.reasons),
                "strategy_id": signal.strategy_id if signal else "",
                "score": str(signal.score) if signal else "0",
                "confidence": str(signal.confidence) if signal else "0",
                "explanation": signal.explanation if signal else "",
                "evidence": list(signal.evidence) if signal else [],
                "objections": list(signal.objections) if signal else [],
                "version": signal.version if signal else "",
            }
        )

    return normalize_daily_report({
        "report_date": report_date.isoformat(),
        "status": status,
        "summary": _build_summary(position_rows, fill_rows, decision_rows),
        "system_notes": list(system_notes),
        "account": {
            "cash": str(portfolio.cash),
            "total_asset": str(total_asset),
            "total_market_value": str(total_market_value),
            "position_ratio": str(position_ratio),
            "daily_pnl": str(daily_pnl),
            "daily_return": str(daily_return),
            "previous_total_asset": str(previous_asset),
        },
        "positions": position_rows,
        "fills": fill_rows,
        "decisions": decision_rows,
    })


def _build_summary(positions: list[dict], fills: list[dict], decisions: list[dict]) -> str:
    if not fills:
        action = "今日没有模拟成交"
    else:
        directions = "、".join(dict.fromkeys(str(item["direction"]) for item in fills))
        action = f"今日完成 {len(fills)} 笔模拟成交，包含{directions}操作"
    position_text = f"收盘持有 {len(positions)} 只证券" if positions else "收盘保持空仓"
    decision_text = f"策略形成 {len(decisions)} 条决策记录" if decisions else "策略未形成可执行决策"
    return f"{action}；{position_text}；{decision_text}。"
