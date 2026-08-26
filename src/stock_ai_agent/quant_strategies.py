from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List

from .models import Direction, FeatureSet, StrategyDataStatus, StrategySignal


@dataclass(frozen=True)
class QuantContext:
    histories: Dict[str, List[Decimal]]
    current_weights: Dict[str, Decimal]
    peak_values: Dict[str, Decimal] | None = None
    current_values: Dict[str, Decimal] | None = None

    def current_weight(self, symbol: str) -> Decimal:
        return self.current_weights.get(symbol, Decimal("0"))


@dataclass(frozen=True)
class ExternalStrategyContext:
    """Persisted external-market evidence. It can influence A-share signals only."""

    futures: Dict[str, Any] | None = None
    overseas: Dict[str, Dict[str, Any]] | None = None
    lhb_records: List[Dict[str, Any]] | None = None
    sector: str = "综合"
    auction_gap_pct: Decimal | None = None
    star_seats: set[str] | None = None
    seat_profiles: Dict[str, Dict[str, Any]] | None = None
    quant_seats: Dict[str, Dict[str, Any]] | None = None
    sector_defaulted: bool = False


def _return(history: List[Decimal], lookback: int) -> Decimal | None:
    if lookback <= 0 or len(history) <= lookback or history[-lookback - 1] == 0:
        return None
    return history[-1] / history[-lookback - 1] - Decimal("1")


class TimeSeriesMomentumStrategy:
    strategy_id = "time_series_momentum"

    def __init__(
        self,
        lookback_days: int = 20,
        buy_threshold: Decimal = Decimal("0.03"),
        reduce_threshold: Decimal = Decimal("-0.02"),
        target_weight: Decimal = Decimal("0.40"),
    ) -> None:
        self.lookback_days = lookback_days
        self.buy_threshold = buy_threshold
        self.reduce_threshold = reduce_threshold
        self.target_weight = target_weight

    def evaluate(self, symbol: str, features: FeatureSet, context: QuantContext) -> StrategySignal:
        history = context.histories.get(symbol, [])
        value = _return(history, self.lookback_days)
        if value is None:
            return _watch(self.strategy_id, symbol, "时间序列动量历史数据不足。")
        if value > self.buy_threshold and features.values.get("atr_ratio", Decimal("1")) <= Decimal("0.04"):
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal("2"), self.target_weight, [f"{self.lookback_days} 日收益为 {value:.2%}，高于动量阈值 {self.buy_threshold:.2%}。"])
        if value < self.reduce_threshold:
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


class FuturesPositionSentimentStrategy:
    strategy_id = "futures_position_sentiment"

    def __init__(self, options: Dict[str, Any]) -> None:
        self.overheated = Decimal(str(options.get("bullish_threshold", "0.60")))
        self.cap = Decimal(str(options.get("overheated_cap", "0.40")))

    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        row = context.futures or {}
        value = row.get("combined_net_ratio")
        if value is None:
            return _watch(self.strategy_id, symbol, "期指持仓数据缺失或已过期，禁止该策略触发交易。")
        ratio = Decimal(str(value))
        if ratio > self.overheated:
            return _signal(self.strategy_id, symbol, Direction.REDUCE, Decimal("0"), self.cap, [f"期指综合净多持仓 {ratio:.1%} 超过 {self.overheated:.0%}，将 A 股仓位上限压至 {self.cap:.0%}。"])
        return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), Decimal("1"), [f"期指综合净持仓 {ratio:.1%}，未施加仓位约束。"])


class OverseasMarketSentimentStrategy:
    strategy_id = "overseas_market_sentiment"
    sector_to_us = {"信息技术": "XLK", "医药卫生": "XLV", "金融地产": "XLF", "能源": "XLE", "工业": "XLI", "可选消费": "XLY", "必需消费": "XLP", "公用事业": "XLU", "材料": "XLB", "电信服务": "XLC"}

    def __init__(self, options: Dict[str, Any]) -> None:
        self.options = options

    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        data = context.overseas or {}
        sector_code = self.sector_to_us.get(context.sector)
        if "^IXIC" not in data or "^GSPC" not in data or "^DJI" not in data:
            return _watch(self.strategy_id, symbol, "外围市场数据或标的行业映射不完整，禁止该策略触发交易。")
        get = lambda key: Decimal(str(data.get(key, {}).get("change_pct", "0")))
        def source_note(key: str, label: str) -> str:
            row = data.get(key, {}) or {}
            source_symbol = str(row.get("source_symbol") or key)
            return f"{label}（来源 {source_symbol}{'，代理' if row.get('is_proxy') else ''}）"

        score = Decimal("0")
        evidence: list[str] = []
        sector_change = get(sector_code) if sector_code and sector_code in data else None
        if sector_change is None:
            evidence.append("标的板块缺失，使用综合板块，仅参考海外大盘情绪。")
        elif sector_change >= Decimal(str(self.options.get("us_sector_bullish", "2"))):
            score += Decimal(str(self.options.get("us_sector_weight", "2")))
            evidence.append(f"{source_note(sector_code, f'美股 {sector_code}')} 涨幅 {sector_change:.1f}% 强于阈值。")
        elif sector_change <= Decimal(str(self.options.get("us_sector_bearish", "-2"))):
            score -= Decimal(str(self.options.get("us_sector_weight", "2")))
            evidence.append(f"{source_note(sector_code, f'美股 {sector_code}')} 跌幅 {sector_change:.1f}% 弱于阈值。")
        nasdaq = get("^IXIC")
        if context.sector in self.options.get("nasdaq_correlated_sectors", ["信息技术"]) or context.sector_defaulted:
            if nasdaq >= Decimal(str(self.options.get("nasdaq_bullish", "1.5"))):
                score += Decimal(str(self.options.get("nasdaq_weight", "1.5")))
                evidence.append(f"{source_note('^IXIC', '纳斯达克')} 上涨 {nasdaq:.1f}% 。")
            elif nasdaq <= Decimal(str(self.options.get("nasdaq_bearish", "-1.5"))):
                score -= Decimal(str(self.options.get("nasdaq_weight", "1.5")))
        kr = get("KOSPI_IT")
        if sector_change is not None and context.sector in self.options.get("kr_tech_correlated_sectors", ["信息技术"]) and kr and sector_change * kr > 0:
            score += Decimal(str(self.options.get("kr_tech_weight", "1"))) * (Decimal("1") if kr > 0 else Decimal("-1"))
            evidence.append(f"韩股科技与美股板块同向 {kr:.1f}% 。")
        broad = [get("^IXIC"), get("^GSPC"), get("^DJI")]
        if all(value > 0 for value in broad):
            score += Decimal("0.5")
        elif all(value < 0 for value in broad):
            score -= Decimal("0.5")
        if score >= Decimal(str(self.options.get("strong_buy_score", "2.5"))):
            return _signal(self.strategy_id, symbol, Direction.BUY, score, Decimal(str(self.options.get("strong_buy_weight", "0.40"))), evidence)
        if score >= Decimal(str(self.options.get("buy_score", "1.5"))):
            return _signal(self.strategy_id, symbol, Direction.BUY, score, Decimal(str(self.options.get("buy_weight", "0.30"))), evidence)
        if score <= Decimal(str(self.options.get("strong_reduce_score", "-2"))):
            return _signal(self.strategy_id, symbol, Direction.REDUCE, score, Decimal(str(self.options.get("strong_reduce_weight", "0.10"))), [], evidence)
        if score <= Decimal(str(self.options.get("reduce_score", "-1"))):
            return _signal(self.strategy_id, symbol, Direction.REDUCE, score, Decimal(str(self.options.get("reduce_weight", "0.20"))), [], evidence)
        return _signal(self.strategy_id, symbol, Direction.HOLD, score, Decimal("0"), evidence or ["外围市场信号中性。"])


def _seat_rows(record: Dict[str, Any], side: str) -> list[tuple[str, Decimal]]:
    rows = []
    for index in range(1, 6):
        seat = str(record.get(f"{side}_seat_{index}") or "")
        amount = Decimal(str(record.get(f"{side}_amount_{index}") or "0"))
        if seat:
            rows.append((seat, amount))
    return rows


class _LhbStrategy:
    def _record(self, symbol: str, context: ExternalStrategyContext) -> Dict[str, Any] | None:
        return next((row for row in context.lhb_records or [] if row.get("symbol") == symbol), None)


class LhbFollowStarSeatsStrategy(_LhbStrategy):
    strategy_id = "lhb_follow_star_seats"
    def __init__(self, options: Dict[str, Any]) -> None: self.options = options
    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        record = self._record(symbol, context)
        if not record:
            return _watch(self.strategy_id, symbol, "龙虎榜数据尚未同步。") if context.lhb_records is None else _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), Decimal("0"), ["最近龙虎榜没有该标的记录。"])
        if not record.get("seat_detail_available", True):
            return _watch(self.strategy_id, symbol, "龙虎榜席位明细不可用，席位跟随策略已禁用。")
        stars = context.star_seats or set(self.options.get("star_seats", []))
        minimum = Decimal(str(self.options.get("min_buy_amount", "1000")))
        matches = [seat for seat, amount in _seat_rows(record, "buy") if seat in stars and amount >= minimum]
        return _signal(self.strategy_id, symbol, Direction.BUY, Decimal(str(self.options.get("signal_score", "1"))), Decimal("0"), [f"明星席位 {matches[0]} 昨日买入达阈值。"] ) if matches else _watch(self.strategy_id, symbol, "龙虎榜未出现满足金额阈值的明星买入席位。")


class LhbReverseInstitutionalStrategy(_LhbStrategy):
    strategy_id = "lhb_reverse_institutional"
    def __init__(self, options: Dict[str, Any]) -> None: self.options = options
    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        record = self._record(symbol, context)
        if context.lhb_records is None or context.auction_gap_pct is None:
            return _watch(self.strategy_id, symbol, "机构龙虎榜或集合竞价低开数据缺失。")
        if not record:
            return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), Decimal("0"), ["最近龙虎榜没有该标的记录。"])
        if not record.get("seat_detail_available", True):
            net_buy = Decimal(str(record.get("net_buy") or "0"))
            if net_buy <= -Decimal(str(self.options.get("min_sell_amount", "500"))) and context.auction_gap_pct <= Decimal(str(self.options.get("min_gap_down", "-3"))):
                return _signal(self.strategy_id, symbol, Direction.BUY, Decimal(str(self.options.get("signal_score", "1.5"))), Decimal(str(self.options.get("target_weight", "0.20"))), [f"龙虎榜汇总净卖出 {abs(net_buy):.0f}，集合竞价低开 {context.auction_gap_pct:.1f}% 。"])
            return _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), Decimal("0"), ["仅有龙虎榜汇总数据，未满足机构反向的净卖出与低开条件。"])
        minimum = Decimal(str(self.options.get("min_sell_amount", "500")))
        count = sum(1 for seat, amount in _seat_rows(record, "sell") if seat == "机构专用" and amount >= minimum)
        if count >= int(self.options.get("min_institutional_count", 3)) and context.auction_gap_pct <= Decimal(str(self.options.get("min_gap_down", "-3"))):
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal(str(self.options.get("signal_score", "1.5"))), Decimal(str(self.options.get("target_weight", "0.20"))), [f"{count} 个机构席位集中卖出且集合竞价低开 {context.auction_gap_pct:.1f}% 。"])
        return _watch(self.strategy_id, symbol, "机构恐慌卖出与低开条件未同时满足。")


class LhbSeatProfileStrategy(_LhbStrategy):
    strategy_id = "lhb_seat_profile"
    def __init__(self, options: Dict[str, Any]) -> None: self.options = options
    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        record = self._record(symbol, context)
        if not record:
            return _watch(self.strategy_id, symbol, "龙虎榜数据尚未同步。") if context.lhb_records is None else _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), Decimal("0"), ["最近龙虎榜没有该标的记录。"])
        if not record.get("seat_detail_available", True):
            return _watch(self.strategy_id, symbol, "龙虎榜席位明细不可用，席位画像策略已禁用。")
        minimum = Decimal(str(self.options.get("min_buy_amount", "1000")))
        profiles = context.seat_profiles or {}
        candidates = [profiles.get(seat) for seat, amount in _seat_rows(record, "buy") if amount >= minimum and profiles.get(seat)]
        candidates = [item for item in candidates if Decimal(str(item.get("t3_win_rate", "0"))) >= Decimal(str(self.options.get("min_win_rate", "0.60"))) and int(item.get("buy_count", 0)) >= int(self.options.get("min_sample_size", 20))]
        if not candidates:
            return _watch(self.strategy_id, symbol, "龙虎榜买入席位没有满足胜率和样本量门槛。")
        rate = max(Decimal(str(item.get("t3_win_rate", "0"))) for item in candidates)
        score = Decimal("2") if rate >= Decimal("0.80") else Decimal("1.5") if rate >= Decimal("0.70") else Decimal("1")
        return _signal(self.strategy_id, symbol, Direction.BUY, score, Decimal("0"), [f"席位历史 T+3 胜率 {rate:.1%}，样本充分。"])


class LhbConsensusStrategy(_LhbStrategy):
    strategy_id = "lhb_consensus"
    def __init__(self, options: Dict[str, Any]) -> None: self.options = options
    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        record = self._record(symbol, context)
        if not record:
            return _watch(self.strategy_id, symbol, "龙虎榜数据尚未同步。") if context.lhb_records is None else _signal(self.strategy_id, symbol, Direction.HOLD, Decimal("0"), Decimal("0"), ["最近龙虎榜没有该标的记录。"])
        if not record.get("seat_detail_available", True):
            star_net_buy = record.get("star_net_buy")
            institution_net_buy = record.get("institution_net_buy")
            if star_net_buy is None or institution_net_buy is None:
                return _watch(self.strategy_id, symbol, "龙虎榜汇总缺少游资和机构净买额，共振策略已禁用。")
            minimum = Decimal(str(self.options.get("min_buy_amount", "1000")))
            if Decimal(str(star_net_buy)) >= minimum and Decimal(str(institution_net_buy)) >= minimum:
                return _signal(self.strategy_id, symbol, Direction.BUY, Decimal(str(self.options.get("signal_score", "2.5"))), Decimal("0"), [f"龙虎榜汇总显示游资净买入 {star_net_buy}、机构净买入 {institution_net_buy}，形成买入共振。"])
            return _watch(self.strategy_id, symbol, "龙虎榜汇总未形成游资与机构买入共振。")
        minimum = Decimal(str(self.options.get("min_buy_amount", "1000")))
        rows = _seat_rows(record, "buy")
        stars = context.star_seats or set(self.options.get("star_seats", []))
        if any(seat in stars and amount >= minimum for seat, amount in rows) and any(seat == "机构专用" and amount >= minimum for seat, amount in rows):
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal(str(self.options.get("signal_score", "2.5"))), Decimal("0"), ["明星游资与机构席位同时净买入。"])
        return _watch(self.strategy_id, symbol, "未形成明星游资与机构买入共振。")


class LhbQuantSectorStrategy(_LhbStrategy):
    strategy_id = "lhb_quant_sector"
    def __init__(self, options: Dict[str, Any]) -> None: self.options = options
    def evaluate(self, symbol: str, features: FeatureSet, context: ExternalStrategyContext) -> StrategySignal:
        del features
        if context.lhb_records is None:
            return _watch(self.strategy_id, symbol, "量化席位策略所需龙虎榜数据尚未同步。")
        records = context.lhb_records
        if records and not any(record.get("seat_detail_available", True) for record in records):
            return _watch(self.strategy_id, symbol, "龙虎榜席位明细不可用，量化板块策略已禁用。")
        quant_seats = context.quant_seats or {}
        minimum = Decimal(str(self.options.get("min_buy_amount", "500")))
        by_firm: dict[str, int] = {}
        for record in records:
            if str(record.get("sector") or "") != context.sector:
                continue
            for seat, amount in _seat_rows(record, "buy"):
                firm = quant_seats.get(seat, {}).get("quant_firm")
                if firm and amount >= minimum:
                    by_firm[str(firm)] = by_firm.get(str(firm), 0) + 1
        required = int(self.options.get("min_symbols_in_sector", 3))
        firm = next((name for name, count in by_firm.items() if count >= required), None)
        if firm:
            return _signal(self.strategy_id, symbol, Direction.BUY, Decimal(str(self.options.get("signal_score", "1"))), Decimal("0"), [f"量化机构 {firm} 集中买入 {context.sector} 板块 {by_firm[firm]} 只标的。"])
        return _watch(self.strategy_id, symbol, "未观察到量化席位对所属板块的集中买入。")


def _watch(strategy_id: str, symbol: str, reason: str) -> StrategySignal:
    return StrategySignal(
        strategy_id,
        symbol,
        Direction.WATCH,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        [],
        [reason],
        reason,
        data_status=StrategyDataStatus.UNAVAILABLE,
        data_status_reason=reason,
    )


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
    status = StrategyDataStatus.NEUTRAL if direction in {Direction.HOLD, Direction.WATCH} and score == 0 else StrategyDataStatus.READY
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
        data_status=status,
    )
