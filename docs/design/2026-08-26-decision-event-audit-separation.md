# 决策事件摘要与原始审计分离设计

**状态：** implemented
**负责人：** platform-and-backend
**创建日期：** 2026-08-26
**更新日期：** 2026-08-26
**关联：** [决策事件治理与摘要审计分离产品需求](../product/2026-08-26-decision-event-governance.md)

## 1. 设计结论

`decision_events` 保留为业务事件审计表，但不再承载每轮监控的重复快照，也不再作为日报主列表的直接数据源。

系统采用三层数据模型：

```text
decisions
  每个交易日、每个标的的一条最终策略摘要

decision_events
  有业务意义的策略、风控和订单状态变化

decision_audit_events（未来可选扩展）
  原始策略评估明细，短期保留，独立分页查询；当前不创建
```

当前阶段不保存每轮原始评估，不创建 `decision_audit_events`；没有业务状态变化的轮询结果直接丢弃。

## 2. 当前实现问题

当前写入链路在 [monitor.py](../../src/stock_ai_agent/monitor.py) 中每轮调用 `record_decision`；MySQL 实现在 [storage/mysql.py](../../src/stock_ai_agent/storage/mysql.py) 中会更新 `decisions`，但同时追加 `decision_events`。日报生成再将当天全部事件放入 `decision_timeline`。

现有 `compact_watch_decisions()` 只处理 `decisions`，无法治理事件表和已经写入 `daily_reports.report_data` 的重复轨迹。

## 3. 事件分类

### 3.1 策略事件

`phase = decision`，用于记录有意义的策略状态变化：

- 方向变化；
- 风控通过状态变化；
- 目标仓位变化；
- 策略组合或策略版本变化；
- 关键依据或约束发生变化。

连续相同的 `观望`、`持有` 和风控结论不写入新事件，只更新 `decisions` 的最终摘要。

### 3.2 订单事件

`phase = order`，用于记录订单状态机的状态转移：

- 已创建；
- 风控通过；
- 已提交；
- 部分成交；
- 已成交；
- 已拒绝；
- 已取消。

订单事件必须以订单状态实际变化为写入条件。重复调用 `save_order` 不能重复写入相同状态。

## 4. 数据模型调整

在现有表基础上增加事件幂等和追踪字段：

```sql
ALTER TABLE decision_events
  ADD COLUMN event_key VARCHAR(128) NOT NULL,
  ADD COLUMN position_quantity BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN position_weight DECIMAL(12,8) NOT NULL DEFAULT 0,
  ADD COLUMN position_state VARCHAR(16) NOT NULL DEFAULT 'unknown',
  ADD COLUMN monitor_round VARCHAR(64) NULL,
  ADD COLUMN created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ADD UNIQUE KEY uq_decision_event_key (event_key),
  ADD INDEX idx_decision_events_retention (phase, event_at);
```

字段职责：

| 字段 | 用途 |
| --- | --- |
| `event_key` | 防止重复写入，作为幂等键 |
| `position_quantity` | 事件发生前的持仓数量 |
| `position_weight` | 事件发生前的组合仓位比例 |
| `position_state` | 事件发生前是 `held`、`empty` 还是历史未知 |
| `monitor_round` | 关联一次 monitor 评估轮次，便于排查 |
| `phase` | 区分策略事件和订单事件 |
| `event_at` | 业务事件发生时间 |
| `created_at` | 数据落库时间，支持写入延迟排查 |

建议事件键：

- 策略事件：`trade_date:symbol:decision:state_fingerprint`；
- 订单事件：`order_id:status:filled_quantity`。

`state_fingerprint` 应由方向、批准结果、目标仓位、策略版本和规范化后的关键依据组成，不应包含每轮变化的时间戳。

## 5. 写入流程

### 5.1 策略评估

```text
读取当日 decisions 摘要
  ↓
计算本轮策略状态指纹
  ↓
与该标的最近一次 decision 事件比较
  ├─ 指纹相同：只更新 decisions 最终摘要，不写 decision_events
  └─ 指纹不同：更新摘要，并以 event_key 幂等写入业务事件
```

### 5.2 订单状态

```text
订单状态机产生新状态
  ↓
读取该订单最后状态
  ├─ 状态和已成交数量均相同：不写事件
  └─ 任一发生变化：写入一条 order 事件
```

订单主表继续保存当前状态，`decision_events` 只保存状态变化历史；`order_events` 如果继续保留，则两者必须明确职责，避免同一事件在两个页面重复展示。

## 6. 查询与接口设计

### 6.1 日报摘要接口

日报详情默认只返回：

- `decisions`：每标的每日最终摘要；
- `fills`：当日模拟成交；
- `decision_timeline`：策略状态变化和订单状态变化的精选事件。

不得默认把当天全部原始轮询记录放入 `decision_timeline`。

### 6.2 原始审计接口

建议增加独立接口：

```text
GET /api/dashboard/reports/{date}/audit-events
```

查询参数：

- `symbol`：标的过滤；
- `phase`：`decision` 或 `order`；
- `start_at`、`end_at`：时间范围；
- `limit`：单页数量，上限 100；
- `cursor`：游标分页。

接口默认按 `event_at DESC, id DESC` 返回，并返回 `next_cursor`。不得使用无上限的全量查询。

## 7. 日报数据迁移

历史迁移必须按以下顺序执行：

1. 备份 `decision_events` 和 `daily_reports`；
2. 以 `trade_date + symbol` 分组，保留最新策略摘要；
3. 从订单主表和订单状态事件重建真实执行轨迹；
4. 重写 `daily_reports.report_data.decision_timeline`，只保留摘要事件和真实订单状态变化；
5. 校验每个交易日每个标的最多一条策略摘要；
6. 分批删除超过保留期限的原始策略事件；
7. 记录迁移前后行数、日报数量、重复数量和异常数量。

迁移脚本不能直接依赖 shell 命令在 MySQL 客户端中执行。备份命令、SQL 文件和验证 SQL 应分别放在 `docs/operations/`，并明确执行环境。

## 8. 保留与清理

| 数据 | 默认保留 | 清理方式 |
| --- | ---: | --- |
| `decision_events` 中的策略事件 | 30 天 | 按 `phase + event_at` 分批删除 |
| `decision_events` 中的订单事件 | 2 年 | 到期后归档或分批删除 |
| `decision_audit_events` 原始评估 | 7 至 30 天 | 按日期分批删除 |
| `decisions` 每日摘要 | 长期 | 不自动删除 |
| `daily_reports` 日报摘要 | 长期 | 不自动删除 |
| `market_quote_events` | 7 天 | 沿用现有清理任务 |

清理任务需要保存：任务时间、阶段、截止时间、删除数量、失败原因和耗时。删除操作使用批量大小限制，避免长事务锁表。当前实现通过 monitor 的首次历史压缩和每日维护执行；未新增原始评估表。

## 9. 页面设计

日报主视图：

- 标题使用“策略与执行轨迹”；
- 默认按标的合并策略摘要；
- “观望”默认折叠或只显示一条；
- 订单状态使用中文业务文案；
- 显示策略依据和风控约束，不显示内部字段名。

审计视图：

- 独立页面或抽屉；
- 支持阶段、标的和时间筛选；
- 分页或虚拟滚动；
- 明确提示“原始评估记录不等同于实际交易次数”。

## 10. 索引与性能

必须具备：

- `decision_events (phase, event_at)`：支持分阶段清理；
- `decision_events (trade_date, symbol, event_at)`：支持日报和标的查询；
- `decision_events (order_id, event_at)`：支持订单轨迹查询；
- `decisions (trade_date, symbol)`：支持每日摘要读取。

日报接口和审计接口禁止共享无条件全表查询。所有列表接口必须有数量上限；审计接口使用游标分页，日报接口只读取摘要数据。

## 11. 兼容与验证

- Mock 存储和 MySQL 存储必须保持相同的去重和事件语义。
- 连续相同观望至少运行 100 轮，验证业务事件数量不增长。
- 同一订单重复保存相同状态，验证只产生一条订单事件。
- 状态变化后，验证新增一条事件且日报显示最新摘要。
- 历史日报迁移后，验证页面不再出现同标的重复摘要。
- 清理任务执行后，验证订单事件和日报摘要未被误删。
- 审计接口验证 `limit`、`cursor`、阶段筛选和标的筛选。

## 12. 实施顺序

1. 先实现事件分类、状态指纹和幂等写入；
2. 再切换日报为摘要数据源；
3. 增加审计接口和前端分页视图；
4. 增加清理任务、监控指标和索引；
5. 最后执行历史日报和历史事件迁移。
