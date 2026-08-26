from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List

from .models import Direction, FeatureSet, StrategyDataStatus, StrategySignal


@dataclass(frozen=True)
class StrategyContext:
    current_weights: Dict[str, Decimal]

    def current_weight(self, symbol: str) -> Decimal:
        return self.current_weights.get(symbol, Decimal("0"))


class TechnicalCompositeStrategy:
    strategy_id = "technical_composite"
    version = "v1"

    def __init__(self, options: Dict[str, object] | None = None) -> None:
        options = options or {}
        self.bullish_score = Decimal(str(options.get("bullish_score", "2")))
        self.bearish_score = Decimal(str(options.get("bearish_score", "-2")))
        self.macd_score = Decimal(str(options.get("macd_score", "1.5")))
        self.rsi_overbought = Decimal(str(options.get("rsi_overbought", "75")))
        self.rsi_healthy_low = Decimal(str(options.get("rsi_healthy_low", "45")))
        self.rsi_healthy_high = Decimal(str(options.get("rsi_healthy_high", "70")))
        self.rsi_oversold = Decimal(str(options.get("rsi_oversold", "35")))
        self.bollinger_high = Decimal(str(options.get("bollinger_high", "2")))
        self.bollinger_low = Decimal(str(options.get("bollinger_low", "-1.2")))
        self.atr_high = Decimal(str(options.get("atr_high", "0.04")))
        self.volume_confirm = Decimal(str(options.get("volume_confirm", "1")))

    def evaluate(self, features: FeatureSet, context: StrategyContext | None = None) -> StrategySignal:
        context = context or StrategyContext({})
        current_weight = context.current_weight(features.symbol)
        if not features.is_complete:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=features.symbol,
                direction=Direction.WATCH,
                score=Decimal("0"),
                confidence=Decimal("0"),
                target_weight=current_weight,
                evidence=[],
                objections=features.missing_reasons,
                explanation="技术指标数据不足，暂不产生交易信号。",
                version=self.version,
            )

        values = features.values
        score = Decimal("0")
        evidence: List[str] = []
        objections: List[str] = []

        close = values.get("close", Decimal("0"))
        sma20 = values.get("sma20", close)
        ema12 = values.get("ema12", close)
        ema26 = values.get("ema26", close)
        macd = values.get("macd", Decimal("0"))
        macd_histogram = values.get("macd_histogram", Decimal("0"))
        rsi_value = values.get("rsi14", Decimal("50"))
        bollinger_z = values.get("bollinger_z", Decimal("0"))
        atr_ratio = values.get("atr_ratio", Decimal("1"))
        volume_ratio = values.get("volume_ratio", Decimal("0"))
        if close > sma20 and ema12 > ema26:
            score += self.bullish_score
            evidence.append("趋势向上：价格位于中期均线上方，EMA12 高于 EMA26。")
        else:
            score += self.bearish_score
            objections.append("趋势偏弱：价格或均线结构未确认。")

        if macd > 0 and macd_histogram >= 0:
            score += self.macd_score
            evidence.append("动能改善：MACD 位于正区间且柱体未走弱。")
        elif macd_histogram < 0:
            score -= Decimal("1")
            objections.append("动能减弱：MACD 柱体收缩。")

        if self.rsi_healthy_low <= rsi_value <= self.rsi_healthy_high:
            score += Decimal("1")
            evidence.append("RSI 处于健康区间，未明显超买。")
        elif rsi_value > self.rsi_overbought:
            score -= Decimal("1.5")
            objections.append("RSI 偏热，追高风险上升。")
        elif rsi_value < self.rsi_oversold:
            score += Decimal("0.5")
            evidence.append("RSI 偏低，存在短线修复可能。")

        if bollinger_z > self.bollinger_high:
            score -= Decimal("1")
            objections.append("价格触及布林带上沿附近，短线过热。")
        elif bollinger_z < self.bollinger_low:
            score += Decimal("0.5")
            evidence.append("价格低于布林中轨较多，具备均值回归观察价值。")

        if atr_ratio > self.atr_high:
            score -= Decimal("2")
            objections.append("ATR 波动率过高，仓位需要下调。")
        else:
            score += Decimal("0.5")
            evidence.append("ATR 波动率处于可接受范围。")

        if volume_ratio >= self.volume_confirm:
            score += Decimal("1")
            evidence.append("成交量高于均值，信号获得量能确认。")
        else:
            objections.append("成交量未放大，信号确认度一般。")

        target_weight = self._target_weight(score)
        direction = self._direction(current_weight, target_weight, score, values)
        if direction == Direction.HOLD:
            explanation = "多指标评分不足以改变当前仓位，选择持有。"
        elif direction == Direction.WATCH:
            explanation = "多指标信号偏弱，保持观望。"
        else:
            explanation = f"多指标综合评分为 {score}，建议{direction.value}至目标仓位 {target_weight:.0%}。"

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=features.symbol,
            direction=direction,
            score=score,
            confidence=max(Decimal("0"), min(Decimal("1"), (score + Decimal("3")) / Decimal("8"))),
            target_weight=target_weight,
            evidence=evidence,
            objections=objections,
            explanation=explanation,
            version=self.version,
        )

    def _target_weight(self, score: Decimal) -> Decimal:
        if score >= Decimal("5"):
            return Decimal("0.60")
        if score >= Decimal("3"):
            return Decimal("0.40")
        if score >= Decimal("1"):
            return Decimal("0.20")
        return Decimal("0")

    def _direction(self, current_weight: Decimal, target_weight: Decimal, score: Decimal, values: Dict[str, Decimal]) -> Direction:
        if values.get("close", Decimal("0")) < values.get("sma20", Decimal("0")) and values.get("macd_histogram", Decimal("0")) < 0:
            return Direction.EXIT if current_weight > 0 else Direction.WATCH
        if values.get("rsi14", Decimal("50")) > Decimal("75") or (values.get("bollinger_z", Decimal("0")) > Decimal("2") and values.get("macd_histogram", Decimal("0")) < 0):
            return Direction.REDUCE if current_weight > 0 else Direction.WATCH
        if target_weight == 0:
            return Direction.HOLD if current_weight > 0 else Direction.WATCH
        if current_weight == 0:
            return Direction.BUY
        if target_weight > current_weight:
            return Direction.ADD
        if target_weight < current_weight:
            return Direction.REDUCE
        return Direction.HOLD


def aggregate_signals(
    signals: Iterable[StrategySignal],
    weights: Dict[str, Decimal] | None = None,
    aggregator: Dict[str, object] | None = None,
) -> StrategySignal:
    signal_list = list(signals)
    if not signal_list:
        raise ValueError("缺少策略信号，无法聚合")
    weights = weights or {}
    legacy_aggregation = aggregator is None
    aggregator = aggregator or {}
    buy_threshold = Decimal(str(aggregator.get("buy_score_threshold", "1.5" if legacy_aggregation else "0.60")))
    exit_threshold = Decimal(str(aggregator.get("exit_score_threshold", "-1.5" if legacy_aggregation else "-0.60")))
    conflict_max_weight = Decimal(str(aggregator.get("conflict_max_weight", "0.20")))
    confidence_divisor = Decimal(str(aggregator.get("confidence_divisor", "5")))
    score_scale = Decimal(str(aggregator.get("score_normalization_divisor", "3")))
    symbol = signal_list[0].symbol
    total_weight = Decimal("0")
    weighted_score = Decimal("0")
    target_weight = Decimal("0")
    risk_caps: List[Decimal] = []
    evidence: List[str] = []
    objections: List[str] = []
    positive = 0
    negative = 0
    effective_weight = Decimal("0")
    participating: List[str] = []
    excluded: List[str] = []
    configured_weights: Dict[str, Decimal] = {}
    for signal in signal_list:
        weight = Decimal(str(Decimal("1") if not weights else weights.get(signal.strategy_id, Decimal("0"))))
        if weight <= 0:
            continue
        configured_weights[signal.strategy_id] = weight
        if signal.data_status in {StrategyDataStatus.UNAVAILABLE, StrategyDataStatus.INVALID}:
            excluded.append(signal.strategy_id)
            objections.extend([f"{signal.strategy_id}: {item}" for item in signal.objections])
            if signal.data_status_reason and signal.data_status_reason not in signal.objections:
                objections.append(f"{signal.strategy_id}: {signal.data_status_reason}")
            continue
        effective_weight += weight
        total_weight += weight
        participating.append(signal.strategy_id)
        normalized_score = signal.score if legacy_aggregation else max(
            Decimal("-1"), min(Decimal("1"), signal.score / score_scale if score_scale > 0 else signal.score)
        )
        weighted_score += normalized_score * weight
        if normalized_score > 0:
            positive += 1
        elif normalized_score < 0:
            negative += 1
        evidence.extend([f"{signal.strategy_id}: {item}" for item in signal.evidence])
        objections.extend([f"{signal.strategy_id}: {item}" for item in signal.objections])
        is_risk_control = signal.strategy_id in {"volatility_target", "drawdown_control", "futures_position_sentiment"}
        if not is_risk_control and signal.target_weight > target_weight and normalized_score > 0:
            target_weight = signal.target_weight
        if is_risk_control and signal.direction in {Direction.REDUCE, Direction.EXIT}:
            risk_caps.append(signal.target_weight)

    # Apply all active risk caps after the directional vote.  This makes the
    # result independent of strategy ordering and prevents neutral risk checks
    # from clamping an otherwise valid entry signal.
    if risk_caps:
        target_weight = min([target_weight, *risk_caps])

    if not total_weight:
        return StrategySignal(
            "strategy_aggregator",
            symbol,
            Direction.WATCH,
            Decimal("0"),
            Decimal("0"),
            target_weight,
            evidence,
            objections or ["没有可参与聚合的策略，本轮保持观望。"],
            "所有启用策略均不可用，本轮保持观望。",
            data_status=StrategyDataStatus.UNAVAILABLE,
            data_status_reason="所有启用策略均不可用。",
            participating_strategies=[],
            excluded_strategies=excluded,
            configured_weights=configured_weights,
            normalized_weights={},
        )
    average_score = weighted_score / total_weight if total_weight else Decimal("0")
    if positive and negative:
        target_weight = min(target_weight, conflict_max_weight)
        direction = Direction.HOLD if target_weight > 0 else Direction.WATCH
        explanation = "策略信号存在冲突，聚合器保守处理，降低或维持目标仓位。"
    elif average_score >= buy_threshold:
        direction = Direction.BUY
        explanation = "多策略信号一致偏多，聚合后允许提高目标仓位。"
    elif average_score <= exit_threshold:
        target_weight = Decimal("0")
        direction = Direction.EXIT
        explanation = "多策略信号一致偏弱，聚合后建议清仓或保持空仓。"
    else:
        direction = Direction.HOLD if target_weight > 0 else Direction.WATCH
        explanation = "策略评分中性，暂不主动扩大仓位。"

    status = StrategyDataStatus.NEUTRAL if direction in {Direction.HOLD, Direction.WATCH} and average_score == 0 else StrategyDataStatus.READY
    normalized_weights = {
        strategy_id: weight / total_weight
        for strategy_id, weight in configured_weights.items()
        if strategy_id in participating and total_weight
    }
    return StrategySignal(
        strategy_id="strategy_aggregator",
        symbol=symbol,
        direction=direction,
        score=average_score,
        confidence=(
            max(Decimal("0"), min(Decimal("1"), abs(average_score) / confidence_divisor))
            if confidence_divisor > 0
            else Decimal("0")
        ),
        target_weight=target_weight,
        evidence=evidence,
        objections=objections,
        explanation=explanation,
        version="v1",
        data_status=status,
        participating_strategies=participating,
        excluded_strategies=excluded,
        configured_weights=configured_weights,
        normalized_weights=normalized_weights,
    )
