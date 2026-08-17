# A股沪深模拟盘 AI-Agent 第一版完成报告

## 已实现

- 默认配置：100 万人民币模拟资金，固定 ETF 池 `588170.SH`、`588200.SH`。
- 数据层：默认使用 AKShare 适配器，支持实时 ETF/股票行情解析、历史 K 线解析、缺依赖中文安装提示；必盈 API 与东方财富公开适配器保留为可选 fallback。
- 动态切换：新增 provider factory，可通过 `config/default.yaml` 中的 `data.provider` 与 `data.history_provider` 切换行情源。
- 持久化：SQLite `MarketDataStore`，按 `(symbol, interval, timestamp)` upsert 保存 K 线，接口兼容未来 MySQL/PostgreSQL 实现。
- 市场范围：只允许沪深 `SH/SZ` 股票与 ETF，拒绝非固定池标的。
- 技术指标：SMA、EMA、MACD、RSI、布林带、ATR、成交量比率、VWAP、日内位置。
- 策略层：多指标综合策略、时间序列动量、均值回归、双 ETF 相对强弱、波动率目标仓位、回撤止损/再入场。
- 聚合器：多策略投票、权重和风险惩罚，冲突时保守处理。
- 风控层：数据过期、固定标的、最大仓位、现金下限、100 股/份整数倍、T+1 可卖数量、单日交易次数。
- 模拟盘：本地现金、持仓、成本、可卖数量、手续费、滑点、已实现/未实现盈亏。
- 日报：生成本地中文 Markdown 日报。
- 学习：按策略贡献生成中文总结，参数建议默认为 `待人工确认`。

## 如何验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

本轮结果：56 个测试全部通过。

## 如何生成收盘日报

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app post-close --reports reports
```

已生成样例：`reports/daily_reports.md`

## 如何同步历史 K 线

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app sync-history
```

默认写入：`data/stock_ai_agent.sqlite3`

使用 AKShare 前需要安装依赖：

```bash
python3 -m pip install akshare
```

此前使用东方财富适配器已真实同步成功：

- `588170.SH`：332 条历史 K 线。
- `588200.SH`：635 条历史 K 线。

## 已知限制

- 当前环境尚未安装 AKShare；已完成 fixture 测试和动态 provider 切换，未在本轮真实联网验证 AKShare。
- 必盈 API 仍可作为 fallback，但需要有效 licence。
- 东方财富公开适配器保留为 fallback，但公开网页端点仍可能出现远端断连或字段变化。
- 当前只持久化历史 K 线，后续建议继续持久化实时行情、信号、订单、成交和日报索引。
- MySQL/PostgreSQL 尚未实现具体适配器，但已有 `MarketDataStore` 接口隔离存储细节。
- 本项目仅用于模拟盘研究，不构成投资建议，也不连接实盘交易。
