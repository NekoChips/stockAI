from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from .models import Direction, Fill, OrderStatus, PaperOrder, Portfolio, Position, Quote


class PaperBrokerError(RuntimeError):
    pass


@dataclass(frozen=True)
class FillAttempt:
    order: PaperOrder
    fill: Fill | None = None


class PaperBroker:
    """Deterministic A-share paper broker with explicit order transitions."""

    def __init__(
        self,
        portfolio: Portfolio,
        fee_rate: Decimal,
        slippage_rate: Decimal,
        *,
        min_commission: Decimal = Decimal("5"),
        stock_sell_stamp_tax: Decimal = Decimal("0.0005"),
    ) -> None:
        self.portfolio = portfolio
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.min_commission = min_commission
        self.stock_sell_stamp_tax = stock_sell_stamp_tax
        self.orders: list[PaperOrder] = []
        self.fills: list[Fill] = []

    def submit(self, order: PaperOrder) -> PaperOrder:
        if order.quantity <= 0:
            raise PaperBrokerError("模拟订单数量必须大于 0。")
        if order.direction not in {Direction.BUY, Direction.ADD, Direction.REDUCE, Direction.EXIT}:
            raise PaperBrokerError("持有或观望信号不能提交模拟订单。")
        if order.status != OrderStatus.APPROVED:
            raise PaperBrokerError("只有风控通过的订单可以提交。")
        now = datetime.now(timezone.utc)
        submitted = replace(order, order_id=order.order_id or uuid4().hex, status=OrderStatus.SUBMITTED, submitted_at=now, updated_at=now)
        self._replace_order(submitted)
        return submitted

    def create(self, order: PaperOrder) -> PaperOrder:
        if order.status != OrderStatus.CREATED:
            raise PaperBrokerError("只有新建订单可以进入已创建状态。")
        created = replace(order, order_id=order.order_id or uuid4().hex, updated_at=order.updated_at or order.created_at)
        self._replace_order(created)
        return created

    def approve(self, order: PaperOrder) -> PaperOrder:
        if order.status != OrderStatus.CREATED:
            raise PaperBrokerError("只有已创建订单可以进入风控通过状态。")
        approved = replace(order, order_id=order.order_id or uuid4().hex, status=OrderStatus.APPROVED, updated_at=datetime.now(timezone.utc))
        self._replace_order(approved)
        return approved

    def reject(self, order: PaperOrder, reason: str) -> PaperOrder:
        rejected = replace(order, status=OrderStatus.REJECTED, rejected_reason=reason, updated_at=datetime.now(timezone.utc))
        self._replace_order(rejected)
        return rejected

    def cancel(self, order: PaperOrder, reason: str = "人工取消") -> PaperOrder:
        if order.status not in {OrderStatus.CREATED, OrderStatus.APPROVED, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
            raise PaperBrokerError("当前订单状态不允许取消。")
        canceled = replace(order, status=OrderStatus.CANCELED, rejected_reason=reason, updated_at=datetime.now(timezone.utc))
        self._replace_order(canceled)
        return canceled

    def try_fill(self, order: PaperOrder, quote: Quote, *, max_fill_quantity: int | None = None) -> FillAttempt:
        if order.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
            raise PaperBrokerError("只有已提交或部分成交订单可以撮合。")
        if quote.symbol != order.symbol:
            return FillAttempt(self.reject(order, "订单标的与行情标的不一致，禁止撮合。"))
        if not quote.is_fresh:
            return FillAttempt(self.reject(order, "行情数据已过期，订单拒绝成交。"))
        quantity = min(order.remaining_quantity, max_fill_quantity or order.remaining_quantity)
        if quantity <= 0:
            return FillAttempt(order)
        try:
            fill = self._fill(order, quote, quantity)
        except PaperBrokerError as exc:
            return FillAttempt(self.reject(order, str(exc)))
        filled_quantity = order.filled_quantity + quantity
        gross_filled = order.average_fill_price * Decimal(order.filled_quantity) + fill.price * Decimal(quantity)
        average = (gross_filled / Decimal(filled_quantity)).quantize(Decimal("0.0001"))
        status = OrderStatus.FILLED if filled_quantity == order.quantity else OrderStatus.PARTIALLY_FILLED
        updated = replace(order, status=status, filled_quantity=filled_quantity, average_fill_price=average, updated_at=fill.timestamp)
        self._replace_order(updated)
        self.fills.append(fill)
        return FillAttempt(updated, fill)

    def execute(self, order: PaperOrder, quote: Quote | None = None) -> Fill:
        """Compatibility shortcut for one-shot simulations."""
        if quote is None:
            now = datetime.now(timezone.utc)
            quote = Quote(order.symbol, order.symbol, now, order.requested_price, order.requested_price, order.requested_price, order.requested_price, order.requested_price, Decimal("0"), Decimal("0"), Decimal("0"), "order", now, bid_price=order.requested_price, ask_price=order.requested_price)
        attempt = self.try_fill(self.submit(self.approve(self.create(order))), quote)
        if attempt.fill is None:
            raise PaperBrokerError(attempt.order.rejected_reason or "订单未成交。")
        return attempt.fill

    def _fill(self, order: PaperOrder, quote: Quote, quantity: int) -> Fill:
        is_buy = order.direction in {Direction.BUY, Direction.ADD}
        market_price = (quote.ask_price if is_buy else quote.bid_price) or quote.latest_price
        if market_price <= 0:
            raise PaperBrokerError("盘口价格无效，无法成交。")
        fill_price = market_price * (Decimal("1") + self.slippage_rate if is_buy else Decimal("1") - self.slippage_rate)
        self._validate_price_limit(order, quote, fill_price)
        gross = fill_price * Decimal(quantity)
        commission = max(self.min_commission, gross * self.fee_rate)
        stamp_tax = gross * self.stock_sell_stamp_tax if not is_buy and order.asset_type == "stock" else Decimal("0")
        fee = (commission + stamp_tax).quantize(Decimal("0.01"))
        if is_buy:
            if gross + fee > self.portfolio.cash:
                raise PaperBrokerError("模拟账户现金不足，无法成交。")
            position = self.portfolio.positions.get(order.symbol, Position(order.symbol))
            old_cost = position.average_cost * Decimal(position.quantity)
            position.quantity += quantity
            position.average_cost = ((old_cost + gross) / Decimal(position.quantity)).quantize(Decimal("0.0001"))
            position.last_price = fill_price
            position.highest_price = max(position.highest_price, fill_price)
            self.portfolio.positions[order.symbol] = position
            self.portfolio.cash = (self.portfolio.cash - gross - fee).quantize(Decimal("0.01"))
        else:
            position = self.portfolio.positions.get(order.symbol)
            if not position or position.available_quantity < quantity:
                raise PaperBrokerError("可卖数量不足，股票 T+1 或持仓限制导致无法成交。")
            position.quantity -= quantity
            position.available_quantity -= quantity
            position.last_price = fill_price
            position.realized_pnl = (position.realized_pnl + gross - fee - position.average_cost * Decimal(quantity)).quantize(Decimal("0.01"))
            self.portfolio.cash = (self.portfolio.cash + gross - fee).quantize(Decimal("0.01"))
            if position.quantity == 0:
                self.portfolio.positions.pop(order.symbol, None)
        return Fill(order.symbol, order.direction, quantity, fill_price.quantize(Decimal("0.0001")), fee, (abs(fill_price - order.requested_price) * Decimal(quantity)).quantize(Decimal("0.01")), datetime.now(timezone.utc), order.order_id)

    @staticmethod
    def _validate_price_limit(order: PaperOrder, quote: Quote, fill_price: Decimal) -> None:
        """Reject fills outside the A-share daily price band instead of inventing a fill."""
        if quote.previous_close <= 0:
            return
        limit = Decimal("0.10")
        code = order.symbol.split(".", 1)[0]
        if order.asset_type == "stock" and code.startswith(("300", "301", "688", "689")):
            limit = Decimal("0.20")
        elif order.asset_type == "stock" and code.startswith(("8", "4")):
            limit = Decimal("0.30")
        lower = quote.previous_close * (Decimal("1") - limit)
        upper = quote.previous_close * (Decimal("1") + limit)
        if fill_price < lower or fill_price > upper:
            raise PaperBrokerError("盘口价格超出当日涨跌停范围，禁止模拟成交。")

    def _replace_order(self, updated: PaperOrder) -> None:
        for index, order in enumerate(self.orders):
            if order.order_id == updated.order_id:
                self.orders[index] = updated
                return
        self.orders.append(updated)

    def settle_t_plus_one(self) -> None:
        for position in self.portfolio.positions.values():
            position.available_quantity = position.quantity
