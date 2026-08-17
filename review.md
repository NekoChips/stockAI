# 代码审查报告

## 结果

未发现阻塞问题。

## 已审查重点

- 没有真实券商接入或实盘下单代码，订单仅由 `PaperBroker` 在本地模拟成交。
- 数据过期会在风控层被拒绝，不能生成新的模拟订单。
- 固定交易宇宙只允许已配置的沪深 ETF：`588170.SH`、`588200.SH`。
- 默认行情源已切换为 AKShare，provider factory 支持通过配置切换到必盈、东方财富或后续新增数据源。
- AKShare 未安装时会给出中文安装提示；必盈 API licence 不写死在代码中，仍可通过环境变量或配置提供。
- SQLite 仅通过 `MarketDataStore` 仓储接口暴露给应用层，策略和风控不依赖 SQLite 细节。
- 历史 K 线以 `(symbol, interval, timestamp)` 唯一键 upsert，重复同步不会产生重复行。
- 单一技术指标或单一量化策略不会直接下单，所有策略先聚合，再经过风控。
- 学习模块的策略调整建议默认状态为 `待人工确认`。
- Markdown 日报为中文输出。

## 验证

- 命令：`PYTHONPATH=src python3 -m unittest discover -s tests`
- 结果：56 个测试全部通过。

## 剩余风险

- 当前环境尚未安装 AKShare；已用 fixture 覆盖解析和缺依赖错误路径，但未真实联网验证 AKShare。
- 必盈 API fallback 需要有效 licence；当前已用 fixture 覆盖解析和配置错误路径。
- 东方财富公开适配器仍保留为 fallback，但公开网页端点可能出现远端断连或字段变化。
- 第一版回放框架是轻量模型，未实现完整盘口撮合、停牌、涨跌停无法成交等复杂情形。
- 当前仅历史 K 线写入 SQLite；实时行情、信号、订单和成交仍主要停留在内存和 Markdown 报告中。
