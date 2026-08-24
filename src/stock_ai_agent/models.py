from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Dict, List, Optional


class Direction(str, Enum):
    BUY = "买入"
    ADD = "加仓"
    REDUCE = "减仓"
    EXIT = "清仓"
    HOLD = "持有"
    WATCH = "观望"


class OrderStatus(str, Enum):
    CREATED = "已创建"
    APPROVED = "风控通过"
    SUBMITTED = "已提交"
    PARTIALLY_FILLED = "部分成交"
    REJECTED = "已拒绝"
    FILLED = "已成交"
    CANCELED = "已取消"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_type: str
    name: str = ""
    lifecycle_status: str = "observing"
    trading_enabled: bool = True

    @property
    def exchange(self) -> str:
        return self.symbol.rsplit(".", 1)[1]


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    timestamp: datetime
    latest_price: Decimal
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    previous_close: Decimal
    volume: Decimal
    amount: Decimal
    change_percent: Decimal
    source: str
    fetched_at: datetime
    freshness_seconds: int = 90
    bid_price: Optional[Decimal] = None
    ask_price: Optional[Decimal] = None

    @property
    def is_fresh(self) -> bool:
        return abs((self.fetched_at - self.timestamp).total_seconds()) <= self.freshness_seconds


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    amount: Decimal = Decimal("0")
    price_mode: str = "qfq"
    adjustment_factor: Decimal = Decimal("1")


@dataclass(frozen=True)
class FeatureSet:
    symbol: str
    timestamp: datetime
    values: Dict[str, Decimal]
    missing_reasons: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing_reasons


@dataclass(frozen=True)
class StrategySignal:
    strategy_id: str
    symbol: str
    direction: Direction
    score: Decimal
    confidence: Decimal
    target_weight: Decimal
    evidence: List[str]
    objections: List[str] = field(default_factory=list)
    explanation: str = ""
    version: str = "v1"


@dataclass(frozen=True)
class Decision:
    symbol: str
    direction: Direction
    target_weight: Decimal
    approved: bool
    reasons: List[str]
    source_signal: Optional[StrategySignal] = None


@dataclass(frozen=True)
class PaperOrder:
    symbol: str
    direction: Direction
    quantity: int
    requested_price: Decimal
    status: OrderStatus = OrderStatus.CREATED
    reason: str = ""
    order_id: str = ""
    asset_type: str = "etf"
    filled_quantity: int = 0
    average_fill_price: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    rejected_reason: str = ""

    @property
    def notional(self) -> Decimal:
        return (self.requested_price * Decimal(self.quantity)).quantize(Decimal("0.01"))

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.quantity - self.filled_quantity)


@dataclass(frozen=True)
class Fill:
    symbol: str
    direction: Direction
    quantity: int
    price: Decimal
    fee: Decimal
    slippage: Decimal
    timestamp: datetime
    order_id: str = ""

    @property
    def gross_amount(self) -> Decimal:
        return (self.price * Decimal(self.quantity)).quantize(Decimal("0.01"))

    @property
    def net_cash_change(self) -> Decimal:
        if self.direction in {Direction.BUY, Direction.ADD}:
            return -(self.gross_amount + self.fee)
        return self.gross_amount - self.fee


@dataclass
class Position:
    symbol: str
    quantity: int = 0
    available_quantity: int = 0
    average_cost: Decimal = Decimal("0")
    last_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    highest_price: Decimal = Decimal("0")

    @property
    def market_value(self) -> Decimal:
        return (self.last_price * Decimal(self.quantity)).quantize(Decimal("0.01"))

    @property
    def cost_value(self) -> Decimal:
        return (self.average_cost * Decimal(self.quantity)).quantize(Decimal("0.01"))

    @property
    def unrealized_pnl(self) -> Decimal:
        return (self.market_value - self.cost_value).quantize(Decimal("0.01"))


@dataclass
class Portfolio:
    cash: Decimal
    positions: Dict[str, Position] = field(default_factory=dict)

    def total_market_value(self) -> Decimal:
        return sum((position.market_value for position in self.positions.values()), Decimal("0")).quantize(Decimal("0.01"))

    def total_asset(self) -> Decimal:
        return (self.cash + self.total_market_value()).quantize(Decimal("0.01"))

    def position_weight(self, symbol: str) -> Decimal:
        total = self.total_asset()
        if total <= 0 or symbol not in self.positions:
            return Decimal("0")
        return (self.positions[symbol].market_value / total).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


@dataclass(frozen=True)
class LearningProposal:
    strategy_id: str
    suggestion: str
    evidence: List[str]
    status: str = "待人工确认"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
