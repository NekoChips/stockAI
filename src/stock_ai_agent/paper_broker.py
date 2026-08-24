from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .models import Direction, Fill, OrderStatus, PaperOrder, Portfolio, Position


class PaperBrokerError(RuntimeError):
    pass


class PaperBroker:
    def __init__(self, portfolio: Portfolio, fee_rate: Decimal, slippage_rate: Decimal) -> None:
        self.portfolio = portfolio
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.orders: list[PaperOrder] = []
        self.fills: list[Fill] = []

    def execute(self, order: PaperOrder) -> Fill:
        if order.quantity <= 0:
            raise PaperBrokerError("模拟订单数量必须大于 0。")
        if order.direction in {Direction.BUY, Direction.ADD}:
            fill_price = order.requested_price * (Decimal("1") + self.slippage_rate)
            gross = fill_price * Decimal(order.quantity)
            fee = gross * self.fee_rate
            cash_needed = gross + fee
            if cash_needed > self.portfolio.cash:
                raise PaperBrokerError("模拟账户现金不足，无法成交。")
            position = self.portfolio.positions.get(order.symbol, Position(order.symbol))
            old_cost = position.average_cost * Decimal(position.quantity)
            new_quantity = position.quantity + order.quantity
            position.average_cost = ((old_cost + gross) / Decimal(new_quantity)).quantize(Decimal("0.0001"))
            position.quantity = new_quantity
            position.last_price = fill_price
            position.highest_price = max(position.highest_price, fill_price)
            self.portfolio.positions[order.symbol] = position
            self.portfolio.cash = (self.portfolio.cash - cash_needed).quantize(Decimal("0.01"))
        elif order.direction in {Direction.REDUCE, Direction.EXIT}:
            position = self.portfolio.positions.get(order.symbol)
            if not position or position.available_quantity < order.quantity:
                raise PaperBrokerError("可卖数量不足，无法成交。")
            fill_price = order.requested_price * (Decimal("1") - self.slippage_rate)
            gross = fill_price * Decimal(order.quantity)
            fee = gross * self.fee_rate
            position.quantity -= order.quantity
            position.available_quantity -= order.quantity
            position.last_price = fill_price
            position.realized_pnl += gross - fee - position.average_cost * Decimal(order.quantity)
            self.portfolio.cash = (self.portfolio.cash + gross - fee).quantize(Decimal("0.01"))
        else:
            raise PaperBrokerError("持有或观望信号不会生成成交。")

        fill = Fill(
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.quantity,
            price=fill_price.quantize(Decimal("0.0001")),
            fee=fee.quantize(Decimal("0.01")),
            slippage=(abs(fill_price - order.requested_price) * Decimal(order.quantity)).quantize(Decimal("0.01")),
            timestamp=datetime.now(timezone.utc),
        )
        self.orders.append(PaperOrder(order.symbol, order.direction, order.quantity, order.requested_price, OrderStatus.FILLED, order.reason))
        self.fills.append(fill)
        return fill

    def settle_t_plus_one(self) -> None:
        for position in self.portfolio.positions.values():
            position.available_quantity = position.quantity
