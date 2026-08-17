from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List

from .models import Decision, Fill, Portfolio


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def generate_daily_report(
    report_date: date,
    portfolio: Portfolio,
    decisions: Iterable[Decision],
    fills: Iterable[Fill],
    output_dir: str | Path = "reports",
    filename: str = "daily_reports.md",
) -> Path:
    decisions = list(decisions)
    fills = list(fills)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / filename
    heading = f"# {report_date.isoformat()} A股模拟盘日报"

    lines: List[str] = [
        heading,
        "",
        "## 账户概览",
        "",
        f"- 总资产：{money(portfolio.total_asset())} 元",
        f"- 现金：{money(portfolio.cash)} 元",
        f"- 总持仓市值：{money(portfolio.total_market_value())} 元",
        "",
        "## 当前持仓",
        "",
    ]
    if portfolio.positions:
        for symbol, position in portfolio.positions.items():
            lines.append(
                f"- {symbol}：数量 {position.quantity}，可卖 {position.available_quantity}，成本 {position.average_cost}，市值 {money(position.market_value)} 元，仓位 {portfolio.position_weight(symbol):.2%}，浮盈浮亏 {money(position.unrealized_pnl)} 元"
            )
    else:
        lines.append("- 当前无持仓。")

    lines.extend(["", "## 今日操作", ""])
    if fills:
        for fill in fills:
            lines.append(f"- {fill.direction.value} {fill.symbol} {fill.quantity} 份，成交价 {fill.price}，手续费 {fill.fee} 元。")
    else:
        lines.append("- 今日无模拟成交。")

    lines.extend(["", "## 执行逻辑与策略证据", ""])
    if decisions:
        for decision in decisions:
            status = "通过" if decision.approved else "拒绝"
            lines.append(f"- {decision.symbol}：{decision.direction.value}，风控{status}，目标仓位 {decision.target_weight:.0%}。")
            if decision.source_signal:
                lines.append(f"  - 技术/量化解释：{decision.source_signal.explanation}")
                for item in decision.source_signal.evidence[:5]:
                    lines.append(f"  - 支持证据：{item}")
                for item in decision.source_signal.objections[:5]:
                    lines.append(f"  - 反对因素：{item}")
            for reason in decision.reasons:
                lines.append(f"  - 风控说明：{reason}")
    else:
        lines.append("- 今日没有策略决策。")

    lines.extend(["", "## 明日关注", "", "- 继续观察固定 ETF 池的趋势、动量、波动率、成交量和相对强弱变化。"])
    section = "\n".join(lines) + "\n"
    path.write_text(_replace_or_append_section(path, heading, section), encoding="utf-8")
    return path


def _replace_or_append_section(path: Path, heading: str, section: str) -> str:
    if not path.exists():
        return section
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line == heading:
            start = index
            break
    if start is None:
        return content.rstrip() + "\n\n" + section
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("# ") and lines[index].endswith("A股模拟盘日报"):
            end = index
            break
    replacement = section.rstrip().splitlines()
    new_lines = lines[:start] + replacement + lines[end:]
    return "\n".join(new_lines).rstrip() + "\n"
