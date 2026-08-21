from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from .models import Direction, FeatureSet, StrategySignal


@dataclass(frozen=True)
class QuantContext:
    histories: Dict[str, List[Decimal]]
    current_weights: Dict[str, Decimal]
    peak_values: Dict[str, Decimal] | None = None
    current_values: Dict[str, Decimal] | None = None

    def current_weight(self, symbol: str) -> Decimal:
        return self.current_weights.get(symbol, Decimal("0"))


def _return(history: List[Decimal], lookback: int) -> Decimal | None:
    if lookback <= 0 or len(history) <= lookback or history[-lookback - 1] == 0:
        return None
    return history[-1] / history[-lookback - 1] - Decimal("1")


class TimeSeriesMomentumStrategy:
    strategy_id = "time_series_momentum"

    def __init__(self, lookback_days: int = 20) -> None:
        self.lookback_days = lookback_days

    def evaluate(self, symbol: str, features: FeatureSet, context: QuantContext) -> StrategySignal:
        history = context.histories.get(symbol, [])
        value = _return(history, self.lookback_days)
        if value is None:
            return _watch(self.strategy_id, symbol, "时间序列动量历史数据不足。")
        if value > Decimal("0.03") and features.values.get("atr_ratio", Decimal("1")) <= Decimal("0.04"):
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal("2"), Decimal("0.40"), [f"{self.lookback_days} 日收益为 {value:.2%}，自身动量为正。"])
        if value < Decimal("-0.02"):
            return _signal(self.strategy_id, symbol, Direction.REDUCE, Decimal("-2"), Decimal("0"), [], [f"{self.lookback_days} 日收益为 {value:.2%}，自身动量转弱。"])
        return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), context.current_weight(symbol), [f"{self.lookback_days} 日动量不极端，维持观察。"])


class MeanReversionStrategy:
    strategy_id = "mean_reversion"

    def __init__(self, z_threshold: Decimal = Decimal("-1.2")) -> None:
        self.z_threshold = z_threshold

    def evaluate(self, symbol: str, features: FeatureSet, context: QuantContext) -> StrategySignal:
        z_score = features.values.get("bollinger_z")
        close = features.values.get("close")
        middle = features.values.get("bollinger_middle", features.values.get("sma20"))
        if z_score is None or close is None or middle is None:
            return _watch(self.strategy_id, symbol, "均值回归所需布林带或均线数据不足。")
        if z_score <= self.z_threshold and close >= middle * Decimal("0.96"):
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal("1.5"), Decimal("0.20"), [f"布林 z-score 为 {z_score:.2f}，短期偏离较大但趋势未明显破坏。"])
        if z_score >= Decimal("1.8"):
            return _signal(self.strategy_id, symbol, Direction.REDUCE, Decimal("-1.5"), Decimal("0.20"), [], [f"布林 z-score 为 {z_score:.2f}，短线偏热。"])
        return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), context.current_weight(symbol), ["均值回归信号不明显。"])


class RelativeStrengthRotationStrategy:
    strategy_id = "relative_strength"

    def __init__(self, lookback_days: int = 20) -> None:
        self.lookback_days = lookback_days

    def evaluate(self, symbol: str, features: FeatureSet, context: QuantContext) -> StrategySignal:
        own_return = _return(context.histories.get(symbol, []), self.lookback_days)
        peer_returns = {
            peer: value
            for peer, history in context.histories.items()
            if peer != symbol
            for value in [_return(history, self.lookback_days)]
            if value is not None
        }
        if own_return is None or not peer_returns:
            return _watch(self.strategy_id, symbol, "相对强弱轮动需要至少两个标的的历史数据。")
        best_peer_return = max(peer_returns.values())
        if own_return > best_peer_return + Decimal("0.01"):
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal("2"), Decimal("0.40"), [f"{symbol} 近端收益强于对照 ETF，适合提高配置。"])
        if own_return < best_peer_return - Decimal("0.01"):
            return _signal(self.strategy_id, symbol, Direction.REDUCE, Decimal("-1.5"), Decimal("0.10"), [], [f"{symbol} 近端收益弱于对照 ETF，轮动得分下降。"])
        return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), context.current_weight(symbol), ["两个 ETF 相对强弱差异不大。"])


class VolatilityTargetStrategy:
    strategy_id = "volatility_target"

    def __init__(self, high_atr_ratio: Decimal = Decimal("0.04")) -> None:
        self.high_atr_ratio = high_atr_ratio

    def evaluate(self, symbol: str, features: FeatureSet, context: QuantContext) -> StrategySignal:
        atr_ratio = features.values.get("atr_ratio")
        if atr_ratio is None:
            return _watch(self.strategy_id, symbol, "波动率目标仓位缺少 ATR 数据。")
        if atr_ratio > self.high_atr_ratio:
            return _signal(self.strategy_id, symbol, Direction.REDUCE, Decimal("-2"), Decimal("0.20"), [], [f"ATR 占价格比例为 {atr_ratio:.2%}，波动偏高，降低目标仓位。"])
        return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0.5"), Decimal("0.60"), [f"ATR 占价格比例为 {atr_ratio:.2%}，波动可接受。"])


class DrawdownControlStrategy:
    strategy_id = "drawdown_control"

    def __init__(self, stop: Decimal = Decimal("0.08")) -> None:
        self.stop = stop

    def evaluate(self, symbol: str, features: FeatureSet, context: QuantContext) -> StrategySignal:
        peaks = context.peak_values or {}
        currents = context.current_values or {}
        peak = peaks.get(symbol)
        current = currents.get(symbol)
        if peak is None or current is None or peak <= 0:
            return _watch(self.strategy_id, symbol, "回撤控制缺少峰值或当前净值数据。")
        drawdown = Decimal("1") - current / peak
        if drawdown >= self.stop:
            return _signal(self.strategy_id, symbol, Direction.EXIT, Decimal("-3"), Decimal("0"), [], [f"策略回撤达到 {drawdown:.2%}，触发止损。"])
        # A non-triggered stop is informational only.  It must not be interpreted
        # as a target-position cap by the aggregator, otherwise an empty account
        # can never open its first position.
        return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0.5"), Decimal("1"), [f"策略回撤 {drawdown:.2%}，未触发止损。"])


def _watch(strategy_id: str, symbol: str, reason: str) -> StrategySignal:
    return StrategySignal(strategy_id, symbol, Direction.WATCH, Decimal("0"), Decimal("0"), Decimal("0"), [], [reason], reason)


def _signal(
    strategy_id: str,
    symbol: str,
    direction: Direction,
    score: Decimal,
    target_weight: Decimal,
    evidence: List[str],
    objections: List[str] | None = None,
) -> StrategySignal:
    objections = objections or []
    explanation = evidence[0] if evidence else objections[0] if objections else "量化策略保持观察。"
    return StrategySignal(
        strategy_id=strategy_id,
        symbol=symbol,
        direction=direction,
        score=score,
        confidence=max(Decimal("0"), min(Decimal("1"), abs(score) / Decimal("3"))),
        target_weight=target_weight,
        evidence=evidence,
        objections=objections,
        explanation=explanation,
        version="v1",
    )
