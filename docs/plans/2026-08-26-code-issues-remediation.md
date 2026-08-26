# 代码问题整改与策略闭环实施方案

## 1. 文档目的

本文档基于 [`2026-08-25-code-issues-review.md`](../reviews/2026-08-25-code-issues-review.md) 对当前 `codex-neko` 分支的复核结果编写，用于指导后续实现、测试和验收。

本文档已经纳入以下产品决策：

1. 龙虎榜接口无法提供席位明细时，直接禁用依赖席位明细的策略。
2. 标的板块数据缺失时，使用“综合”作为默认板块。
3. 不再因为全局有效策略权重低于 60% 而直接禁止全部交易。

本轮只描述业务代码、数据库和页面功能改造，不包含服务拆分、部署、备份和数据库迁移执行工作。

## 2. 当前代码复核结论

### 2.1 文档中已经过时的问题

以下问题在当前代码中已经修复，或原始文件路径已经不存在，不应直接照搬原整改方案：

- 标的代码规范化返回整数。
- `aggregator` 配置层级错误。
- ETF 没有波动率目标和回撤控制策略。
- `trading_enabled` 完全没有生效。
- 量化板块策略权重为零。
- 运行 monitor 时量化席位表一定为空。
- 系统没有回测模块。

这些项目需要保留回归测试，但不应重复开发。

### 2.2 当前仍需整改的问题

| 优先级 | 问题 | 影响 |
| --- | --- | --- |
| P0 | 龙虎榜只同步汇总数据，没有买卖席位明细 | 席位跟随、席位画像、量化席位策略无法产生有效信号 |
| P0 | 板块映射表没有完整同步入口 | 海外情绪和量化行业策略长期回退为“综合”或无法判断 |
| P1 | 外部数据任务共用异常边界 | 一个数据源失败会影响同一时段的其他同步任务 |
| P1 | 美股逐标的同步缺少部分成功机制 | 单个 Yahoo 标的失败可能导致整批数据不可用 |
| P1 | 全局 60% 有效权重规则过于粗糙 | 新标的可能因可选数据暂缺而长期无法交易 |
| P1 | 缺少真实适配器契约测试 | AKShare/Yahoo 字段变化可能在生产环境才暴露 |
| P2 | `trading_enabled` 主要由 monitor 过滤 | 其他调用路径缺少风险层二次防护 |
| P2 | 量化席位默认数据依赖 monitor 启动写入 | 仅启动 Web 或执行迁移时可能没有基础席位数据 |
| P2 | 分数归一化规则缺少参数影响说明 | 阈值调整后的策略行为不可解释、不可稳定回测 |

## 3. 目标策略数据规则

### 3.1 数据可用性分类

每个策略在每个标的、每个 monitor 轮次输出统一的数据状态：

```text
READY       数据完整，可以输出信号
UNAVAILABLE 数据缺失或过期，本策略本轮不参与聚合
INVALID     数据格式错误或违反业务规则，本策略本轮失效
NEUTRAL     数据完整，但信号为中性
```

禁止通过伪造 0 分、空席位或默认行情来掩盖 `UNAVAILABLE` 和 `INVALID`。

### 3.2 不同数据源的处理规则

| 数据 | 缺失或过期时的处理 |
| --- | --- |
| 实时行情 | 当前标的本轮禁止模拟成交 |
| 日 K 线 | 技术、动量、均值回归等依赖策略失效 |
| 期货情绪 | 仅期货情绪策略失效 |
| 海外指数 | 仅海外市场情绪策略失效 |
| 龙虎榜汇总 | 仅汇总字段策略可使用，席位策略失效 |
| 龙虎榜席位明细 | 席位跟随、席位画像、量化席位策略失效 |
| 板块映射 | 使用“综合”板块继续计算，但记录降级状态 |
| 风控数据 | 风控不通过时禁止对应交易 |

### 3.3 聚合规则

1. 只聚合状态为 `READY` 或 `NEUTRAL` 的策略。
2. `UNAVAILABLE` 和 `INVALID` 策略不参与权重分母，也不伪造中性信号。
3. 剩余有效策略权重重新归一化。
4. 不再使用“有效权重低于配置总权重 60%”作为全局禁止交易条件。
5. 所有策略均不可用时，输出 `WATCH`，不得交易。
6. 实时行情失效、风控失败、订单状态不允许时，即使聚合方向为买入，也不得成交。
7. 聚合结果必须记录有效策略列表、失效策略列表、归一化前后权重和降级原因。

这样可以实现：缺少龙虎榜时仍允许技术策略正常运行，但不会让龙虎榜策略在没有数据时伪造信号。

## 4. 具体改造清单

### 4.1 P0：龙虎榜席位数据链路

涉及文件：

- `src/stock_ai_agent/data/analysis_sources.py`
- `src/stock_ai_agent/quant_strategies.py`
- `src/stock_ai_agent/lhb_backtest.py`
- `src/stock_ai_agent/storage/base.py`
- `src/stock_ai_agent/storage/mysql.py`
- `src/stock_ai_agent/storage/mock.py`
- `migrations/003_strategy_execution_and_price_tracks.sql`

实施内容：

1. 在数据源层增加龙虎榜适配器，不让策略直接依赖 AKShare 原始列名。
2. 统一输出：交易日、标的、席位方向、席位名称、买入金额、卖出金额、净额、上榜原因、原始数据和来源。
3. 优先使用能返回买卖席位明细的接口；接口不可用时保留汇总记录，但明确 `seat_detail_available=false`。
4. `lhb_follow_star_seats`、`lhb_seat_profile`、`lhb_quant_sector` 在 `seat_detail_available=false` 时返回 `UNAVAILABLE`。
5. `lhb_reverse_institutional`、`lhb_consensus` 仅使用其实际需要的汇总字段。
6. 对同一交易日、同一标的、同一席位和方向做幂等写入。
7. 记录原始响应，便于排查接口字段变化。

验收：

- 有席位明细时，席位策略可以读取真实席位并生成证据。
- 只有汇总数据时，席位策略明确失效，不产生买入信号。
- 不同 AKShare 返回字段版本都能被标准化或明确失败。

### 4.2 P0：板块映射同步

涉及文件：

- `src/stock_ai_agent/reference_data.py`
- `src/stock_ai_agent/app.py`
- `src/stock_ai_agent/data/`
- `src/stock_ai_agent/storage/base.py`
- `src/stock_ai_agent/storage/mysql.py`
- `src/stock_ai_agent/storage/mock.py`

实施内容：

1. 增加板块数据源适配器和标准化模型。
2. 增加 CLI 命令 `sync-sectors`。
3. 支持全量同步、重复执行幂等、来源和同步时间记录。
4. 标的没有板块映射时，策略上下文使用 `综合`，同时写入降级证据。
5. 板块同步失败不能阻断实时行情、持仓估值和技术策略。
6. 新增标的进入观察池后进入低优先级板块补数队列。

验收：

- 执行 `sync-sectors` 后可查询指定标的板块。
- 没有映射的标的仍能运行核心技术策略。
- 海外情绪和量化行业策略能看到明确的板块名称和数据状态。

### 4.3 P1：外部任务故障隔离与状态记录

涉及文件：

- `src/stock_ai_agent/monitor.py`
- `src/stock_ai_agent/data/analysis_sources.py`
- `src/stock_ai_agent/storage/base.py`
- `src/stock_ai_agent/storage/mysql.py`
- `src/stock_ai_agent/storage/mock.py`

实施内容：

1. 将美股、韩股、龙虎榜、期货、日报和自动回测拆成独立任务。
2. 每个任务独立捕获异常、记录成功和失败，不得共用一个大异常块。
3. 美股同步按标的隔离异常，允许部分标的成功保存。
4. 为每个任务记录：任务名称、交易日、开始时间、结束时间、成功数量、失败数量、错误摘要和数据新鲜度。
5. 策略只读取满足最大允许延迟的数据。
6. 外部任务失败只使对应策略降级，不影响行情、模拟成交和其他独立策略。

### 4.4 P1：策略聚合器改造

涉及文件：

- `src/stock_ai_agent/strategy.py`
- `src/stock_ai_agent/strategy_runtime.py`
- `src/stock_ai_agent/models.py`
- `src/stock_ai_agent/monitor.py`

实施内容：

1. 为策略信号增加数据状态和降级原因。
2. 将“数据缺失”和“有效中性信号”分开。
3. 移除全局 60% 有效权重硬阻断。
4. 实现有效策略权重重新归一化。
5. 保留实时行情、风控、订单状态和账户约束的硬阻断。
6. 在决策记录、日报和 Web 策略详情中展示参与聚合和未参与聚合的策略。
7. 回测使用同一套聚合规则，避免线上和回测逻辑不一致。

### 4.5 P2：风险层二次校验

涉及文件：

- `src/stock_ai_agent/risk.py`
- `src/stock_ai_agent/monitor.py`
- `src/stock_ai_agent/paper_broker.py`

实施内容：

1. `trading_enabled=false` 的标的不允许买入或加仓。
2. 已持仓标的允许减仓、卖出和风控清仓。
3. 未启用标的的拒绝原因写入订单校验结果。
4. 增加绕过 monitor 直接调用风险层的测试。

### 4.6 P2：参考数据初始化

涉及文件：

- `src/stock_ai_agent/data/analysis_sources.py`
- `src/stock_ai_agent/storage/mysql.py`
- `src/stock_ai_agent/storage/mock.py`
- `migrations/003_strategy_execution_and_price_tracks.sql`

实施内容：

1. 增加幂等的参考席位初始化函数。
2. MySQL 初始化、Mock 初始化和独立同步命令使用同一套默认数据。
3. Web 页面显示量化席位数据是否已初始化。
4. 不覆盖人工禁用或修改过的席位配置。

### 4.7 P2：数据源契约测试与分数说明

涉及文件：

- `tests/test_external_strategies.py`
- `tests/test_strategy_runtime.py`
- 新增 `tests/test_data_adapter_contracts.py`
- 新增 `tests/fixtures/`

实施内容：

1. 为美股、韩股、龙虎榜、期货和板块数据保存脱敏样本。
2. 测试正常字段、空结果、字段改名、部分失败和日期异常。
3. 增加可选的在线冒烟测试，不纳入默认 CI。
4. 为分数归一化除数、阈值和裁剪范围增加参数化测试。
5. 在配置说明中解释归一化除数对策略阈值的影响。

## 5. 页面与接口改造

### 5.1 API

新增或扩展以下接口：

```text
GET  /api/data-health
GET  /api/strategy-readiness?symbol=...
GET  /api/sectors?symbol=...
POST /api/sectors/sync
GET  /api/lhb/records?date=...&symbol=...
GET  /api/lhb/records/{id}/raw
```

策略状态接口至少返回：

- 策略中文名和英文名。
- 当前状态：READY、UNAVAILABLE、INVALID、NEUTRAL。
- 数据来源和最后成功时间。
- 当前权重和归一化后权重。
- 失效原因。
- 是否允许产生交易信号。

### 5.2 Web 页面

在策略中心增加“数据就绪度”区域：

- 实时行情、日 K、期货、海外、龙虎榜、板块分别显示状态。
- 使用“可交易 / 降级 / 禁止交易”三种明确状态。
- 展示本轮参与聚合的策略和被排除的策略。
- 龙虎榜席位明细缺失时，明确提示“席位策略已禁用”，不能只显示空白。
- 板块缺失时显示“综合（默认板块）”，并展示数据降级提示。

## 6. 测试与验收顺序

1. 先补充数据模型和适配器契约测试。
2. 实现龙虎榜席位数据标准化。
3. 实现板块同步命令和存储。
4. 拆分 monitor 外部任务并补充失败隔离测试。
5. 改造策略聚合和风险二次校验。
6. 补充 API、页面和回测一致性测试。
7. 执行完整测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

核心验收场景：

- 龙虎榜只有汇总数据：汇总策略可运行，席位策略失效，不产生伪造买入信号。
- 板块数据缺失：使用“综合”，核心技术策略仍可运行。
- 美股一个标的接口失败：其他美股数据仍入库。
- 外部数据全部缺失：核心策略按自身数据状态运行；没有任何可用策略时保持观望。
- 未启用标的：禁止买入和加仓；已有持仓仍可减仓和清仓。
- 回测和 monitor 对同一数据集得到相同的策略聚合结果。

## 7. 发布前检查

- 数据库表结构已完成幂等初始化。
- 新增命令、API 和前端状态均有测试。
- 外部接口失败不会导致 monitor 进程退出。
- 不会把外部市场标的写入 A 股持仓、订单或收益统计。
- 现有策略配置和人工确认流程不被绕过。
- 157 个现有测试全部通过，并新增本方案覆盖的测试。

## 8. 暂不纳入本轮

- 服务容器拆分和部署方式调整。
- 数据备份和恢复机制。
- 多 monitor 实例协调。
- LLM 接入。
- 美股、韩股自身的交易和持仓能力。
