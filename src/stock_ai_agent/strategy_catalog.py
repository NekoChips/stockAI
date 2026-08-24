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
    {
        "strategy_id": "futures_sentiment",
        "name_zh": "期货情绪",
        "name_en": "Futures Sentiment",
        "category_zh": "市场情绪",
        "category_en": "Market Sentiment",
        "description_zh": "使用 IF、IC、IM 期货走势和基差情绪辅助仓位判断。",
        "description_en": "Uses IF, IC, and IM futures trends and basis sentiment as an allocation factor.",
    },
    {
        "strategy_id": "overseas_sentiment",
        "name_zh": "海外市场情绪",
        "name_en": "Overseas Sentiment",
        "category_zh": "市场情绪",
        "category_en": "Market Sentiment",
        "description_zh": "使用美股和韩股收盘数据辅助 A 股风险偏好判断。",
        "description_en": "Uses US and Korean market closes as an A-share risk appetite factor.",
    },
    {
        "strategy_id": "lhb_follow",
        "name_zh": "龙虎榜跟随",
        "name_en": "LHB Follow",
        "category_zh": "事件量化",
        "category_en": "Event Quantitative",
        "description_zh": "根据机构和明星席位的龙虎榜行为生成股票候选信号。",
        "description_en": "Generates stock candidates from institutional and star-seat LHB activity.",
    },
    {
        "strategy_id": "quant_sector_rotation",
        "name_zh": "量化行业轮动",
        "name_en": "Quantitative Sector Rotation",
        "category_zh": "量化策略",
        "category_en": "Quantitative",
        "description_zh": "综合行业收益、换手、机构买入和上涨比例判断行业强弱。",
        "description_en": "Ranks sectors using returns, turnover, institutional buying, and breadth.",
    },
)


def strategy_definitions() -> list[dict[str, str]]:
    return [dict(item) for item in STRATEGY_DEFINITIONS]
