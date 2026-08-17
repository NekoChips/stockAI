from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .config import RiskConfig
from .models import Decision, Direction, PaperOrder, Portfolio, Quote, StrategySignal
from .universe import Universe, UniverseError


@dataclass(frozen=True)
class RiskResult:
    decision: Decision
    order: Optional[PaperOrder] = None


class RiskEngine:
    def __init__(self, config: RiskConfig, universe: Universe) -> None:
        self.config = config
        self.universe = universe

    def evaluate(self, signal: StrategySignal, portfolio: Portfolio, quote: Quote, daily_trade_count: int = 0) -> RiskResult:
        reasons = []
        try:
            self.universe.require(signal.symbol)
        except UniverseError as exc:
            return self._reject(signal, str(exc))

        if not quote.is_fresh:
            return self._reject(signal, "行情数据已过期，禁止产生新的模拟订单。")
        if daily_trade_count >= self.config.max_daily_trades:
            return self._reject(signal, "已达到单日最大交易次数，禁止继续交易。")

        target_weight = min(signal.target_weight, self.config.max_symbol_weight)
        current_weight = portfolio.position_weight(signal.symbol)
        total_asset = portfolio.total_asset()
        if target_weight > self.config.max_total_exposure:
            target_weight = self.config.max_total_exposure
            reasons.append("目标仓位超过总仓位上限，已下调。")

        if quote.latest_price <= 0:
            return self._reject(signal, "行情价格无效，无法计算订单。")

        if signal.direction in {Direction.BUY, Direction.ADD}:
            min_cash = total_asset * self.config.min_cash_ratio
            target_value = total_asset * target_weight
            current_value = portfolio.positions.get(signal.symbol).market_value if signal.symbol in portfolio.positions else Decimal("0")
            buy_value = max(Decimal("0"), target_value - current_value)
            available_cash = max(Decimal("0"), portfolio.cash - min_cash)
            if buy_value <= 0:
                return self._approve(signal, target_weight, reasons + ["当前仓位已达到目标仓位，无需买入。"], None)
            if buy_value > available_cash:
                buy_value = available_cash
                reasons.append("受最小现金比例约束，买入金额已下调。")
            quantity = int((buy_value / quote.latest_price / Decimal("100")).to_integral_value(rounding=ROUND_DOWN)) * 100
            if quantity <= 0:
                return self._reject(signal, "可用现金不足以按 100 股/份整数倍买入。")
            order = PaperOrder(signal.symbol, signal.direction, quantity, quote.latest_price, reason="；".join(reasons or signal.evidence[:2]))
            return self._approve(signal, target_weight, reasons or ["风控通过，允许生成模拟买入订单。"], order)

        if signal.direction in {Direction.REDUCE, Direction.EXIT}:
            position = portfolio.positions.get(signal.symbol)
            if not position or position.quantity <= 0:
                return self._approve(signal, Decimal("0"), ["当前没有持仓，无需卖出。"], None)
            target_quantity = int((position.quantity * target_weight / current_weight).to_integral_value(rounding=ROUND_DOWN)) if current_weight > 0 else 0
            sell_quantity = position.quantity if signal.direction == Direction.EXIT else max(0, position.quantity - target_quantity)
            sell_quantity = min(sell_quantity, position.available_quantity)
            if sell_quantity <= 0:
                return self._reject(signal, "可卖数量不足，股票 T+1 或持仓限制导致无法卖出。")
            order = PaperOrder(signal.symbol, signal.direction, sell_quantity, quote.latest_price, reason="；".join(reasons or signal.objections[:2]))
            return self._approve(signal, target_weight, reasons or ["风控通过，允许生成模拟卖出订单。"], order)

        return self._approve(signal, current_weight, ["策略建议持有或观望，未生成模拟订单。"], None)

    def _reject(self, signal: StrategySignal, reason: str) -> RiskResult:
        return RiskResult(Decision(signal.symbol, signal.direction, signal.target_weight, False, [reason], signal), None)

    def _approve(self, signal: StrategySignal, target_weight: Decimal, reasons: list, order: Optional[PaperOrder]) -> RiskResult:
        return RiskResult(Decision(signal.symbol, signal.direction, target_weight, True, reasons, signal), order)
