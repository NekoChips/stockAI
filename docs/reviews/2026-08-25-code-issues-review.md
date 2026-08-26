# 代码问题审查报告

| 项 | 值 |
|---|---|
| 审查日期 | 2026-08-25 |
| 审查分支 | `develop` (1db6bc9) |
| 测试结果 | 163 passed |
| 问题分类 | 代码问题、业务问题、策略问题 |

---

## 摘要

对照 [`2026-08-21-strategy-design.md`](../specs/2026-08-21-strategy-design.md) 和 [`2026-08-24-strategy-implementation-review.md`](./2026-08-24-strategy-implementation-review.md)，审查最新代码提交后的实际状态。

**已解决**（上一轮提出的 5 个问题）：
- ✅ 四个新策略不再是空壳，已有真实实现
- ✅ `futures_sentiment` 已加入风控集合
- ✅ 六张数据表已创建（迁移脚本 `003_strategy_data_feeds.sql`）
- ✅ 聚合器 `risk_caps` 逻辑验证通过
- ✅ 策略 ID 已统一命名

**新发现**：13 个已确认根因 + 1 个待确认项

---

## 🔴 代码问题（7 个）

### 1. `_normalize_symbol` 返回整数而非字符串

**位置**：`src/stock_ai_agent/data/lhb.py:29`

```python
def _normalize_symbol(raw: str) -> str:
    if not any(c.isdigit() for c in raw):
        return len("")  # type: ignore  ← 返回 0（整数）
    # ...
```

**后果**：
- 类型注解说返回 `str`，实际返回 `int`
- `# type: ignore` 说明编写时已知类型错误
- 调用方 `if not symbol: continue` 侥幸没崩（`not 0` 为 `True`）
- 任何对返回值调用字符串方法都会 `AttributeError`

**修复**：`return ""`，删除 `# type: ignore`

---

### 2. `_build_strategy_feeds` 缺一个方法就全部失败

**位置**：`src/stock_ai_agent/monitor.py:123-124`

```python
def _build_strategy_feeds(store):
    if not hasattr(store, "load_latest_futures_sentiment"):
        return {}  # ← 直接返回空字典
    # ... 后续构建其他 feeds
    self._feed_cache = feeds  # ← 缓存赋值在 return 后面
```

**后果**：
- `load_latest_futures_sentiment` 不存在 → 所有 feed 丢失
- 缓存赋值在早退后，下一轮读到的是上一轮的旧数据
- 期指数据缺失不应拖垮外围市场和龙虎榜

**修复**：逐 feed 独立 try/except，缺失的 feed 返回 None，早退前清空缓存

---

### 3. `aggregator` 配置多嵌套一层

**位置**：`config/default.yaml:164-165`

```yaml
strategy:
  aggregator:
    aggregator: null  # ← 多嵌套了一层
```

**后果**：
- `config.strategy.aggregator` 读到 `{"aggregator": null}`
- 所有参数（`conflict_max_weight`、`buy_threshold`、`min_effective_weight_ratio`）失效
- 聚合器用硬编码默认值，配置文件改了没用

**修复**：改为 `aggregator: null`（去掉一层），或补全参数：

```yaml
aggregator:
  conflict_max_weight: "0.20"
  buy_threshold: "1.5"
  exit_threshold: "-1.5"
  min_effective_weight_ratio: "0.60"
  legacy_aggregation: false
```

---

### 4. 生产者/消费者字段名不一致

**位置**：
- 生产者：`src/stock_ai_agent/data/lhb.py:101` 返回 `symbol_count`
- 消费者：`src/stock_ai_agent/quant_strategies.py:233` 读取 `sector_symbol_count`
- 转译层：`src/stock_ai_agent/monitor.py:152` 手工重命名

**后果**：
- 功能可用，但增加维护成本
- 改字段名时容易遗漏某处
- `seat_name` 用 `set` 类型存储，键名是单数，无法 JSON 序列化

**修复**：
- 统一字段名为 `sector_symbol_count`，移除转译层
- `seat_name` 改为 `seat_names`，返回 `sorted(list(...))`

---

### 5. `quant_seat_sector_activity` 返回 set 破坏序列化

**位置**：`src/stock_ai_agent/data/lhb.py:95`

```python
return {
    "sector": sector,
    "symbol_count": len(unique_symbols),
    "total_net_buy": total_net_buy,
    "seat_name": set(seat_names),  # ← set 无法 JSON 序列化
}
```

**后果**：这个结构进入 Web 响应或日志时抛出 `TypeError: Object of type set is not JSON serializable`

**修复**：`"seat_names": sorted(list(seat_names))`

---

### 6. 测试从未执行真实适配器

**位置**：`tests/test_data_overseas.py`、`tests/test_data_lhb.py`

**现状**：所有测试注入 mock adapter，`_default_adapter` 从未真正执行

**后果**：
- XLK HTTP 400 错误在 163 个测试全绿时进入 develop
- 同类问题：`ISSUES.md` 记录的"138 个测试漏掉建仓死锁"

**修复**：添加契约测试（可用 `-m integration` 跳过），真实调用每个数据源一次并验证返回结构

---

### 7. `trading_enabled` 字段不起作用

**位置**：
- 定义：`src/stock_ai_agent/models.py:55`
- 读取：`src/stock_ai_agent/watchlist.py:36`、`storage/mysql.py:328`、`web_dashboard.py:62`、`web_actions.py:133`
- 使用：**无（0 处）**

**后果**：
- `grep -rn "if.*trading_enabled" src/` → 无结果
- 迁移脚本默认值 `trading_enabled=0`
- 数据库验证：现有 2 个标的都是 `trading_enabled=0`
- 看起来有安全门，实际完全不拦截下单

**修复**：
- **方案 A**：在 `risk.evaluate()` 里真正拦截 BUY/ADD（允许 REDUCE/EXIT）
- **方案 B**：明确注释为"展示字段"，迁移脚本默认值改为 1

---

## 🟡 业务问题（4 个）

### 8. ETF 回撤止损和波动率风控被关闭（最高优先级）

**位置**：`config/default.yaml:116-117`

```yaml
enabled_by_asset_type:
  etf: ["technical_composite", "time_series_momentum", "futures_sentiment", 
        "overseas_sentiment", "quant_sector_rotation"]
```

**缺失**：`volatility_target`、`drawdown_control`

**后果**：
- `futures_sentiment` 因表空返回 WATCH
- ETF 完全无风控，8% 回撤不止损，波动率超标不减仓
- 这是**最严重的风险敞口**，优先级高于所有其他问题

**修复**：

```yaml
etf: ["technical_composite", "time_series_momentum", "volatility_target", 
      "drawdown_control", "futures_sentiment", "overseas_sentiment"]
```

权重：

```yaml
weights_by_asset_type:
  etf:
    technical_composite: "0.30"
    time_series_momentum: "0.15"
    volatility_target: "0.10"      # 新增
    drawdown_control: "0.15"       # 新增
    futures_sentiment: "0.15"
    overseas_sentiment: "0.15"
```

---

### 9. 美股板块 ETF 拉取失败（XLK/XLV/... HTTP 400）

**位置**：`src/stock_ai_agent/data/overseas.py:36-61`

**现状**：
```python
def _default_adapter():
    import akshare as ak
    def adapter(symbol: str):
        df = ak.index_us_stock_sina(symbol=symbol)  # ← 只支持指数
```

**验证**：
```bash
PYTHONPATH=src ... sync-overseas
# 日志：多个 HTTP 400 警告
# 库内只有 3 行（^IXIC/^GSPC/^DJI），缺 11 个 ETF
```

**后果**：
- 信息技术板块靠 `^IXIC` 兜底，意外可用
- 其余 9 个板块 ETF 全失败，`overseas_sentiment` 对这些板块永久 WATCH

**修复**：按标的类型分流，指数用 `index_us_stock_sina`，ETF 用 `stock_us_hist_sina` 或 `stock_us_spot_em`

---

### 10. `quant_seats` 表无初始数据

**位置**：`migrations/003_strategy_data_feeds.sql:60`

```sql
-- Seed quant_seats from design doc §8.2
```

**现状**：注释存在，INSERT 语句完全缺失

**后果**：
- `load_quant_seats()` 返回 `[]`
- `quant_seat_sector_activity` 过滤条件恒不成立
- `symbol_count` 永远是 0
- `quant_sector_rotation` 永久返回 WATCH（"板块动向不明"）

**修复**：从设计文档第 8.2 节补写 15 条 INSERT（幻方、九坤、明汯、灵均、天演、衍复）

---

### 11. 龙虎榜适配器硬编码空席位名

**位置**：`src/stock_ai_agent/data/lhb.py:72`

```python
"seat_name": "",  # ← 硬编码空字符串
```

**原因**：`stock_lhb_detail_em` 返回标的级汇总，无席位明细

**后果**：
- 主键 `(trade_date, symbol, seat_name)` 退化，每个标的每天只能存 1 条
- `quant_seats` 匹配条件永远不成立（席位名恒空）
- `quant_sector_rotation` 即使有 INSERT 也无法工作

**修复**：改用 `stock_lhb_stock_detail_em` 获取席位明细，根据 `quant_seats` 表标注席位类型

---

## 🟠 策略问题（2 个 + 1 个待确认）

### 12. `instrument_sectors` 表为空且无同步命令

**位置**：
- 表定义：`migrations/003_strategy_data_feeds.sql:25`
- CLI：`src/stock_ai_agent/app.py` 无 `sync-sectors` 命令

**后果**：
- `_symbol_feeds` 取到的 `sector` 字段恒为 `""`
- `overseas_sentiment` 无法计算 `sector_change_percent`
- `quant_sector_rotation` 条件分支失效

**影响范围**：跨策略，2 个策略同时受影响

**修复**：
- 新增 `sync-sectors` 命令
- 或在 `sync-instruments` 里顺带写入板块（利用设计文档的行业归一化映射）

---

### 13. `quant_sector_rotation` 启用但权重为 0

**位置**：
- 启用：`config/default.yaml:117` ETF 的 `enabled_by_asset_type`
- 权重：`config/default.yaml:132-136` `weights_by_asset_type.etf` **无此项**

**后果**：
- 策略每轮被调用，`evaluate()` 执行
- 聚合器 `if weight <= 0: continue` 丢弃结果
- 白白消耗计算，信号无效

**修复**：
- 要么加权重 `quant_sector_rotation: "0.10"`
- 要么从 `enabled` 列表移除

---

### 14. 新标的被 60% 门槛锁死

**位置**：`src/stock_ai_agent/strategy.py:219-230`

```python
if configured_weights is not None and (
    not total_weight or effective_weight < configured_total * Decimal("0.60")
):
    return StrategySignal(..., Direction.WATCH, ...)
```

**场景**：
- 新标的 K 线 < 35 根 → `technical_composite` 返回 WATCH
- `futures_sentiment` 表空 → WATCH
- `overseas_sentiment` 板块映射缺失 → WATCH
- WATCH 信号不计入 `effective_weight`（`strategy.py:191-193`）
- ETF 权重：0.30 + 0.15 + 0.15 + 0.15 + 0.15 = 0.90，WATCH 排除 3 个 → 剩 0.30
- `0.30 < 0.90 * 0.60` → 聚合器返回 WATCH，系统不交易

**后果**：新标的完全无法建仓，比"永远不建仓" bug 更隐蔽

**修复**：
- **方案 A**：区分"数据缺失的 WATCH"和"策略观望"，前者不计入分母
- **方案 B**：调低 `min_effective_weight_ratio` 到 0.40
- **方案 C**：数据缺失时策略返回 `score=0, Direction.HOLD` 而非 WATCH

---

### ⏸️ 待确认：分数归一化是否有意为之

**位置**：`src/stock_ai_agent/strategy.py:196-199`

```python
normalized_score = signal.score if legacy_aggregation else max(
    Decimal("-1"),
    min(Decimal("1"), signal.score / Decimal("2") if signal.score.copy_abs() > 1 else signal.score),
)
```

**行为**：`legacy_aggregation=False`（生产默认）时，score ≥ 2 归一化为 1

**后果**：
- `technical_composite` 得 2.0 和 6.0 的信号强度完全相同
- 强弱梯度被抹平

**状态**：[`2026-08-24-strategy-implementation-review.md`](./2026-08-24-strategy-implementation-review.md) 问题 5 已提出，两轮实现后仍未确认是有意压缩还是过渡遗留

---

## 修复优先级

| 优先级 | 根因 | 层级 | 工作量 | 阻塞关系 |
|---|---|---|---|---|
| **P0** | #8 ETF 无风控 | 业务 | 5 分钟 | 无 |
| **P0** | #7 下单门控失效 | 代码 | 半天 | 无 |
| **P1** | #3 aggregator 调参阻塞 | 代码 | 10 分钟 | 无 |
| **P1** | #14 新标的锁死 | 策略 | 半天 | 需先解决 #9/#12 |
| **P2** | #9 美股 ETF 数据源 | 业务 | 1 天 | 阻塞 overseas_sentiment |
| **P2** | #12 板块映射缺失 | 策略 | 1 天 | 阻塞 #9/#13 |
| **P2** | #10 quant_seats 无数据 | 业务 | 半天 | 阻塞 #11/#13 |
| **P2** | #11 LHB 席位解析 | 业务 | 1 天 | 依赖 #10 |
| **P3** | #13 权重配置缺失 | 策略 | 5 分钟 | 依赖 #10/#11/#12 |
| **P3** | #2 feeds 早退 | 代码 | 半天 | 无 |
| **P3** | #1 类型错误 | 代码 | 5 分钟 | 无 |
| **P3** | #4/#5 序列化 | 代码 | 半天 | 无 |
| **P3** | #6 契约测试 | 代码 | 1 天 | 防复发 |

---

## 验证清单

```bash
# 1. 风控策略已启用
python3 -c "import yaml; c=yaml.safe_load(open('config/default.yaml')); 
print('volatility_target' in c['strategy']['enabled_by_asset_type']['etf'])"

# 2. 席位表非空
python3 -c "import pymysql; conn=pymysql.connect(...); cur=conn.cursor();
cur.execute('SELECT COUNT(*) FROM quant_seats'); print(cur.fetchone()[0])"

# 3. 席位名非空
python3 -c "...; cur.execute('SELECT seat_name FROM lhb_seat_data LIMIT 1'); 
print(cur.fetchone()[0] != '')"

# 4. 板块映射已落库
python3 -c "...; cur.execute('SELECT COUNT(*) FROM instrument_sectors WHERE symbol IN (SELECT symbol FROM watchlist_items)'); 
print(cur.fetchone()[0])"

# 5. aggregator 参数可读
python3 -c "from stock_ai_agent.config import load_config; c=load_config('config/default.yaml'); 
print(c.strategy.aggregator.conflict_max_weight)"
```

---

## 与设计文档的对照

| 设计要求 | 实现状态 | 偏差 |
|---|---|---|
| 六张数据表 | ✅ 已创建 | 无 |
| 期指/外围/LHB 策略 | ✅ 已实现 | LHB 只有 2/5 子策略 |
| 风控集合包含期指 | ✅ 已加入 | 无 |
| 三段式架构 | ❌ 未实现 | 设计文档第 5 节，不影响 K 线 |
| 回测模块 | ❌ 未实现 | 设计文档第 4.10 节 |
| 量化席位预置 | ❌ 缺失 | 根因 #10 |
