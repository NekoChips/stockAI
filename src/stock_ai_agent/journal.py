from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from .models import Decision, Fill, Portfolio


def _merge_unique(items: list, additions: list) -> list:
    merged = []
    for item in [*items, *additions]:
        if item not in merged:
            merged.append(item)
    return merged


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


def normalize_daily_report(report: dict) -> dict:
    """Normalize persisted report snapshots without mutating the stored object."""
    normalized = dict(report)
    normalized["decisions"] = deduplicate_decision_rows(report.get("decisions") or [])
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
