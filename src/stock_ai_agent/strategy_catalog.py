"""Stable strategy metadata shared by persistence and dashboard layers."""

from __future__ import annotations


STRATEGY_DEFINITIONS = (
    {
        "strategy_id": "technical_composite",
        "name_zh": "技术指标综合",
        "name_en": "Technical Composite",
        "category_zh": "技术分析",
        "category_en": "Technical Analysis",
        "description_zh": "综合均线、MACD、RSI、布林带、ATR 和成交量信号。",
        "description_en": "Combines moving averages, MACD, RSI, Bollinger Bands, ATR, and volume signals.",
    },
    {
        "strategy_id": "time_series_momentum",
        "name_zh": "时间序列动量",
        "name_en": "Time-Series Momentum",
        "category_zh": "量化策略",
        "category_en": "Quantitative",
        "description_zh": "根据标的自身一段时间的收益方向判断趋势强弱。",
        "description_en": "Uses the asset's own trailing return to identify directional momentum.",
    },
    {
        "strategy_id": "mean_reversion",
        "name_zh": "均值回归",
        "name_en": "Mean Reversion",
        "category_zh": "量化策略",
        "category_en": "Quantitative",
        "description_zh": "根据价格相对均值的偏离程度寻找修复机会。",
        "description_en": "Looks for mean-reversion opportunities from deviations around the mean.",
    },
    {
        "strategy_id": "relative_strength",
        "name_zh": "相对强弱轮动",
        "name_en": "Relative Strength Rotation",
        "category_zh": "量化策略",
        "category_en": "Quantitative",
        "description_zh": "比较观察池标的的相对表现，辅助资金向强势标的轮动。",
        "description_en": "Compares watchlist performance to support rotation toward relative strength.",
    },
    {
        "strategy_id": "volatility_target",
        "name_zh": "波动率目标",
        "name_en": "Volatility Targeting",
        "category_zh": "风险控制",
        "category_en": "Risk Control",
        "description_zh": "根据 ATR 波动率限制目标仓位。",
        "description_en": "Caps target exposure according to ATR-based volatility.",
    },
    {
        "strategy_id": "drawdown_control",
        "name_zh": "回撤控制",
        "name_en": "Drawdown Control",
        "category_zh": "风险控制",
        "category_en": "Risk Control",
        "description_zh": "根据组合回撤触发降仓或清仓。",
        "description_en": "Reduces or exits exposure when portfolio drawdown limits are reached.",
    },
    {
        "strategy_id": "strategy_aggregator",
        "name_zh": "策略聚合器",
        "name_en": "Strategy Aggregator",
        "category_zh": "组合引擎",
        "category_en": "Portfolio Engine",
        "description_zh": "按权重汇总多个策略信号并处理冲突。",
        "description_en": "Aggregates weighted strategy signals and resolves conflicts.",
    },
    {"strategy_id": "futures_position_sentiment", "name_zh": "期指情绪对冲", "name_en": "Futures Position Sentiment", "category_zh": "风险控制", "category_en": "Risk Control", "description_zh": "以 IC 期指净持仓在市场过热时压低 A 股仓位上限。", "description_en": "Caps A-share exposure when IC futures positioning is overheated."},
    {"strategy_id": "overseas_market_sentiment", "name_zh": "外围市场情绪", "name_en": "Overseas Market Sentiment", "category_zh": "市场情绪", "category_en": "Market Sentiment", "description_zh": "将美股和韩股板块表现映射为 A 股行业信号。", "description_en": "Maps US and Korean sector moves to A-share sector signals."},
    {"strategy_id": "lhb_follow_star_seats", "name_zh": "龙虎榜明星席位跟随", "name_en": "LHB Star Seat Follow", "category_zh": "事件量化", "category_en": "Event Quantitative", "description_zh": "跟随满足金额门槛的高胜率明星席位。", "description_en": "Follows high-win-rate star seats above an amount threshold."},
    {"strategy_id": "lhb_reverse_institutional", "name_zh": "龙虎榜机构反向", "name_en": "LHB Institutional Reversal", "category_zh": "事件量化", "category_en": "Event Quantitative", "description_zh": "机构集中卖出且集合竞价低开时，生成反向观察买入信号。", "description_en": "Generates a reversal signal after institutional selling and a gap down."},
    {"strategy_id": "lhb_seat_profile", "name_zh": "龙虎榜席位画像", "name_en": "LHB Seat Profile", "category_zh": "事件量化", "category_en": "Event Quantitative", "description_zh": "使用席位历史 T+3 胜率和样本量筛选跟随对象。", "description_en": "Selects seats from T+3 win rates and sample size."},
    {"strategy_id": "lhb_consensus", "name_zh": "龙虎榜游资机构共振", "name_en": "LHB Consensus", "category_zh": "事件量化", "category_en": "Event Quantitative", "description_zh": "识别明星游资与机构同时净买入。", "description_en": "Detects concurrent star-seat and institutional buying."},
    {"strategy_id": "lhb_quant_sector", "name_zh": "龙虎榜量化席位板块", "name_en": "LHB Quant Sector", "category_zh": "事件量化", "category_en": "Event Quantitative", "description_zh": "识别量化席位对同一行业的集中买入。", "description_en": "Detects concentrated quant-seat buying in one sector."},
)


def strategy_definitions() -> list[dict[str, str]]:
    return [dict(item) for item in STRATEGY_DEFINITIONS]
