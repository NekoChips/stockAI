from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List

from .backtest import BacktestResult
from .models import LearningProposal


def summarize_learning(strategy_contributions: Dict[str, Decimal], backtest: BacktestResult | None = None) -> str:
    lines = ["# 策略学习总结", ""]
    if backtest:
        lines.append(f"- 回放收益率：{backtest.total_return:.2%}")
        lines.append(f"- 最大回撤：{backtest.max_drawdown:.2%}")
        lines.append(f"- 胜率：{backtest.win_rate:.2%}")
        lines.append(f"- 盈亏比：{backtest.profit_loss_ratio:.2f}")
    for strategy, contribution in strategy_contributions.items():
        direction = "正贡献" if contribution > 0 else "负贡献" if contribution < 0 else "中性"
        lines.append(f"- {strategy}：{direction}，贡献 {contribution:.2%}")
    return "\n".join(lines)


def propose_parameter_changes(strategy_contributions: Dict[str, Decimal], backtest: BacktestResult) -> List[LearningProposal]:
    proposals: List[LearningProposal] = []
    for strategy, contribution in strategy_contributions.items():
        if contribution < 0:
            proposals.append(
                LearningProposal(
                    strategy_id=strategy,
                    suggestion="建议降低该策略权重或延长冷却期，需人工确认后启用。",
                    evidence=[
                        f"最近回放贡献为 {contribution:.2%}",
                        f"组合最大回撤为 {backtest.max_drawdown:.2%}",
                    ],
                )
            )
    if not proposals:
        proposals.append(
            LearningProposal(
                strategy_id="portfolio",
                suggestion="当前策略组合暂不需要调整，继续观察样本外表现。",
                evidence=["回放中未发现明显负贡献策略。"],
            )
        )
    return proposals
