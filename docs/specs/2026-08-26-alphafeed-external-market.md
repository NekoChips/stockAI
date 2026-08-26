# AlphaFeed 海外市场日 K 采集改造实施方案

## 1. 目标与范围

将当前海外市场数据采集改为复用现有 `AlphaFeedAdapter`，优先通过 AlphaFeed 获取美股大盘指数代理、行业 ETF 和韩国指数日 K 数据。

本次改造不新建一套独立行情适配器，不改变 A 股实时行情、A 股历史 K 线和模拟成交链路。现有 A 股代码校验、A 股主备行情源和 AlphaFeed 限流逻辑继续保留。

海外数据仍然只作为 A 股策略分析因子：

- 不创建海外可交易标的。
- 不进入 A 股持仓、订单和收益统计。
- 只参与 `overseas_market_sentiment` 策略。
- AlphaFeed 获取失败时，海外策略降级，不影响技术、动量、均值回归和风控策略。

## 2. 已确认的调用约束

AlphaFeed 日 K 套餐约束：

```text
最大频率：10 次/分钟
单次请求：1 只标的
历史范围：不限
```

实施时必须满足：

1. 日 K 请求不得批量传入多个标的。
2. 令牌桶按 `API Key + daily_kline` 全局限流，不能只在单个对象实例内限流。
3. 第 10 次请求后必须等待窗口释放，不能立即发送第 11 次请求。
4. 限流异常不能立即重试；应等待窗口或切换备用源。
5. 每次成功请求后才更新缓存和数据库；请求失败不能写入伪造的 0 值。
6. 初始历史补数和每日增量同步都使用相同的单标的请求约束。

当前适配器已经有按端点限流的基础实现，但日 K 默认值为 8 次/分钟，后续统一配置为不超过套餐上限的安全值；生产配置使用 10 次/分钟时仍必须由限流器严格保护。[alphafeed.py](/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/data/alphafeed.py:337)

## 3. 数据范围与代码映射

### 3.1 美股行业 ETF

海外策略当前使用以下行业 ETF：

| A 股板块 | 标准标识 | AlphaFeed 来源标识 |
| --- | --- | --- |
| 信息技术 | `XLK` | `XLK.US` |
| 医药卫生 | `XLV` | `XLV.US` |
| 金融地产 | `XLF` | `XLF.US` |
| 能源 | `XLE` | `XLE.US` |
| 工业 | `XLI` | `XLI.US` |
| 可选消费 | `XLY` | `XLY.US` |
| 必需消费 | `XLP` | `XLP.US` |
| 公用事业 | `XLU` | `XLU.US` |
| 材料 | `XLB` | `XLB.US` |
| 电信服务 | `XLC` | `XLC.US` |

策略仍使用标准标识 `XLK` 等，不将 `.US` 来源标识暴露给 A 股策略和持仓模型。

### 3.2 美股大盘指数

优先验证 AlphaFeed 是否直接提供原始指数代码。如果原始指数代码不可用，使用 ETF 代理：

| 策略标准标识 | 首选来源 | 代理来源 |
| --- | --- | --- |
| `^IXIC` | AlphaFeed 对应指数代码 | `QQQ.US` |
| `^GSPC` | AlphaFeed 对应指数代码 | `SPY.US` |
| `^DJI` | AlphaFeed 对应指数代码 | `DIA.US` |

直接指数和 ETF 代理不能同时请求。运行时按照“首选来源成功即停止，否则使用代理来源”的规则执行，避免重复消耗日 K 调用额度。

数据库中建议同时保存：

```text
canonical_symbol: ^IXIC
source_symbol: QQQ.US
is_proxy: true
```

如果使用代理数据，策略证据中必须显示“使用 QQQ 代理纳斯达克”，不能伪装成原始指数数据。

### 3.3 韩国市场

优先验证 AlphaFeed 是否支持以下标准标识：

```text
KOSPI
KOSPI_IT
KOSPI200
```

若 AlphaFeed 不支持韩国指数，本轮不将未知代码硬编码进 AlphaFeed 请求。韩国数据继续由现有备用源提供；备用源也失败时，仅将海外情绪策略标记为不可用。

## 4. 适配器改造方案

### 4.1 保留现有 A 股接口

以下现有行为不变：

- `get_quote()` 和 `get_quotes()` 仍只接受沪深 A 股/ETF。
- `get_bars()` 和 `get_bars_batch()` 仍返回 A 股 `Bar` 对象。
- A 股历史 K 线继续使用前复权配置。
- A 股实时行情继续使用不复权现价。

### 4.2 在同一适配器中增加海外日 K 方法

在 `AlphaFeedAdapter` 中增加内部通用方法，建议接口如下：

```python
get_external_daily_bars(
    source_symbol: str,
    start: str,
    end: str,
    *,
    count: int | None = None,
) -> list[ExternalDailyBar]
```

要求：

1. 不调用 `validate_hs_symbol()`。
2. 允许 `.US`、韩国指数等外部代码格式。
3. 每次只调用一个 `source_symbol`。
4. 使用 `client.klines.get(source_symbol, period="1d", ...)`。
5. 使用不复权或原始价格，海外数据仅用于涨跌幅情绪判断。
6. 从最近两个有效交易日计算 `change_pct`；若只有一个有效交易日，则返回不可用。
7. 返回统一的外部日行情对象，不复用只能接受 A 股符号的 `Bar` 解析器。
8. 保留来源标识、来源代码、交易日期和抓取时间。

建议的统一结果结构：

```text
market
canonical_symbol
source_symbol
name
trade_date
prev_close
close_price
change_pct
source
is_proxy
fetched_at
```

### 4.3 标的可用性探测

增加一次性或低频的标的探测逻辑：

1. 先调用 AlphaFeed 标的信息或最近日 K。
2. 记录来源代码是否存在、是否有权限、是否有最近两个交易日数据。
3. 探测结果缓存到数据库或进程级短缓存。
4. 不在每轮 monitor 中重复探测。
5. 只有配置变更、连续失败或数据源版本变化时重新探测。

探测失败时：

- 行业 ETF 失败：对应板块的海外情绪策略不可用。
- 原始指数失败：尝试对应 ETF 代理。
- 原始指数和代理都失败：大盘情绪部分不可用。
- 不得把失败标的的涨跌幅设置为 0。

## 5. 限流与缓存方案

### 5.1 限流配置

配置建议：

```json
{
  "kline_max_symbols_per_request": 1,
  "kline_max_requests_per_minute": 10,
  "kline_request_interval_seconds": 6,
  "kline_cache_seconds": 21600
}
```

实际限流按滑动窗口执行，`6 秒间隔`是基础节奏，窗口计数是最终保护。不能仅依赖固定 sleep，因为多个适配器实例可能共享同一个 API Key。

### 5.2 每日同步策略

海外策略只需要每日涨跌幅，不需要盘中轮询：

```text
A 股开盘前
  -> 查询数据库中当天是否已有有效数据
  -> 已有且未过期：不调用 AlphaFeed
  -> 缺失或过期：按标的逐个请求
  -> 成功一只写入一只
  -> 单只失败不影响其他标的
```

当前行业 ETF 10 只，加上 3 个大盘指数代理，最多约 13 次日 K 请求，按照 10 次/分钟约需 78 秒以上。调度窗口必须预留请求和网络耗时，不能把任务安排在交易开始前最后几秒。

### 5.3 历史补数策略

“不限历史”只代表接口没有历史范围限制，不代表每次 monitor 都要重新拉全历史。

分两种情况：

- 初次初始化：按配置的起始日期补数，单标的逐个请求。
- 日常同步：只请求最近一到两个交易日，避免重复消耗额度。

历史数据已存在的标的，不允许每次重拉全量历史。补数任务应支持断点、失败重试和幂等写入。

## 6. 数据库与策略接入

### 6.1 现有表扩展

当前 `overseas_market_data` 已保存市场、标识、交易日、收盘价、涨跌幅、来源和抓取时间。[003_strategy_execution_and_price_tracks.sql](/Users/neko/Documents/ChatGPT/codex-stockAI/migrations/003_strategy_execution_and_price_tracks.sql:51)

建议增加：

```text
source_symbol VARCHAR(64)
is_proxy TINYINT NOT NULL DEFAULT 0
data_status VARCHAR(24) NOT NULL DEFAULT 'ready'
```

主键仍使用：

```text
market + canonical_symbol + trade_date
```

这样可以保留策略标准标识，同时追踪实际使用的 AlphaFeed 来源代码。

### 6.2 策略输入

`overseas_market_sentiment` 只读取：

```text
canonical_symbol
change_pct
trade_date
data_status
```

策略不直接调用 AlphaFeed。所有数据必须先入库，再由 `load_external_strategy_context()` 读取，保持回测和实时 monitor 的数据边界一致。[strategy_runtime.py](/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/strategy_runtime.py:150)

数据超过一个海外交易日，或 `data_status != ready` 时，海外情绪策略返回不可用；其他策略继续执行。

## 7. Monitor 调度改造

将当前直接调用 `fetch_us_market_data()` 和 `fetch_korea_market_data()` 的逻辑替换为统一的外部日行情同步任务。[monitor.py](/Users/neko/Documents/ChatGPT/codex-stockAI/src/stock_ai_agent/monitor.py:518)

建议流程：

```text
09:00  查询数据库缓存
09:05  AlphaFeed 同步美股行业 ETF
09:05  AlphaFeed 同步大盘指数或 ETF 代理
09:10  AlphaFeed 同步可用的韩国指数
09:15  失败标的单独重试
09:20  写入数据健康状态
```

每个市场和每个来源独立执行：

- 美股行业 ETF 失败不阻断大盘指数。
- 大盘指数失败不阻断韩国指数。
- 一个标的失败不阻断其他标的。
- 失败任务不能永久标记为当天已完成，必须允许重试窗口执行。

## 8. 测试清单

新增或调整以下测试：

### 8.1 标的格式

- `XLK.US` 可以被海外日 K 方法接受。
- `QQQ.US`、`SPY.US`、`DIA.US` 可以被海外日 K 方法接受。
- A 股方法仍拒绝非沪深标的。
- 海外标的不会进入 A 股 `Universe`、持仓或订单。

### 8.2 限流

- 单次 AlphaFeed 日 K 请求只传入一个标的。
- 10 次请求内不提前触发第 11 次。
- 第 11 次请求会等待窗口释放。
- 多个适配器实例共享 API Key 时仍按全局 10 次/分钟限流。
- 限流异常不会立即重复请求。

### 8.3 采集与回退

- 单个 ETF 失败时其他 ETF 仍能入库。
- 原始指数不可用时切换 ETF 代理。
- 原始指数和代理都失败时，数据状态为不可用。
- AlphaFeed 返回空数据、字段缺失或日期异常时不写入 0 值。
- 同一标的同一交易日重复同步是幂等的。

### 8.4 策略

- 所有必需海外数据存在时正常计算。
- 行业 ETF 缺失时海外策略失效，核心 A 股策略继续运行。
- 海外数据过期时不触发海外策略交易。
- 使用 ETF 代理时，决策证据显示代理来源。

## 9. 实施顺序

1. 增加海外标的标准化模型和映射配置。
2. 扩展现有 `AlphaFeedAdapter` 的海外日 K 方法。
3. 将日 K 限流配置调整为最多 10 次/分钟、单标的一次请求。
4. 增加数据库来源代码和代理标识字段。
5. 替换海外采集任务，统一写入 `overseas_market_data`。
6. 增加缓存、增量同步和失败重试。
7. 修改策略上下文读取和数据有效期判断。
8. 增加完整的 Mock/契约测试。
9. 使用实际 AlphaFeed API Key 执行一次在线冒烟测试。
10. 验证海外数据不会进入 A 股交易链路后再发布。

## 10. 验收标准

- AlphaFeed 可以成功获取至少一个行业 ETF 的日 K。
- AlphaFeed 可以成功获取至少一个大盘指数或其 ETF 代理的日 K。
- 日 K 请求始终满足 1 只/次、最多 10 次/分钟。
- 13 个左右海外标的可以在调度窗口内完成同步。
- 单个来源或单个标的失败不会导致 monitor 退出。
- 数据写入 MySQL 后，策略只从数据库读取。
- 海外数据缺失时只禁用海外情绪策略，不阻断其他 A 股策略。
- 全部测试通过，且保留现有 A 股行情和模拟交易行为不变。

## 11. 本轮暂不处理

- 海外市场真实交易。
- 海外市场持仓和收益统计。
- 海外市场分钟级行情。
- AlphaFeed 原始指数代码的最终命名，需通过实际账户权限探测确认。
- 韩国指数在 AlphaFeed 中的覆盖范围，需通过实际账户权限探测确认。
