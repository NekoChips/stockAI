from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Tuple

from .models import Bar, Fill, Portfolio


@dataclass(frozen=True)
class PeriodReturn:
    period: str
    start_date: date
    end_date: date
    start_value: Decimal
    end_value: Decimal
    return_rate: Decimal


@dataclass(frozen=True)
class BenchmarkPoint:
    series: str
    day: date
    return_rate: Decimal


@dataclass(frozen=True)
class ProfitRankRow:
    symbol: str
    name: str
    profit_amount: Decimal
    holding_days: int
    return_rate: Decimal


@dataclass(frozen=True)
class ProfitCalendarCell:
    period: str
    start_date: date
    end_date: date
    pnl: Decimal
    return_rate: Decimal


Snapshot = Tuple[date, Decimal]


def compute_period_returns(snapshots: Iterable[Snapshot]) -> Dict[str, List[PeriodReturn]]:
    ordered = _ordered_snapshots(snapshots)
    return {
        "daily": _daily_returns(ordered),
        "weekly": _period_returns(ordered, lambda day: f"{day.isocalendar().year}-W{day.isocalendar().week:02d}"),
        "monthly": _period_returns(ordered, lambda day: f"{day.year:04d}-{day.month:02d}"),
        "yearly": _period_returns(ordered, lambda day: f"{day.year:04d}"),
    }


def build_benchmark_comparison(
    snapshots: Iterable[Snapshot],
    benchmarks: Dict[str, List[Bar]],
    benchmark_names: Dict[str, str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> List[BenchmarkPoint]:
    ordered = _ordered_snapshots(snapshots)
    if not ordered:
        return []
    points: List[BenchmarkPoint] = _normalize_series("AI-Agent", ordered)
    for symbol, bars in benchmarks.items():
        series = [
            (bar.timestamp.date(), bar.close_price)
            for bar in sorted(bars, key=lambda item: item.timestamp)
            if bar.close_price > 0
            and (start_date is None or bar.timestamp.date() >= start_date)
            and (end_date is None or bar.timestamp.date() <= end_date)
        ]
        points.extend(_normalize_series(benchmark_names.get(symbol, symbol), series))
    return points


def build_profit_leaderboard(
    portfolio: Portfolio,
    fills: Iterable[Fill],
    names: Dict[str, str],
    as_of: date | None = None,
) -> List[ProfitRankRow]:
    fills_by_symbol: Dict[str, List[Fill]] = {}
    for fill in fills:
        fills_by_symbol.setdefault(fill.symbol, []).append(fill)
    as_of = as_of or date.today()
    rows: List[ProfitRankRow] = []
    for symbol, position in portfolio.positions.items():
        cost_value = position.cost_value
        profit_amount = (position.realized_pnl + position.unrealized_pnl).quantize(Decimal("0.01"))
        first_fill = min((fill.timestamp.date() for fill in fills_by_symbol.get(symbol, [])), default=as_of)
        holding_days = max(1, (as_of - first_fill).days + 1) if position.quantity > 0 else 0
        return_rate = _safe_rate(profit_amount, cost_value)
        rows.append(
            ProfitRankRow(
                symbol=symbol,
                name=names.get(symbol, symbol),
                profit_amount=profit_amount,
                holding_days=holding_days,
                return_rate=return_rate,
            )
        )
    return sorted(rows, key=lambda item: item.profit_amount, reverse=True)


def build_profit_calendar(snapshots: Iterable[Snapshot]) -> Dict[str, List[ProfitCalendarCell]]:
    ordered = _ordered_snapshots(snapshots)
    return {
        "daily": _calendar_cells(ordered, lambda day: day.isoformat()),
        "monthly": _calendar_cells(ordered, lambda day: f"{day.year:04d}-{day.month:02d}"),
        "yearly": _calendar_cells(ordered, lambda day: f"{day.year:04d}"),
    }


def fill_daily_snapshots(
    snapshots: Iterable[Snapshot],
    start_date: date,
    end_date: date,
    default_value: Decimal,
) -> List[Snapshot]:
    ordered = _ordered_snapshots(snapshots)
    values = {day: value for day, value in ordered}
    carried = default_value
    for day, value in ordered:
        if day <= start_date:
            carried = value
        else:
            break
    result: List[Snapshot] = []
    current = start_date
    while current <= end_date:
        if current in values:
            carried = values[current]
        result.append((current, carried))
        current += timedelta(days=1)
    return result


def _period_returns(ordered: List[Snapshot], period_key) -> List[PeriodReturn]:
    grouped: Dict[str, List[Snapshot]] = {}
    for snapshot in ordered:
        grouped.setdefault(period_key(snapshot[0]), []).append(snapshot)
    results: List[PeriodReturn] = []
    for period, values in grouped.items():
        start_date, start_value = values[0]
        end_date, end_value = values[-1]
        results.append(
            PeriodReturn(
                period=period,
                start_date=start_date,
                end_date=end_date,
                start_value=start_value,
                end_value=end_value,
                return_rate=_safe_rate(end_value - start_value, start_value),
            )
        )
    return results


def _daily_returns(ordered: List[Snapshot]) -> List[PeriodReturn]:
    if not ordered:
        return []
    results = [
        PeriodReturn(
            period=ordered[0][0].isoformat(),
            start_date=ordered[0][0],
            end_date=ordered[0][0],
            start_value=ordered[0][1],
            end_value=ordered[0][1],
            return_rate=Decimal("0.000000"),
        )
    ]
    for previous, current in zip(ordered[:-1], ordered[1:]):
        results.append(
            PeriodReturn(
                period=current[0].isoformat(),
                start_date=previous[0],
                end_date=current[0],
                start_value=previous[1],
                end_value=current[1],
                return_rate=_safe_rate(current[1] - previous[1], previous[1]),
            )
        )
    return results


def _calendar_cells(ordered: List[Snapshot], period_key) -> List[ProfitCalendarCell]:
    if not ordered:
        return []
    grouped: Dict[str, List[Snapshot]] = {}
    for snapshot in ordered:
        grouped.setdefault(period_key(snapshot[0]), []).append(snapshot)
    previous_value = ordered[0][1]
    cells: List[ProfitCalendarCell] = []
    for period, values in grouped.items():
        start_date, start_value = values[0]
        end_date, end_value = values[-1]
        base = previous_value if period != ordered[0][0].isoformat() else start_value
        pnl = (end_value - base).quantize(Decimal("0.01"))
        cells.append(
            ProfitCalendarCell(
                period=period,
                start_date=start_date,
                end_date=end_date,
                pnl=pnl,
                return_rate=_safe_rate(pnl, base),
            )
        )
        previous_value = end_value
    return cells


def _normalize_series(name: str, values: List[Snapshot]) -> List[BenchmarkPoint]:
    if not values:
        return []
    base = values[0][1]
    if base <= 0:
        return []
    return [BenchmarkPoint(name, day, _safe_rate(value - base, base)) for day, value in values]


def _ordered_snapshots(snapshots: Iterable[Snapshot]) -> List[Snapshot]:
    return sorted([(day, Decimal(value)) for day, value in snapshots], key=lambda item: item[0])


def _safe_rate(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
