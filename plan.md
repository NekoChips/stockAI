# A股沪深模拟盘 AI-Agent 实施计划

## 1. 当前决策

- 语言与运行方式：Python，本地命令行 MVP。
- 数据源：默认使用 AKShare；必盈 API 和东方财富公开适配器保留为可选 fallback。
- 市场范围：仅沪深 A 股股票与沪深交易所 ETF。
- 初始资金：人民币 1,000,000 元。
- 初始标的：`588170.SH`、`588200.SH`。
- 输出语言：全部用户可见内容中文化。
- 日报形式：本地 Markdown。
- 策略升级：必须人工确认。
- 操作策略：多指标综合评分，包含均线/EMA、MACD、RSI、布林带、ATR、成交量比率和可选 VWAP。
- 量化策略库：时间序列动量、均值回归、双 ETF 相对强弱轮动、波动率目标仓位、回撤止损/再入场。

## 2. 目标目录

- `/Users/neko/Documents/ChatGPT/codex-stockAI/pyproject.toml`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/config/default.yaml`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/__init__.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/config.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/models.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/universe.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/eastmoney.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/akshare_provider.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/biying.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/providers.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/features.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/strategy.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/quant_strategies.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/backtest.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/risk.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/paper_broker.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/journal.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/learning.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/app.py`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/tests/`
- `/Users/neko/Documents/ChatGPT/codex-stockAI/reports/`

## 3. 测试策略

严格按 Red-Green-Refactor 做。每个功能先写失败测试，再写最小实现，再整理命名和边界。第一版优先使用 Python 标准库，减少依赖安装风险；当前本机没有 `pytest`，因此已使用标准库 `unittest` 验证，命令为 `PYTHONPATH=src python3 -m unittest discover -s tests`。

## 4. 任务拆解

### 任务 1：项目骨架

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_config.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/pyproject.toml`、`/Users/neko/Documents/ChatGPT/codex-stockAI/config/default.yaml`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/config.py`
- 先写测试：验证默认资金为 `1000000`，标的为 `588170.SH` 与 `588200.SH`，默认数据源为 `biying`，策略权重包含趋势、动能、波动、成交量和风险惩罚。
- 最小实现：读取 YAML 配置；如果没有 PyYAML，则提供简单配置加载或改用 JSON/TOML。
- 验证：运行 `python -m pytest tests/test_config.py`。

### 任务 2：领域模型

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_models.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/models.py`
- 先写测试：验证行情、信号、订单、成交、持仓、组合快照可以创建，并且金额字段可计算。
- 最小实现：使用 `dataclasses` 和 `Decimal` 定义核心对象。
- 验证：运行 `python -m pytest tests/test_models.py`。

### 任务 3：沪深市场范围过滤

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_universe.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/universe.py`
- 先写测试：接受 `588170.SH`、`588200.SH`、`600519.SH`、`000001.SZ`；拒绝港股、美股、无后缀代码、B 股、非配置标的。
- 最小实现：实现代码规范化、交易所识别、固定交易宇宙校验。
- 验证：运行 `python -m pytest tests/test_universe.py`。

### 任务 4：可配置行情 provider 与 AKShare 适配器

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_akshare_adapter.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_biying_adapter.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_provider_factory.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_eastmoney_adapter.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/akshare_provider.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/biying.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/providers.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/eastmoney.py`
- 先写测试：使用本地 fixture 模拟 AKShare 实时行情与历史 K 线表格，验证能解析最新价、开高低昨收、涨跌幅、成交量、成交额、时间戳和数据源；验证缺少 AKShare 依赖时输出中文安装提示；验证 provider factory 可按配置创建 AKShare、必盈或东方财富适配器。
- 最小实现：默认 provider 使用 AKShare；ETF 实时行情走 `fund_etf_spot_em()`，A 股股票走 `stock_zh_a_spot_em()`；历史 K 线默认走 `fund_etf_hist_em()` 或 `stock_zh_a_hist()`；必盈和东方财富适配器保留为 fallback。
- 验证：先跑 fixture 单测；再可选手动运行一次真实行情拉取。

### 任务 5：行情新鲜度检查

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_data_freshness.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/eastmoney.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/models.py`
- 先写测试：新鲜行情允许分析；过期行情阻止模拟下单；错误消息为中文。
- 最小实现：在行情模型上增加 `is_fresh` 或 freshness 字段。
- 验证：运行对应测试。

### 任务 6：特征计算

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_features.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/features.py`
- 先写测试：验证 SMA、EMA、MACD、RSI、布林带、ATR、成交量比率、日内位置和可选 VWAP 可确定性计算。
- 最小实现：基于当前行情、分钟线和日线计算第一版技术指标；指标不足时返回中文缺失原因，而不是伪造信号。
- 验证：运行 `python -m pytest tests/test_features.py`。

### 任务 7：策略接口与多指标综合策略

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_strategy.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/strategy.py`
- 先写测试：所有策略实现统一接口，输出 `strategy_id`、方向、分数、目标仓位、证据、反对因素和中文解释；趋势、MACD、RSI、布林带、ATR 和成交量共同确认时输出买入；已有仓位且评分提高时输出加仓；过热、动能衰减或跌破趋势时输出减仓；多指标转弱时输出清仓；弱势或数据不足时输出持有/观望。
- 最小实现：定义策略接口和信号协议；实现“市场状态识别 + 多指标评分 + 分层目标仓位”的保守策略。评分维度包括趋势分、动能分、波动分、成交量确认分和风险惩罚分，输出目标仓位档位 `0%`、`20%`、`40%`、`60%`。
- 验证：运行 `python -m pytest tests/test_strategy.py`。

### 任务 8：量化策略库

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_quant_strategies.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/quant_strategies.py`
- 先写测试：时间序列动量在 N 日收益为正且回撤可控时给正分；均值回归在价格低于布林中轨且 z-score 过低时给低吸分；双 ETF 相对强弱轮动在 `588170.SH` 强于 `588200.SH` 时偏向前者；波动率目标仓位在 ATR 过高时降低仓位；回撤止损策略在回撤触发后输出降仓或清仓；所有解释为中文。
- 最小实现：实现五个可开关量化策略，每个策略只输出信号和证据，不直接生成订单。
- 验证：运行 `python -m pytest tests/test_quant_strategies.py`。

### 任务 9：策略聚合器

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_strategy_aggregator.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/strategy.py`
- 先写测试：多个策略一致时提高置信度；策略冲突时降低目标仓位或观望；风险惩罚策略只能降权不能加仓；聚合结果保留支持和反对证据。
- 最小实现：实现“投票 + 权重 + 风险惩罚”的聚合器，输出统一决策信号。
- 验证：运行 `python -m pytest tests/test_strategy_aggregator.py`。

### 任务 10：策略回放验证

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_backtest.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/backtest.py`
- 先写测试：给定历史价格序列和策略参数，回放输出收益率、最大回撤、胜率、盈亏比、换手率、最大连续亏损和每个策略贡献。
- 最小实现：实现轻量回放框架，供学习模块验证参数建议；第一版不做复杂撮合，只复用模拟盘的手续费和滑点假设。
- 验证：运行 `python -m pytest tests/test_backtest.py`。

### 任务 11：风控层

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_risk.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/risk.py`
- 先写测试：覆盖单标的最大仓位、总仓位、现金下限、100 股/份整数倍、数据过期、非固定标的、T+1 可卖数量，以及 ATR 过高导致目标仓位下调。
- 最小实现：策略信号转订单前逐条检查，输出通过/拒绝和中文原因；风险层可以降低仓位，但不能放大策略目标仓位。
- 验证：运行 `python -m pytest tests/test_risk.py`。

### 任务 12：模拟盘成交与持仓

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_paper_broker.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/paper_broker.py`
- 先写测试：覆盖建仓、加仓、减仓、清仓、现金不足、可卖数量不足、手续费和滑点。
- 最小实现：维护现金、持仓、成本、已实现盈亏、浮动盈亏和订单记录。
- 验证：运行 `python -m pytest tests/test_paper_broker.py`。

### 任务 13：Markdown 日报

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_journal.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/journal.py`
- 先写测试：有交易和无交易两种日报都包含中文标题、账户概览、当前持仓、今日操作、技术指标证据、量化策略证据、执行逻辑、风控拒绝和明日关注。
- 最小实现：生成并维护统一文件 `reports/daily_reports.md`，每个交易日用日期标题分段；同日重复生成时替换同日段落，不重复追加。每笔操作解释至少列出趋势、MACD、RSI、布林带/ATR、成交量、时间序列动量、均值回归、相对强弱、波动率目标中的关键证据。
- 验证：运行测试并检查生成的 Markdown。

### 任务 14：自我学习建议

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_learning.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/learning.py`
- 先写测试：根据交易结果生成中文学习总结；能按指标组合和量化策略组合统计后续表现；策略参数建议状态默认为 `待人工确认`；未通过回放验证的建议不得启用。
- 最小实现：统计胜率、盈亏比、回撤、错误类型、指标贡献、量化策略贡献和信号后 N 日表现，并输出不自动启用的阈值或权重调整建议。
- 验证：运行 `python -m pytest tests/test_learning.py`。

### 任务 15：命令行主流程

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_app.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/app.py`
- 先写测试：使用 mock 行情跑完整流程，生成模拟决策和 Markdown 日报。
- 最小实现：提供 `run-once` 和 `post-close` 两个入口。
- 验证：运行 `python -m pytest tests/test_app.py`，再运行本地命令生成一次示例日报。

### 任务 16：全量验证与代码审查

- 输出文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/review.md`
- 验证步骤：运行全量测试、检查中文输出、检查非沪深标的拒绝、检查没有真实下单代码。
- 审查重点：风控是否可绕过、数据过期是否会下单、学习建议是否会自动启用、公开行情失败时是否可解释、是否存在单一技术指标或单一量化策略直接触发下单、回测指标是否考虑成本和滑点。

### 任务 17：完成报告

- 输出文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/final_report.md`
- 内容：已实现功能、测试结果、已知限制、如何运行、后续建议。
- 完成条件：所有测试通过，并生成至少一份中文 Markdown 日报。

## 5. 人工检查点

开始写代码前需要确认本计划。后续还有三个检查点：

- 东方财富公开行情真实拉取成功后，确认字段质量是否够用。
- 第一份 Markdown 日报生成后，确认中文表达和栏目是否符合预期。
- 学习模块产生第一条策略调整建议后，确认人工审批流程是否足够清楚。

## 6. 下一步

当前计划已完成第一版 MVP 开发，并已补充真实历史 K 线拉取、SQLite 持久化和实时盯盘模拟。后续扩展任务如下：

### 任务 18：收益分析与资产快照

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_analytics.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_storage_sqlite.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/analytics.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/storage/sqlite.py`
- 验证：资产快照可持久化；每日、每周、每月、每年收益率可计算；盈亏日历可按日、月、年聚合。

### 任务 19：自动回测优化

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_backtest.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/backtest.py`
- 验证：参数网格回测能输出多个候选，最佳参数状态保持 `待人工确认`，并能保存到 SQLite。

### 任务 20：大盘指数对比

- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/config/default.yaml`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/akshare_provider.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/app.py`
- 验证：`sync-benchmarks` 能按配置同步上证指数、深证成指、沪深300、创业板指和科创50历史 K 线。

### 任务 21：Web 驾驶舱

- 测试文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/tests/test_web.py`
- 实现文件：`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/web.py`、`/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/app.py`
- 验证：`web` 命令启动本地页面；`/api/dashboard` 返回账户、持仓、收益、指数对比、盈亏排行榜、盈亏日历和回测记录。
