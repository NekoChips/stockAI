from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List

from .models import Bar


@dataclass(frozen=True)
class BacktestResult:
    total_return: Decimal
    max_drawdown: Decimal
    win_rate: Decimal
    profit_loss_ratio: Decimal
    turnover: Decimal
    max_consecutive_losses: int
    strategy_contributions: Dict[str, Decimal]


@dataclass(frozen=True)
class OptimizedStrategyCandidate:
    strategy_id: str
    parameters: Dict[str, object]
    metrics: BacktestResult
    status: str = "待人工确认"


@dataclass(frozen=True)
class OptimizationResult:
    best: OptimizedStrategyCandidate
    candidates: List[OptimizedStrategyCandidate]


def run_simple_backtest(prices: Iterable[Decimal], strategy_returns: Dict[str, Iterable[Decimal]] | None = None) -> BacktestResult:
    price_list = list(prices)
    if len(price_list) < 2:
        raise ValueError("回放至少需要两个价格点")

    returns: List[Decimal] = []
    equity = Decimal("1")
    peak = Decimal("1")
    max_drawdown = Decimal("0")
    wins = 0
    losses = 0
    gross_profit = Decimal("0")
    gross_loss = Decimal("0")
    max_consecutive_losses = 0
    current_losses = 0

    for previous, current in zip(price_list[:-1], price_list[1:]):
        day_return = current / previous - Decimal("1")
        returns.append(day_return)
        equity *= Decimal("1") + day_return
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, Decimal("1") - equity / peak)
        if day_return > 0:
            wins += 1
            gross_profit += day_return
            current_losses = 0
        elif day_return < 0:
            losses += 1
            gross_loss += abs(day_return)
            current_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, current_losses)

    total = len(returns)
    win_rate = Decimal(wins) / Decimal(total) if total else Decimal("0")
    profit_loss_ratio = gross_profit / gross_loss if gross_loss else Decimal("0")
    contributions = {
        name: sum((Decimal(str(item)) for item in values), Decimal("0"))
        for name, values in (strategy_returns or {}).items()
    }
    turnover = Decimal(len([item for item in returns if item != 0])) / Decimal(total)
    return BacktestResult(
        total_return=equity - Decimal("1"),
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        turnover=turnover,
        max_consecutive_losses=max_consecutive_losses,
        strategy_contributions=contributions,
    )


def optimize_strategy_parameters(
    bars_by_symbol: Dict[str, List[Bar]],
    lookback_days: Iterable[int] = (5, 10, 20),
    thresholds: Iterable[Decimal] = (Decimal("0.01"), Decimal("0.02"), Decimal("0.04")),
    target_weights: Iterable[Decimal] = (Decimal("0.20"), Decimal("0.40"), Decimal("0.60")),
    fee_rate: Decimal = Decimal("0.0003"),
    slippage_rate: Decimal = Decimal("0.0005"),
) -> OptimizationResult:
    candidates: List[OptimizedStrategyCandidate] = []
    for lookback in lookback_days:
        for threshold in thresholds:
            for target_weight in target_weights:
                returns = _simulate_momentum_portfolio(
                    bars_by_symbol,
                    int(lookback),
                    Decimal(threshold),
                    Decimal(target_weight),
                    fee_rate,
                    slippage_rate,
                )
                metrics = run_simple_backtest(_equity_prices(returns), {"momentum_grid": returns})
                candidates.append(
                    OptimizedStrategyCandidate(
                        strategy_id="momentum_grid",
                        parameters={
                            "lookback_days": int(lookback),
                            "threshold": str(threshold),
                            "target_weight": str(target_weight),
                        },
                        metrics=metrics,
                    )
                )
    if not candidates:
        raise ValueError("至少需要一个回测参数组合")
    best = sorted(candidates, key=lambda item: (item.metrics.total_return - item.metrics.max_drawdown, item.metrics.win_rate), reverse=True)[0]
    return OptimizationResult(best=best, candidates=candidates)


def _simulate_momentum_portfolio(
    bars_by_symbol: Dict[str, List[Bar]],
    lookback: int,
    threshold: Decimal,
    target_weight: Decimal,
    fee_rate: Decimal,
    slippage_rate: Decimal,
) -> List[Decimal]:
    series = [sorted(bars, key=lambda item: item.timestamp) for bars in bars_by_symbol.values() if len(bars) > lookback + 1]
    if not series:
        return [Decimal("0")]
    horizon = min(len(bars) for bars in series)
    returns: List[Decimal] = []
    previous_weights = [Decimal("0") for _ in series]
    for index in range(lookback, horizon - 1):
        raw_weights: List[Decimal] = []
        for bars in series:
            momentum = bars[index].close_price / bars[index - lookback].close_price - Decimal("1")
            raw_weights.append(target_weight if momentum > threshold else Decimal("0"))
        total_weight = sum(raw_weights, Decimal("0"))
        weights = [weight / total_weight * target_weight if total_weight > target_weight and total_weight > 0 else weight for weight in raw_weights]
        day_return = Decimal("0")
        turnover_cost = Decimal("0")
        for offset, bars in enumerate(series):
            asset_return = bars[index + 1].close_price / bars[index].close_price - Decimal("1")
            day_return += weights[offset] * asset_return
            turnover_cost += abs(weights[offset] - previous_weights[offset]) * (fee_rate + slippage_rate)
        previous_weights = weights
        returns.append(day_return - turnover_cost)
    return returns or [Decimal("0")]


def _equity_prices(returns: Iterable[Decimal]) -> List[Decimal]:
    equity = Decimal("1")
    prices = [equity]
    for item in returns:
        equity *= Decimal("1") + item
        prices.append(equity)
    return prices
