# StockAI 数据库数据字典

**状态：** active
**负责人：** platform-and-operations
**创建日期：** 2026-08-27
**更新日期：** 2026-08-27
**关联：** [行情数据表治理与 `bars` 淘汰实施方案](../plans/2026-08-27-market-data-table-governance.md)

## 1. 文档目的

本文档是 StockAI 当前 MySQL 业务表的查阅基线，用于：

- 运维人员理解表的职责、数据粒度、字段和索引；
- 排查数据同步、策略决策、订单成交和收益统计问题；
- 评估表之间的逻辑关联和数据保留策略；
- 约束后续数据库结构变更，避免新增重复表或遗漏同步文档。

本次拆分前的生产基线为 29 张 MySQL 表，其中包含计划淘汰的旧表 `bars`。当前代码已定义两个新目标表，因此新部署会创建 30 张业务表；已有生产库在完成迁移但尚未删除 `bars` 时会短暂存在 31 张表。最终应保留 30 张表。当前表之间没有声明式 `FOREIGN KEY`，关联主要由业务字段和代码约定维护，因此删除或修改字段前必须先检查调用方。

本文档描述的是当前实现基线，不代表生产库一定已经完成全部历史迁移。生产环境应结合“现状核对 SQL”确认实际字段、索引和迁移版本。

## 2. 数据库范围与通用约定

### 2.1 数据库范围

- 发布版使用 MySQL；连接信息通过环境变量或部署配置注入，不写入本文档。
- 本地开发验证使用 mock 数据，不以本地 SQLite 作为当前结构基线。
- 所有表默认使用 `utf8mb4`，金额、价格和数量使用 `DECIMAL` 或整数，不使用浮点字段保存核心财务事实。

### 2.2 通用字段约定

| 约定 | 含义 |
| --- | --- |
| `symbol` | 标的代码，通常带市场后缀，例如 `588170.SH`；代码本身不声明外键 |
| `trade_date` | 业务交易日；必须结合 `trading_calendar` 判断是否为目标市场交易日 |
| `timestamp_value` | K 线时间点 |
| `quoted_at` | 数据源报价时间 |
| `observed_at` | 系统观察/接收时间，用于去重、排序和限流审计 |
| `source` | 实际数据来源，例如 AlphaFeed、AKShare 或 market_quotes |
| `created_at` | 首次写入时间 |
| `updated_at` | 最近一次更新或覆盖时间 |
| `*_data`、`*_json`、`record_data` | JSON 文本或可扩展结构，读取时必须保留版本兼容能力 |
| `TINYINT` 布尔字段 | `0` 表示否，`1` 表示是 |

### 2.3 当前表分类

| 数据域 | 表 |
| --- | --- |
| 交易与组合 | `account_state`、`positions`、`orders`、`order_events`、`fills`、`portfolio_snapshots` |
| 决策与策略 | `decisions`、`decision_events`、`strategy_definitions`、`strategy_profiles`、`strategy_change_log`、`backtest_runs` |
| 行情与同步 | `bars`、`bar_price_tracks`、`index_price_tracks`、`intraday_bars`、`market_quotes`、`market_quote_events`、`data_sync_status` |
| 标的与观察池 | `watchlist_items`、`watchlist_exclusions`、`instrument_catalog`、`instrument_sector_mapping` |
| 报告与日历 | `daily_reports`、`trading_calendar` |
| 外部市场与事件 | `futures_positions`、`overseas_market_data`、`lhb_records`、`lhb_seat_profile`、`lhb_quant_seats` |
| 运行配置 | `metadata` |

## 3. 表结构、职责与索引

字段类型以当前 MySQL 建表语句为准；`NULL` 表示允许为空，未标记 `NULL` 的字段均为 `NOT NULL`。

### 3.1 `bars`（计划淘汰）

**职责：** 旧版通用 K 线表，历史上混存观察池日 K、指数日 K、分钟线，并提供旧版回退读取。新业务不得继续写入或读取；完成拆分和校验后删除。

**粒度：** 一个标的、一个周期、一个时间点一行。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `interval_name` | `VARCHAR(16)` | 周期，如 `daily`、`minute` |
| `timestamp_value` | `DATETIME(6)` | K 线时间点 |
| `open_price` | `DECIMAL(20,6)` | 开盘价 |
| `high_price` | `DECIMAL(20,6)` | 最高价 |
| `low_price` | `DECIMAL(20,6)` | 最低价 |
| `close_price` | `DECIMAL(20,6)` | 收盘价或该周期最新价 |
| `volume` | `DECIMAL(24,4)` | 成交量 |
| `amount` | `DECIMAL(24,4)` | 成交额 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `created_at` | `TIMESTAMP` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (symbol, interval_name, timestamp_value)`；无其他索引。

### 3.2 `account_state`

**职责：** 模拟账户的现金状态，当前通过固定账户标识保存纸面账户。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `VARCHAR(32)` | 账户标识，当前通常为 `paper` |
| `cash` | `DECIMAL(20,6)` | 可用现金 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (id)`。

### 3.3 `positions`

**职责：** 当前模拟持仓快照，每个标的一行。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `quantity` | `BIGINT` | 总持仓数量 |
| `available_quantity` | `BIGINT` | 可卖数量 |
| `average_cost` | `DECIMAL(20,6)` | 持仓平均成本 |
| `last_price` | `DECIMAL(20,6)` | 最近估值价格，使用不复权价格 |
| `realized_pnl` | `DECIMAL(20,6)` | 已实现盈亏 |
| `highest_price` | `DECIMAL(20,6)` | 持仓期间最高价，用于回撤控制 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (symbol)`；无其他索引。

### 3.4 `decisions`

**职责：** 每个交易日、每个标的的当前策略决策摘要；日报和看板读取的紧凑业务结果。通过唯一键避免同一标的同一交易日重复摘要。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 决策摘要 ID |
| `trade_date` | `DATE` | 决策所属交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `direction` | `VARCHAR(16)` | 决策方向，如买入、卖出、持有、观望 |
| `target_weight` | `DECIMAL(12,8)` | 目标仓位比例 |
| `approved` | `TINYINT` | 是否通过人工或风控确认 |
| `reasons` | `TEXT` | 聚合后的决策原因 |
| `signal_strategy_id` | `VARCHAR(128)` | 产生主要信号的策略 ID |
| `signal_score` | `DECIMAL(12,8)` | 信号评分 |
| `signal_confidence` | `DECIMAL(12,8)` | 信号置信度 |
| `signal_target_weight` | `DECIMAL(12,8)` | 信号建议目标仓位 |
| `signal_evidence` | `TEXT` | 信号证据摘要 |
| `signal_objections` | `TEXT` | 反对或限制因素摘要 |
| `signal_explanation` | `TEXT` | 可读的决策解释 |
| `signal_version` | `VARCHAR(64)` | 信号算法或规则版本 |
| `created_at` | `TIMESTAMP` | 创建时间 |

**索引：** `idx_decisions_trade_date (trade_date)`；唯一键 `uq_decisions_trade_date_symbol (trade_date, symbol)`；主键 `id`。

### 3.5 `market_quotes`

**职责：** 当前交易日的实时行情快照，保留当天不同观察时点，用于看板最新行情和后续分时聚合，不承担跨日历史存储。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 快照 ID |
| `trade_date` | `DATE` | 行情所属交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `name` | `VARCHAR(128)` | 标的名称 |
| `latest_price` | `DECIMAL(20,6)` | 最新价，不复权 |
| `change_percent` | `DECIMAL(12,6)` | 当日涨跌幅 |
| `previous_close` | `DECIMAL(20,6)` | 前收价 |
| `quoted_at` | `DATETIME(6)` | 数据源报价时间 |
| `observed_at` | `DATETIME(6)` | 系统接收时间 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 唯一键 `uq_market_quotes_tick (trade_date, symbol, observed_at)`；`idx_market_quotes_latest (symbol, trade_date, observed_at)`；主键 `id`。

### 3.6 `market_quote_events`

**职责：** 实时行情采集审计事件，用于排查主备切换、限流和数据异常；按既定策略保留 7 天。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 事件 ID |
| `trade_date` | `DATE` | 行情所属交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `name` | `VARCHAR(128)` | 标的名称 |
| `latest_price` | `DECIMAL(20,6)` | 最新价 |
| `change_percent` | `DECIMAL(12,6)` | 当日涨跌幅 |
| `previous_close` | `DECIMAL(20,6)` | 前收价 |
| `quoted_at` | `DATETIME(6)` | 数据源报价时间 |
| `observed_at` | `DATETIME(6)` | 系统观察时间 |
| `source` | `VARCHAR(64)` | 实际数据来源 |
| `created_at` | `TIMESTAMP` | 审计事件写入时间 |

**索引：** 唯一键 `uq_market_quote_events_tick (trade_date, symbol, observed_at)`；`idx_market_quote_events_retention (observed_at)`；`idx_market_quote_events_symbol (symbol, trade_date, observed_at)`；主键 `id`。

### 3.7 `fills`

**职责：** 模拟成交事实，一笔成交一行，是持仓、收益和订单成交数量计算的事实来源之一。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 成交 ID |
| `trade_date` | `DATE` | 成交交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `direction` | `VARCHAR(16)` | 买入或卖出方向 |
| `quantity` | `BIGINT` | 成交数量 |
| `price` | `DECIMAL(20,6)` | 成交价格，使用不复权价格 |
| `fee` | `DECIMAL(20,6)` | 交易费用 |
| `slippage` | `DECIMAL(20,6)` | 模拟滑点 |
| `order_id` | `VARCHAR(64)` NULL | 来源订单 ID |
| `timestamp_value` | `DATETIME(6)` | 成交发生时间 |
| `created_at` | `TIMESTAMP` | 记录创建时间 |

**索引：** `idx_fills_trade_date (trade_date)`；主键 `id`。`order_id` 当前没有单独索引。

### 3.8 `metadata`

**职责：** 兼容运行标记、同步日期和风险配置等通用键值数据。后续应使用命名空间，敏感信息不得写入。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | `VARCHAR(128)` | 配置或运行标识，主键 |
| `value` | `TEXT` | 配置值或 JSON 文本 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (key)`。

### 3.9 `watchlist_items`

**职责：** 当前观察池标的及其生命周期、是否允许交易的状态。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `name` | `VARCHAR(128)` | 标的名称 |
| `asset_type` | `VARCHAR(16)` | 资产类型，如股票或 ETF |
| `lifecycle_status` | `VARCHAR(24)` | 生命周期状态，如 observing、dormant |
| `trading_enabled` | `TINYINT` | 是否允许策略触发交易 |
| `dormant_since` | `DATE` NULL | 进入休眠状态的日期 |
| `created_at` | `TIMESTAMP` | 加入时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** `idx_watchlist_lifecycle (lifecycle_status, trading_enabled)`；主键 `symbol`。

### 3.10 `watchlist_exclusions`

**职责：** 删除观察池标的的墓碑记录，防止默认配置或同步任务重新加入已删除标的。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 被排除的标的代码 |
| `removed_at` | `TIMESTAMP` | 最近一次删除时间 |
| `created_at` | `TIMESTAMP` | 墓碑创建时间 |

**索引：** 主键 `PRIMARY KEY (symbol)`。

### 3.11 `instrument_catalog`

**职责：** 全市场股票和 ETF 的代码、名称、类型搜索目录，与当前观察池不同；按同步日期更新。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `name` | `VARCHAR(128)` | 标的名称 |
| `asset_type` | `VARCHAR(16)` | 资产类型 |
| `source` | `VARCHAR(64)` | 目录数据来源 |
| `synced_date` | `DATE` | 本条目录数据同步日期 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** `idx_instrument_catalog_name (name)`；主键 `symbol`。

### 3.12 `portfolio_snapshots`

**职责：** 每个交易日的组合资产快照，用于收益率、盈亏日历和基准比较。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `snapshot_date` | `DATE` | 快照日期 |
| `cash` | `DECIMAL(20,6)` | 现金 |
| `total_asset` | `DECIMAL(20,6)` | 组合总资产 |
| `total_market_value` | `DECIMAL(20,6)` | 持仓市值 |
| `created_at` | `TIMESTAMP` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (snapshot_date)`。

### 3.13 `backtest_runs`

**职责：** 回测任务和结果摘要，保存策略、参数、指标及人工确认/应用状态，不保存代码内容。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 回测记录 ID |
| `strategy_id` | `VARCHAR(128)` | 策略 ID |
| `strategy_profile_id` | `VARCHAR(128)` | 使用的策略组合配置 ID |
| `parameters` | `TEXT` | 回测参数 JSON |
| `metrics` | `TEXT` | 回测指标 JSON |
| `status` | `VARCHAR(32)` | 任务或审批状态 |
| `confirmed_at` | `DATETIME(6)` NULL | 人工确认时间 |
| `applied_at` | `DATETIME(6)` NULL | 应用到运行配置的时间 |
| `created_at` | `TIMESTAMP` | 创建时间 |

**索引：** `idx_backtest_status (status, created_at)`；`idx_backtest_profile (strategy_profile_id, status)`；主键 `id`。

### 3.14 `daily_reports`

**职责：** 只读日报归档，每个交易日一条，内容写入数据库而非 Markdown 文件。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `report_date` | `DATE` | 报告日期 |
| `status` | `VARCHAR(32)` | 报告状态 |
| `summary` | `TEXT` | 报告摘要 |
| `total_asset` | `DECIMAL(20,6)` | 报告时组合总资产 |
| `daily_pnl` | `DECIMAL(20,6)` | 当日盈亏 |
| `daily_return` | `DECIMAL(20,8)` | 当日收益率 |
| `report_data` | `LONGTEXT` | 完整报告 JSON |
| `created_at` | `TIMESTAMP` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (report_date)`。

### 3.15 `trading_calendar`

**职责：** 统一维护多个市场的交易日历；当前业务重点为 A 股，也可按 `market` 扩展其他市场。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | `VARCHAR(8)` | 市场标识，如 CN |
| `trade_date` | `DATE` | 日期 |
| `is_trading_day` | `TINYINT` | 是否交易日 |
| `source` | `VARCHAR(64)` | 日历来源 |
| `synced_at` | `TIMESTAMP` | 同步时间 |

**索引：** 主键 `PRIMARY KEY (market, trade_date)`；`idx_trading_calendar_flag (market, is_trading_day, trade_date)`。

### 3.16 `strategy_definitions`

**职责：** 策略目录和中英双语元数据，不保存某个标的的运行参数。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_id` | `VARCHAR(128)` | 策略唯一 ID |
| `name_zh` | `VARCHAR(128)` | 中文名称 |
| `name_en` | `VARCHAR(128)` | 英文名称 |
| `category_zh` | `VARCHAR(64)` | 中文分类 |
| `category_en` | `VARCHAR(64)` | 英文分类 |
| `description_zh` | `TEXT` | 中文说明 |
| `description_en` | `TEXT` | 英文说明 |
| `enabled` | `TINYINT` | 是否启用 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (strategy_id)`；无其他索引。

### 3.17 `strategy_profiles`

**职责：** 策略组合、适用范围、参数版本和“保存草稿 → 人工确认 → 下一轮 monitor 生效”状态。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `profile_id` | `VARCHAR(128)` | 配置组合 ID |
| `name_zh` | `VARCHAR(128)` | 中文名称 |
| `name_en` | `VARCHAR(128)` | 英文名称 |
| `scope_type` | `VARCHAR(32)` | 作用域类型 |
| `scope_value` | `VARCHAR(128)` | 作用域值，如标的或资产类型 |
| `status` | `VARCHAR(32)` | 配置状态 |
| `revision` | `INT` | 当前生效版本号 |
| `profile_data` | `LONGTEXT` | 当前生效配置 JSON |
| `draft_data` | `LONGTEXT` NULL | 待确认草稿 JSON |
| `draft_revision` | `INT` NULL | 草稿版本号 |
| `confirmed_by` | `VARCHAR(128)` NULL | 确认人 |
| `confirmed_at` | `DATETIME(6)` NULL | 确认时间 |
| `effective_monitor_round` | `VARCHAR(64)` NULL | 计划生效的 monitor 轮次 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** `idx_strategy_profiles_scope (scope_type, scope_value, status)`；主键 `profile_id`。

### 3.18 `strategy_change_log`

**职责：** 策略配置变更审计，记录人工操作前后的配置内容。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 变更记录 ID |
| `profile_id` | `VARCHAR(128)` | 受影响的配置组合 |
| `action` | `VARCHAR(32)` | 操作类型，如保存草稿、确认、生效 |
| `operator_name` | `VARCHAR(128)` | 操作人 |
| `before_data` | `LONGTEXT` NULL | 变更前配置 |
| `after_data` | `LONGTEXT` NULL | 变更后配置 |
| `created_at` | `TIMESTAMP` | 变更时间 |

**索引：** `idx_strategy_change_log_profile (profile_id, created_at)`；主键 `id`。

### 3.19 `bar_price_tracks`

**职责：** 观察池日 K 价格轨迹，保存不复权、前复权和原始复权因子三套数据。治理完成后不再保存指数或分钟线。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 观察池标的代码 |
| `interval_name` | `VARCHAR(16)` | 当前应为 `daily` |
| `timestamp_value` | `DATETIME(6)` | K 线日期对应时间点 |
| `raw_open` / `raw_high` / `raw_low` / `raw_close` | `DECIMAL(20,6)` | 不复权 OHLC，模拟成交和收益估值使用 |
| `qfq_open` / `qfq_high` / `qfq_low` / `qfq_close` | `DECIMAL(20,6)` | 前复权 OHLC，技术指标、趋势和回测使用 |
| `volume` | `DECIMAL(24,4)` | 成交量 |
| `amount` | `DECIMAL(24,4)` | 成交额 |
| `adjustment_factor` | `DECIMAL(28,12)` | 原始复权因子 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (symbol, interval_name, timestamp_value)`；无其他索引。

### 3.20 `orders`

**职责：** 模拟订单主表，保存订单当前状态、请求数量和累计成交信息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `order_id` | `VARCHAR(64)` | 订单唯一 ID |
| `trade_date` | `DATE` | 订单交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `asset_type` | `VARCHAR(16)` | 资产类型 |
| `direction` | `VARCHAR(16)` | 买卖方向 |
| `quantity` | `BIGINT` | 委托数量 |
| `requested_price` | `DECIMAL(20,6)` | 委托价格 |
| `filled_quantity` | `BIGINT` | 累计成交数量 |
| `average_fill_price` | `DECIMAL(20,6)` | 平均成交价 |
| `status` | `VARCHAR(32)` | 订单状态机当前状态 |
| `reason` | `TEXT` NULL | 创建或处理原因 |
| `rejected_reason` | `TEXT` NULL | 拒绝原因 |
| `created_at` | `DATETIME(6)` | 创建时间 |
| `submitted_at` | `DATETIME(6)` NULL | 提交时间 |
| `updated_at` | `DATETIME(6)` NULL | 最近状态更新时间 |

**索引：** `idx_orders_open (symbol, status, updated_at)`；`idx_orders_trade_date (trade_date, symbol)`；主键 `order_id`。

### 3.21 `order_events`

**职责：** 订单状态机事件流，记录订单每次状态变化及累计成交数量。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 事件 ID |
| `order_id` | `VARCHAR(64)` | 订单 ID |
| `trade_date` | `DATE` | 交易日 |
| `status` | `VARCHAR(32)` | 变更后的订单状态 |
| `filled_quantity` | `BIGINT` | 该事件时累计成交数量 |
| `reason` | `TEXT` NULL | 状态变更原因 |
| `event_at` | `DATETIME(6)` | 事件发生时间 |

**索引：** `idx_order_events_order (order_id, event_at)`；主键 `id`。

### 3.22 `decision_events`

**职责：** 策略业务事件审计表，记录决策、风控、订单关联和持仓上下文。看板应读取聚合摘要，不应直接把每轮重复事件全部铺开。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT AUTO_INCREMENT` | 事件 ID |
| `trade_date` | `DATE` | 交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `phase` | `VARCHAR(24)` | 业务阶段，如 decision、risk、execution |
| `direction` | `VARCHAR(16)` NULL | 决策方向 |
| `approved` | `TINYINT` NULL | 是否通过 |
| `target_weight` | `DECIMAL(12,8)` NULL | 目标仓位 |
| `status` | `VARCHAR(32)` NULL | 业务状态 |
| `filled_quantity` | `BIGINT` | 关联累计成交数量 |
| `position_quantity` | `BIGINT` | 事件时持仓数量 |
| `position_weight` | `DECIMAL(12,8)` | 事件时持仓比例 |
| `position_state` | `VARCHAR(16)` | 持仓状态，如 holding、flat |
| `reasons` | `TEXT` NULL | 决策或风控原因 |
| `strategy_id` | `VARCHAR(128)` NULL | 策略 ID |
| `order_id` | `VARCHAR(64)` NULL | 关联订单 ID |
| `event_key` | `VARCHAR(128)` | 幂等业务事件键 |
| `monitor_round` | `VARCHAR(64)` NULL | 产生事件的 monitor 轮次 |
| `event_at` | `DATETIME(6)` | 业务事件时间 |
| `created_at` | `DATETIME(6)` | 入库时间 |

**索引：** 唯一键 `uq_decision_events_event_key (event_key)`；`idx_decision_events_date_symbol (trade_date, symbol, event_at)`；`idx_decision_events_retention (phase, event_at)`；`idx_decision_events_order (order_id, event_at)`；主键 `id`。

### 3.23 `futures_positions`

**职责：** 期货情绪和席位净持仓辅助数据，仅作为外部市场信号，不得进入 A 股持仓和收益统计。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_date` | `DATE` | 数据交易日 |
| `contract` | `VARCHAR(16)` | 期货合约 |
| `top10_long` | `DECIMAL(20,2)` | 前十多头数量或规模 |
| `top10_short` | `DECIMAL(20,2)` | 前十空头数量或规模 |
| `top10_net_ratio` | `DECIMAL(10,6)` | 前十净持仓比例 |
| `specific_seat_name` | `VARCHAR(128)` NULL | 关注席位名称 |
| `specific_seat_long` | `DECIMAL(20,2)` NULL | 关注席位多头 |
| `specific_seat_short` | `DECIMAL(20,2)` NULL | 关注席位空头 |
| `specific_seat_net_ratio` | `DECIMAL(10,6)` NULL | 关注席位净比例 |
| `combined_net_ratio` | `DECIMAL(10,6)` | 汇总净比例 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `created_at` | `TIMESTAMP` | 入库时间 |

**索引：** `idx_futures_trade_date (trade_date)`；主键 `PRIMARY KEY (trade_date, contract)`。

### 3.24 `overseas_market_data`

**职责：** 海外市场外部信号数据，可参与 A 股策略分析，但永久禁止进入 A 股持仓和收益统计。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `market` | `VARCHAR(32)` | 市场标识 |
| `symbol` | `VARCHAR(32)` | 系统内标识 |
| `trade_date` | `DATE` | 数据交易日 |
| `name` | `VARCHAR(128)` NULL | 名称 |
| `prev_close` | `DECIMAL(20,6)` | 前收价 |
| `close_price` | `DECIMAL(20,6)` | 收盘价 |
| `change_pct` | `DECIMAL(10,6)` | 涨跌幅 |
| `source_symbol` | `VARCHAR(64)` | 数据源代码 |
| `is_proxy` | `TINYINT` | 是否代理/替代标的 |
| `data_status` | `VARCHAR(24)` | 数据状态 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `fetched_at` | `DATETIME(6)` | 获取时间 |

**索引：** `idx_overseas_trade_date (trade_date)`；主键 `PRIMARY KEY (market, symbol, trade_date)`。

### 3.25 `data_sync_status`

**职责：** 各类数据同步任务的当前结果和运行时间，供故障排查和任务幂等控制使用。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_name` | `VARCHAR(64)` | 同步任务唯一名称 |
| `trade_date` | `DATE` | 任务所属交易日 |
| `status` | `VARCHAR(24)` | 成功、失败、部分成功等状态 |
| `success_count` | `INT` | 成功数量 |
| `failure_count` | `INT` | 失败数量 |
| `error_summary` | `TEXT` NULL | 错误摘要 |
| `started_at` | `DATETIME(6)` | 开始时间 |
| `finished_at` | `DATETIME(6)` | 完成时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** `idx_data_sync_status_date (trade_date, status)`；主键 `task_name`。

### 3.26 `instrument_sector_mapping`

**职责：** 标的到行业/板块的当前映射，用于策略特征和龙虎榜分析。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `sector` | `VARCHAR(64)` | 行业或板块 |
| `source` | `VARCHAR(32)` | 映射来源 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (symbol)`。

### 3.27 `lhb_records`

**职责：** 龙虎榜按交易日和标的保存的事件记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trade_date` | `DATE` | 龙虎榜交易日 |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `name` | `VARCHAR(128)` NULL | 标的名称 |
| `sector` | `VARCHAR(64)` NULL | 行业或板块 |
| `net_buy` | `DECIMAL(24,2)` NULL | 净买入金额 |
| `record_data` | `LONGTEXT` | 原始或扩展龙虎榜 JSON |
| `source` | `VARCHAR(64)` | 数据来源 |
| `created_at` | `TIMESTAMP` | 入库时间 |

**索引：** `idx_lhb_symbol (symbol, trade_date)`；主键 `PRIMARY KEY (trade_date, symbol)`。

### 3.28 `lhb_seat_profile`

**职责：** 龙虎榜席位画像及其历史统计。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seat_name` | `VARCHAR(256)` | 席位名称 |
| `seat_type` | `VARCHAR(32)` NULL | 席位类型 |
| `quant_firm` | `VARCHAR(128)` NULL | 关联量化机构 |
| `buy_count` | `INT` | 买入样本数 |
| `t3_win_rate` | `DECIMAL(10,6)` NULL | T+3 胜率 |
| `profile_data` | `LONGTEXT` | 画像扩展 JSON |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (seat_name)`。

### 3.29 `lhb_quant_seats`

**职责：** 可配置的量化席位名单和策略风格标签。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seat_name` | `VARCHAR(256)` | 席位名称 |
| `quant_firm` | `VARCHAR(128)` | 量化机构名称 |
| `strategy_style` | `VARCHAR(128)` NULL | 策略风格 |
| `notes` | `TEXT` NULL | 备注 |
| `is_active` | `TINYINT` | 是否启用 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (seat_name)`。

### 3.30 `index_price_tracks`

**职责：** 指数价格轨迹表，独立保存上证、深证、沪深 300、创业板、科创 50 等基准指数的日 K 数据，不与观察池日 K 或分钟线混存。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 指数系统标识 |
| `interval_name` | `VARCHAR(16)` | K 线周期，当前为 `daily` |
| `timestamp_value` | `DATETIME(6)` | K 线时间点 |
| `open_price` | `DECIMAL(20,6)` | 开盘点位 |
| `high_price` | `DECIMAL(20,6)` | 最高点位 |
| `low_price` | `DECIMAL(20,6)` | 最低点位 |
| `close_price` | `DECIMAL(20,6)` | 收盘点位 |
| `volume` | `DECIMAL(24,4)` | 成交量 |
| `amount` | `DECIMAL(24,4)` | 成交额 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `fetched_at` | `DATETIME(6)` | 数据获取时间 |
| `created_at` | `TIMESTAMP` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (symbol, interval_name, timestamp_value)`；`idx_index_price_tracks_time (interval_name, timestamp_value, symbol)`。

### 3.31 `intraday_bars`

**职责：** 分钟线和分时聚合数据表，由当日 `market_quotes` 快照转换产生，支持 1m、5m、15m、30m、60m 等周期。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `VARCHAR(32)` | 标的代码 |
| `trade_date` | `DATE` | 行情所属交易日 |
| `interval_name` | `VARCHAR(16)` | 分钟周期，如 `1m`、`5m` |
| `timestamp_value` | `DATETIME(6)` | 分钟 K 时间点 |
| `open_price` | `DECIMAL(20,6)` | 开盘价 |
| `high_price` | `DECIMAL(20,6)` | 最高价 |
| `low_price` | `DECIMAL(20,6)` | 最低价 |
| `close_price` | `DECIMAL(20,6)` | 收盘价或该分钟最新价 |
| `volume` | `DECIMAL(24,4)` | 成交量 |
| `amount` | `DECIMAL(24,4)` | 成交额 |
| `source` | `VARCHAR(64)` | 数据来源 |
| `created_at` | `TIMESTAMP` | 创建时间 |
| `updated_at` | `TIMESTAMP` | 最近更新时间 |

**索引：** 主键 `PRIMARY KEY (symbol, interval_name, timestamp_value)`；`idx_intraday_bars_trade_date (trade_date, symbol, interval_name, timestamp_value)`。

## 4. 表之间的逻辑关联

以下关联均为业务逻辑关联，不是数据库外键。连接条件变化时必须同步检查存储层、报表查询和清理任务。

| 主表 | 从表/使用方 | 关联字段 | 关系与说明 |
| --- | --- | --- | --- |
| `watchlist_items` | `bar_price_tracks` | `symbol` | 一个观察池标的对应多条日 K；仅有效观察池应进入同步范围 |
| `watchlist_items` | `market_quotes`、`market_quote_events` | `symbol` | 一个观察池标的对应当日多条行情快照/审计事件 |
| `watchlist_items` | `positions`、`orders`、`fills` | `symbol` | 标的与持仓、订单、成交事实的业务关联 |
| `watchlist_items` | `decisions`、`decision_events` | `symbol` | 标的与日决策摘要、策略审计事件的业务关联 |
| `watchlist_items` | `watchlist_exclusions` | `symbol` | 删除后通过墓碑阻止重新加入；不是级联删除关系 |
| `instrument_catalog` | `watchlist_items` | `symbol` | 搜索目录提供名称和资产类型，添加观察池时复制必要信息 |
| `instrument_catalog` | `instrument_sector_mapping` | `symbol` | 目录标的与行业映射的业务关联 |
| `account_state` | `positions`、`portfolio_snapshots` | 账户语义 | 现金、持仓、市值共同构成组合估值；当前没有 account_id 外键 |
| `orders` | `order_events` | `order_id` | 一个订单对应多条状态事件 |
| `orders` | `fills` | `order_id` | 一个订单可以对应多条成交事实；历史成交可能为空订单 ID |
| `orders` | `decision_events` | `order_id` | 决策/执行事件可关联订单 |
| `strategy_definitions` | `strategy_profiles` | `strategy_id` 存于配置 JSON/代码 | 策略目录与组合配置逻辑关联，当前没有结构化中间表 |
| `strategy_profiles` | `strategy_change_log` | `profile_id` | 一个配置组合对应多条变更审计 |
| `strategy_profiles` | `backtest_runs` | `strategy_profile_id` | 回测记录引用使用的配置组合版本 |
| `decisions` | `daily_reports` | `trade_date`、`symbol` 通过 `report_data` | 日报归档聚合当天决策，不建立逐行外键 |
| `decision_events` | `daily_reports` | `trade_date`、`symbol` 通过 `report_data` | 日报展示摘要，不能把原始事件全量直接铺开展示 |
| `trading_calendar` | `market_quotes`、`decisions`、`daily_reports` | `market`/`trade_date` | 判断交易日、日报生成日和数据任务窗口 |
| `trading_calendar` | `portfolio_snapshots` | `snapshot_date` | 组合日快照按交易日生成 |
| `data_sync_status` | 各行情/外部数据表 | `task_name`、`trade_date` | 任务状态索引，不直接拥有业务数据 |
| `futures_positions`、`overseas_market_data` | 策略运行 | `trade_date` | 仅作为外部信号输入，禁止写入 A 股持仓和收益事实 |
| `lhb_records` | `lhb_seat_profile`、`lhb_quant_seats` | `seat_name` 存于扩展 JSON/业务解析 | 龙虎榜记录与席位画像/配置的逻辑关联 |
| `lhb_records` | `instrument_sector_mapping` | `symbol` | 龙虎榜标的与板块映射的业务关联 |

### 4.1 本次新增的目标表

以下表已进入当前代码和迁移脚本的目标模型，但生产库是否已执行迁移仍需通过第 5 节 SQL 核对：

- `index_price_tracks`：指数日 K 和价格轨迹；
- `intraday_bars`：分钟线及分时聚合数据。

完成生产迁移后，应将实际 `SHOW CREATE TABLE` 结果与本文档核对；最终删除 `bars` 后，系统应保留 30 张业务表。

## 5. 现状核对与运维 SQL

以下 SQL 只读，可用于生产库核对；不要在业务库中执行本文档中的 `DROP` 操作。

```sql
SHOW TABLES;

SELECT table_name, table_rows, data_length, index_length, update_time
FROM information_schema.tables
WHERE table_schema = DATABASE()
ORDER BY table_name;

SHOW CREATE TABLE bars;
SHOW CREATE TABLE bar_price_tracks;
SHOW INDEX FROM bars;
SHOW INDEX FROM bar_price_tracks;
```

检查是否存在声明式外键：

```sql
SELECT table_name, constraint_name, referenced_table_name
FROM information_schema.referential_constraints
WHERE constraint_schema = DATABASE();
```

检查目标表是否已经建立：

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN ('index_price_tracks', 'intraday_bars');
```

检查按保留策略积压的数据：

```sql
SELECT COUNT(*) AS expired_quote_events
FROM market_quote_events
WHERE observed_at < NOW() - INTERVAL 7 DAY;

SELECT trade_date, COUNT(*) AS decision_event_count
FROM decision_events
GROUP BY trade_date
ORDER BY trade_date DESC;

SELECT trade_date, symbol, COUNT(*) AS duplicate_count
FROM decisions
GROUP BY trade_date, symbol
HAVING COUNT(*) > 1;
```

## 6. 表治理结论

### 6.1 立即治理

| 表 | 结论 | 动作 |
| --- | --- | --- |
| `bars` | 混合职责和旧版回退表 | 先迁移观察池日 K、指数日 K、分钟线，清理代码依赖，最后删除 |
| `bar_price_tracks` | 观察池日 K 主表，但历史可能不完整 | 通过 AlphaFeed 重建 raw/qfq/factor 后继续保留 |
| `market_quotes` | 当日快照表 | 只保留当前交易日快照，分钟线转入 `intraday_bars` |
| `market_quote_events` | 审计事件表 | 按 7 天保留期清理 |

### 6.2 保留但加强约束

- `decisions`：同一 `trade_date + symbol` 只能有一条日报决策摘要。
- `decision_events`：通过 `event_key` 幂等；保留业务状态变化，不把每轮无变化的观望/持有重复写成展示记录。
- `orders`、`order_events`、`fills`：分别保持订单当前状态、状态事件和成交事实的边界。
- `metadata`：统一 key 命名空间，例如 `risk.*`、`runtime.*`、`sync.*`；禁止保存密码、API Key 和完整生产连接串。
- `trading_calendar`：只通过统一日历表判断交易日；新增市场时只增加 `market` 数据，不复制新表。

### 6.3 当前没有足够证据删除

`account_state`、`positions`、`portfolio_snapshots`、`backtest_runs`、`daily_reports`、策略相关表、观察池目录表、外部市场表和龙虎榜表职责明确，当前不判定为无效或重复表。后续如果某表连续一个完整发布周期无读写、无接口依赖，才进入“弃用观察”并另行出具删除方案。

## 7. 文档维护与结构变更规则

今后任何表的新增、删除或结构变更都必须同步更新本文档，最低要求如下：

1. 新增表：先明确职责、数据粒度、保留期、敏感字段和关联关系，再提交迁移脚本；在本文档增加表清单、完整字段、索引和关联说明。
2. 新增字段：在同一变更中补充字段类型、是否可空、默认值、业务含义和读写方；如果涉及脱敏或兼容逻辑，补充运维注意事项。
3. 修改字段：写明旧结构、新结构、数据迁移方式、回滚边界和应用版本兼容期；不得只改 `CREATE TABLE` 而不更新迁移脚本。
4. 新增或修改索引：记录索引名称、字段顺序、唯一性、解决的查询场景和预计影响；上线前检查重复索引和写入开销。
5. 删除字段或表：先检索代码、接口、报表、定时任务、备份脚本和运维 SQL；完成数据备份及验收后再删除，并在本文档保留删除原因和替代对象。
6. 表结构变更与本文档必须在同一个 PR 中提交；文档更新日期与迁移脚本版本保持一致。
7. 生产变更完成后，使用第 5 节 SQL 对实际结构复核，并在对应 `reviews` 或 `releases` 文档记录执行结果。
8. 文档中不得出现真实密码、API Key、生产连接串或可直接登录生产环境的敏感信息。

## 8. 变更验收清单

- [ ] 表名、字段名、类型、可空性和默认值与生产 `SHOW CREATE TABLE` 一致。
- [ ] 主键、唯一键和普通索引均已记录，且无重复或失效索引。
- [ ] 新增/删除表已经更新表总数、分类和关联关系。
- [ ] 应用读写路径已经完成代码检索，未遗留旧表回退依赖。
- [ ] 数据迁移前已完成备份，迁移后完成行数、日期范围和重复数据校验。
- [ ] 保留期清理任务有索引支持，并验证不会误删业务事实。
- [ ] 生产库核对结果已记录到复核或发布文档。
