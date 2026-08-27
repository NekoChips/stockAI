# 行情数据表治理与 `bars` 淘汰实施方案

**状态：** implemented
**负责人：** platform-and-operations
**创建日期：** 2026-08-27
**更新日期：** 2026-08-27
**关联：** [实时快照与日 K 分时调度设计](../specs/2026-08-26-market-data-scheduling-design.md)、[AlphaFeed 海外市场数据规格](../specs/2026-08-26-alphafeed-external-market.md)、[数据库数据字典](../architecture/2026-08-27-database-data-dictionary.md)

## 1. 目标与范围

本方案处理生产 MySQL 中历史行情表职责混杂的问题，最终目标是：

1. 观察池历史日 K 由 AlphaFeed 重新获取，并写入 `bar_price_tracks`。
2. 指数日 K 独立写入 `index_price_tracks`。
3. 分钟线独立写入 `intraday_bars`。
4. 清理全部业务逻辑对 `bars` 的读取回退和写入依赖。
5. 完成数据校验后删除 `bars` 表。
6. 识别现有无效表、过渡表和表间重复职责，形成可执行的治理结论。

本方案只描述实施计划，不执行生产数据库迁移、数据删除或 `DROP TABLE`。

## 2. 当前问题判断

### 2.1 `bars` 的混合职责

当前 `bars` 同时承载：

- 旧版本观察池日 K；
- 新版本保存的前复权日 K 副本；
- 指数日 K；
- 由 `market_quotes` 转换得到的分钟线；
- `bar_price_tracks` 没有记录时的兼容回退。

这也是 `bar_price_tracks` 只有少量记录、而 `bars` 仍有几百条记录的直接背景：新表创建后没有从旧表回填，增量同步又以新表的最新日期作为起点。

### 2.2 当前已确认的非重复表

下列表虽然名称或数据形态相近，但职责不同，不应作为重复表删除：

| 表 | 职责 | 结论 |
| --- | --- | --- |
| `decisions` | 每个交易日、每个标的的当前策略决策摘要 | 保留 |
| `decision_events` | 策略业务状态变化审计 | 保留，按既定保留期治理 |
| `orders` | 订单当前状态及聚合信息 | 保留 |
| `order_events` | 订单状态流转明细 | 保留 |
| `fills` | 模拟成交事实记录 | 保留 |
| `market_quotes` | 当日最新行情快照及当日分时来源 | 保留，保留当前日数据 |
| `market_quote_events` | 快照采集审计，保留 7 天 | 保留，按 7 天清理 |
| `watchlist_items` | 当前观察池 | 保留 |
| `watchlist_exclusions` | 删除标的的墓碑记录，避免被默认配置重新加入 | 保留 |
| `instrument_catalog` | 全市场代码、名称和类型搜索目录 | 保留 |
| `strategy_definitions` | 策略元数据和中英双语说明 | 保留 |
| `strategy_profiles` | 策略组合、范围和参数版本 | 保留 |
| `strategy_change_log` | 策略人工变更审计 | 保留 |
| `portfolio_snapshots` | 每日组合资产快照 | 保留 |
| `daily_reports` | 只读日报归档 | 保留 |

### 2.3 需要拆分或淘汰的表

| 表 | 当前问题 | 治理结论 |
| --- | --- | --- |
| `bars` | 混合观察池、指数、分钟线和旧版回退职责 | 拆分后删除 |
| `bar_price_tracks` | 观察池价格轨迹主表，但当前缺少历史回填，且曾被当作所有日 K 的通用来源 | 限定为观察池日 K；补齐历史后保留 |
| `market_quotes` | 快照表本身不适合继续承担分钟 K 的长期查询 | 仅保存当日快照；分钟 K 转入 `intraday_bars` |
| `metadata` | 通用键值表，承载运行状态和风险配置 | 暂保留；建立 key 命名空间，后续再评估是否拆成配置表 |

当前没有足够证据判定 `metadata` 为无效表。它仍承载风险配置草稿、激活配置和运行标记，不能在本次删除 `bars` 时一并清理。

## 3. 目标数据模型

### 3.1 `bar_price_tracks`：观察池日 K

保留现有表名，限定数据范围为观察池标的的日 K：

- 主键：`(symbol, interval_name, timestamp_value)`；
- `interval_name` 当前固定为 `daily`；
- `raw_*` 保存不复权价格；
- `qfq_*` 保存前复权价格；
- `adjustment_factor` 保存原始复权因子；
- `source` 保存实际来源，历史重建记录为 `alphafeed`；
- 不再接收指数和分钟线数据。

历史回填不得直接把 `bars` 的前复权数据伪装成不复权数据。必须按观察池逐标的调用 AlphaFeed，同时获取：

```text
adjust=none
adjust=forward
```

然后按交易日对齐写入三套数据。AlphaFeed 支持通过 `start_time`、`end_time` 获取日期区间，回填时以配置的历史起始日和当前截止日为范围。[AlphaFeed 时间区间接口说明](https://docs.alphafeed.org/zh-Hans/sdk/python-quickstart)

### 3.2 `index_price_tracks`：指数价格轨迹

新增独立表，建议字段：

```text
symbol
interval_name
timestamp_value
open_price
high_price
low_price
close_price
volume
amount
source
fetched_at
updated_at
```

约束：

- 主键为 `(symbol, interval_name, timestamp_value)`；
- 当前只保存 `daily`；
- 指数不进入观察池持仓和收益统计；
- 指数走势、盈亏分析基准线和基准状态接口统一从本表读取；
- 指数同步保留 AlphaFeed 主源与现有备用源策略，实际来源必须写入 `source`。

### 3.3 `intraday_bars`：分钟线

新增独立表，建议字段：

```text
symbol
trade_date
interval_name
timestamp_value
open_price
high_price
low_price
close_price
volume
amount
source
created_at
updated_at
```

约束：

- 主键为 `(symbol, interval_name, timestamp_value)`；
- 支持 `1m`、`5m`、`15m`、`30m`、`60m`；
- `market_quotes` 只保存当日接口快照；
- 详情页的分时、五日分钟聚合和分钟 K 统一从本表读取；
- 先完整迁移现有 `bars` 中 `interval_name = 'minute'` 的数据，再决定是否启用独立保留期；
- 初次迁移不删除任何分钟数据。

## 4. 分阶段实施

### 阶段一：基线盘点与冻结删除条件

1. 停止直接修改生产数据表结构的临时操作。
2. 记录生产环境的表行数、最早日期、最新日期、标的数量和来源分布。
3. 导出 `bars` 的结构和数据备份，由运维人员保存到数据库主机之外的受控位置。
4. 生成待迁移清单：
   - `bars` 中 `interval_name = 'daily'` 的观察池标的；
   - `bars` 中的指数标的；
   - `bars` 中 `interval_name = 'minute'` 的数据；
   - 不在观察池、不在指数配置且不是分钟线的异常记录。
5. 在代码中增加删除前检查，任何一项不通过都禁止删除 `bars`。

### 阶段二：新增目标表与存储接口

已新增迁移脚本：

```text
migrations/009_split_market_bar_tables.sql
```

代码层新增明确的存储接口：

```text
save_watchlist_price_tracks()
load_watchlist_bars()
save_index_price_tracks()
load_index_bars()
save_intraday_bars()
load_intraday_bars()
```

要求：

- 接口命名体现数据域，不再用一个通用 `save_bars()` 处理所有行情类型；
- MySQL 和 mock 存储实现保持相同契约；
- 新接口使用幂等 upsert；
- 写入失败必须记录 `data_sync_status`，不能静默视为成功。

当前应用初始化会创建两个目标表，但不会自动创建或删除旧 `bars` 表；已有生产库必须先执行迁移脚本，再按阶段六人工删除旧表。

### 阶段三：观察池历史重建

1. 从 `watchlist_items` 读取有效观察池，不读取 `bars` 作为数据源。
2. 逐标的通过 AlphaFeed 获取配置区间内的完整日 K。
3. 分别获取 raw 和 qfq 数据并按日期对齐。
4. 写入 `bar_price_tracks`，并校验：
   - raw 和 qfq 日期集合一致；
   - 最新日期不晚于同步截止日期；
   - 行数达到预期交易日数量；
   - `source = 'alphafeed'`；
   - 调整因子可计算且不为异常空值。
5. 允许任务按标的重试，禁止因为一个标的失败而覆盖其他标的成功结果。
6. 只有所有有效观察池标的达到最低历史长度，才将 `watchlist_history` 状态标记为成功。

### 阶段四：指数与分钟线迁移

#### 指数

1. 从 `config.benchmarks` 获取指数集合。
2. 通过指数历史数据统一入口获取日 K。
3. 写入 `index_price_tracks`。
4. 修改盈亏分析、指数状态和图表接口，移除对 `bars` 的读取。
5. 校验五个主要指数均有记录，日期范围与组合分析区间可对齐。

#### 分钟线

1. 将 `bars` 中 `interval_name = 'minute'` 的记录写入 `intraday_bars`。
2. 按 `(symbol, interval_name, timestamp_value)` 去重。
3. 对比迁移前后每个标的的：
   - 总行数；
   - 最早时间和最晚时间；
   - 每日行数；
   - 开、高、低、收价格范围。
4. 修改详情页、五日分时聚合和分钟 K 接口读取 `intraday_bars`。
5. 修改行情清理逻辑：新交易日清理 `market_quotes` 的旧快照时，不再把数据写入 `bars`，而是写入或更新 `intraday_bars`。

### 阶段五：清理 `bars` 依赖

全局搜索并删除以下逻辑：

- `load_bars()` 对 `bars` 的回退查询；
- `save_price_tracks()` 自动向 `bars` 写副本；
- 指数使用通用 `save_bars()` 写入 `bars`；
- 分钟线使用通用 `save_bars()` 写入 `bars`；
- 详情页从 `bars` 读取分钟线；
- 任何把 `bars` 视为通用历史行情源的测试和辅助脚本。

同时将调用方改为目标数据域接口：

| 原调用 | 新调用 |
| --- | --- |
| `load_bars(symbol, daily)` | `load_watchlist_bars(symbol)` |
| `load_bars(index, daily)` | `load_index_bars(index)` |
| `load_bars(symbol, minute)` | `load_intraday_bars(symbol)` |
| `save_bars(qfq_bars)` | `save_watchlist_price_tracks(...)` |
| `save_bars(index_bars)` | `save_index_price_tracks(...)` |
| `save_bars(minute_bars)` | `save_intraday_bars(...)` |

### 阶段六：删除 `bars`

只有阶段一至五全部通过后，才允许执行：

```sql
DROP TABLE bars;
```

删除前必须满足：

- 全项目不再出现 `FROM bars`、`INTO bars` 或 `save_bars` 的生产路径；
- 观察池每个标的的 `bar_price_tracks` 已达到预期历史长度；
- 指数每个标的的 `index_price_tracks` 已达到预期历史长度；
- 分钟线迁移前后校验通过；
- 页面详情、盈亏分析、回测和策略运行测试通过；
- 新版本至少运行一个完整交易日，未出现 `bars` 缺表错误；
- 已完成生产备份并确认可恢复。

## 5. 数据治理与异常表清单

### 5.1 立即治理

| 对象 | 问题 | 处理方式 |
| --- | --- | --- |
| `bars` | 多域混存、职责重复、存在旧数据 | 按阶段拆分后删除 |
| `bar_price_tracks` | 新旧数据不完整，历史回填缺口 | AlphaFeed 全量重建观察池数据 |
| `market_quotes` | 只应保留当日快照，不能承担分钟历史 | 保留当日职责，分钟数据转独立表 |

### 5.2 保留但加强约束

| 对象 | 治理要求 |
| --- | --- |
| `market_quote_events` | 保留 7 天；增加或确认按 `observed_at` 的清理任务 |
| `decision_events` | 继续执行摘要与审计分离；策略事件和订单事件按不同保留期清理 |
| `decisions` | 保证每个交易日、每个标的最多一条摘要记录 |
| `metadata` | 统一 key 前缀，例如 `risk.*`、`runtime.*`、`sync.*`；禁止存放密码和 API Key |
| `data_sync_status` | 每类同步任务使用稳定的 `task_name`，失败必须可追踪 |

### 5.3 暂不删除

以下表当前仍有明确业务用途，不判定为无效表：

```text
account_state
positions
orders
order_events
fills
watchlist_items
watchlist_exclusions
instrument_catalog
portfolio_snapshots
backtest_runs
daily_reports
trading_calendar
strategy_definitions
strategy_profiles
strategy_change_log
futures_positions
overseas_market_data
instrument_sector_mapping
lhb_records
lhb_seat_profile
lhb_quant_seats
```

后续如需继续治理，应以“是否存在读写入口、是否有明确数据所有者、是否有保留策略和页面/API 依赖”作为判断标准，而不是仅按表名相似性删除。

## 6. 验收 SQL

### 6.1 观察池日 K

```sql
SELECT
    symbol,
    interval_name,
    COUNT(*) AS row_count,
    MIN(DATE(timestamp_value)) AS first_date,
    MAX(DATE(timestamp_value)) AS last_date,
    COUNT(DISTINCT source) AS source_count
FROM bar_price_tracks
WHERE interval_name = 'daily'
GROUP BY symbol, interval_name
ORDER BY symbol;
```

### 6.2 指数日 K

```sql
SELECT
    symbol,
    COUNT(*) AS row_count,
    MIN(DATE(timestamp_value)) AS first_date,
    MAX(DATE(timestamp_value)) AS last_date
FROM index_price_tracks
WHERE interval_name = 'daily'
GROUP BY symbol
ORDER BY symbol;
```

### 6.3 分钟线

```sql
SELECT
    symbol,
    interval_name,
    COUNT(*) AS row_count,
    MIN(timestamp_value) AS first_time,
    MAX(timestamp_value) AS last_time
FROM intraday_bars
GROUP BY symbol, interval_name
ORDER BY symbol, interval_name;
```

### 6.4 删除前依赖检查

```text
rg -n "FROM bars|INTO bars|UPDATE bars|DELETE FROM bars|save_bars\(|load_bars\(" src tests migrations
```

该命令的结果必须只剩迁移说明、历史归档或明确标记为非生产兼容代码的内容；正式应用路径不得再依赖 `bars`。

## 7. 风险与回滚边界

- AlphaFeed 历史数据不完整时，观察池历史同步标记失败，禁止用旧 `bars` 静默填充 raw 价格。
- 新表数据校验不通过时，只回滚应用版本，不执行 `DROP TABLE bars`。
- `bars` 删除后不设计应用层自动恢复；恢复依赖数据库备份或快照。
- `index_price_tracks` 与 `intraday_bars` 上线后，如果页面查询异常，应切回上一版本应用，但不回写旧表。
- 任何删除操作必须由数据库管理员在确认备份可用后执行。

## 8. 完成标准

- [x] 新增 `index_price_tracks` 和 `intraday_bars` 迁移脚本。
- [x] MySQL/mock 存储接口完成域拆分。
- [ ] 观察池日 K 已通过 AlphaFeed 全量重建。
- [ ] 指数日 K 已迁移并由 `index_price_tracks` 提供。
- [ ] 分钟线已迁移并由 `intraday_bars` 提供。
- [x] 所有业务逻辑不再回退或写入 `bars`。
- [x] 前端详情页、盈亏分析、回测、策略运行和同步任务验证通过。
- [ ] 生产运行一个完整交易日无 `bars` 依赖错误。
- [ ] 完成备份确认后删除 `bars`。
- [x] 更新 `docs/README.md` 索引，并补充实施复核记录。
