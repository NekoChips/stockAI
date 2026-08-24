from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from .config import RiskConfig
from .models import Decision, Direction, PaperOrder, Portfolio, Quote, StrategySignal
from .universe import Universe, UniverseError, infer_asset_type


@dataclass(frozen=True)
class RiskResult:
    decision: Decision
    order: Optional[PaperOrder] = None


class RiskEngine:
    def __init__(self, config: RiskConfig, universe: Universe) -> None:
        self.config = config
        self.universe = universe

    def evaluate(
        self,
        signal: StrategySignal,
        portfolio: Portfolio,
        quote: Quote,
        daily_trade_count: int = 0,
        symbol_daily_operation_count: int = 0,
        portfolio_daily_loss_hit: bool = False,
        historical_peak: Decimal | None = None,
    ) -> RiskResult:
        reasons = []
        try:
            instrument = self.universe.require(signal.symbol)
        except UniverseError as exc:
            return self._reject(signal, str(exc))

        if not quote.is_fresh:
            return self._reject(signal, "行情数据已过期，禁止产生新的模拟订单。")
        position = portfolio.positions.get(signal.symbol)
        if position and position.quantity > 0:
            position.highest_price = max(position.highest_price, quote.latest_price)
        forced_reason = self._forced_reason(position, quote, portfolio, historical_peak)
        forced = forced_reason is not None and position is not None and position.quantity > 0
        if forced:
            current_weight = portfolio.position_weight(signal.symbol)
            forced_target = Decimal("0") if "清仓" in forced_reason else (current_weight * Decimal("0.5")).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            signal = StrategySignal(
                "risk_control",
                signal.symbol,
                Direction.EXIT if "清仓" in forced_reason else Direction.REDUCE,
                Decimal("-1"),
                Decimal("1"),
                forced_target,
                [],
                [forced_reason],
                forced_reason,
            )
        if not forced and self.config.max_daily_trades is not None and daily_trade_count >= self.config.max_daily_trades:
            return self._reject(signal, "已达到单日最大交易次数，禁止继续交易。")
        if not forced and symbol_daily_operation_count >= self.config.max_operations_per_symbol:
            return self._reject(signal, f"{signal.symbol} 已达到单日 {self.config.max_operations_per_symbol} 笔操作上限。")
        if not forced and portfolio_daily_loss_hit and signal.direction in {Direction.BUY, Direction.ADD}:
            return self._reject(signal, "组合当日亏损已达到风控阈值，停止新开仓和加仓。")

        target_weight = min(signal.target_weight, self.config.symbol_limit(instrument.asset_type))
        current_weight = portfolio.position_weight(signal.symbol)
        total_asset = portfolio.total_asset()
        other_market_value = portfolio.total_market_value() - (
            portfolio.positions[signal.symbol].market_value if signal.symbol in portfolio.positions else Decimal("0")
        )
        remaining_total_weight = max(Decimal("0"), self.config.max_total_exposure - other_market_value / total_asset) if total_asset > 0 else Decimal("0")
        other_asset_market_value = Decimal("0")
        for held_symbol, position in portfolio.positions.items():
            if held_symbol == signal.symbol:
                continue
            try:
                held_type = self.universe.require(held_symbol).asset_type
            except UniverseError:
                held_type = infer_asset_type(held_symbol)
            if held_type == instrument.asset_type:
                other_asset_market_value += position.market_value
        remaining_asset_weight = max(
            Decimal("0"),
            self.config.asset_total_limit(instrument.asset_type) - other_asset_market_value / total_asset,
        ) if total_asset > 0 else Decimal("0")
        if signal.direction in {Direction.BUY, Direction.ADD} and (
            remaining_total_weight <= 0 or remaining_asset_weight <= 0
        ):
            return self._reject(
                signal,
                f"当前组合或{instrument.asset_type}总仓位已达上限，禁止继续买入或加仓。",
            )
        if target_weight > remaining_total_weight:
            target_weight = remaining_total_weight
            reasons.append("目标仓位超过总仓位上限，已下调。")
        if target_weight > remaining_asset_weight:
            target_weight = remaining_asset_weight
            reasons.append(f"目标仓位超过{instrument.asset_type}总仓位上限，已下调。")

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

    def _forced_reason(self, position, quote: Quote, portfolio: Portfolio, historical_peak: Decimal | None) -> str | None:
        if position is None or position.quantity <= 0:
            return None
        if position.average_cost > 0 and quote.latest_price <= position.average_cost * (Decimal("1") - self.config.single_position_loss):
            return f"单标的亏损达到 {self.config.single_position_loss:.0%}，触发风控清仓。"
        if position.highest_price > 0 and quote.latest_price <= position.highest_price * (Decimal("1") - self.config.trailing_drawdown):
            return f"从持仓期间最高价回撤达到 {self.config.trailing_drawdown:.0%}，触发风控清仓。"
        if historical_peak and historical_peak > 0 and portfolio.total_asset() <= historical_peak * (Decimal("1") - self.config.max_drawdown):
            return f"组合历史高点回撤达到 {self.config.max_drawdown:.0%}，触发风控降仓。"
        return None

    def _reject(self, signal: StrategySignal, reason: str) -> RiskResult:
        return RiskResult(Decision(signal.symbol, signal.direction, signal.target_weight, False, [reason], signal), None)

    def _approve(self, signal: StrategySignal, target_weight: Decimal, reasons: list, order: Optional[PaperOrder]) -> RiskResult:
        return RiskResult(Decision(signal.symbol, signal.direction, target_weight, True, reasons, signal), order)
