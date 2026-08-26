# 新策略实现审阅：已确认与待确认问题

| 项 | 值 |
|---|---|
| 审阅日期 | 2026-08-24 |
| 审阅分支 | `develop` |
| 审阅范围 | `fc8bd8a` (策略中心与市场时段调度) → `5b4158a` (策略风控与市场数据) |
| 改动规模 | 38 文件，+1889 / -182 行 |
| 测试结果 | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` → **137 passed, OK** |
| 对照文档 | [`2026-08-21-strategy-design.md`](../specs/2026-08-21-strategy-design.md) |

> **审阅方式说明**：结论基于代码阅读与测试执行。测试套件已实际运行并全部通过；聚合器与策略装配路径的行为判断来自代码追踪，未做运行时打点验证。凡属推断的部分在下文明确标注。

---

## 摘要

基础设施部分完成度高且质量不错：策略档案持久化（`strategy_profiles`）、按资产类型分流的权重、市场时段调度、交易日历多市场支持、观察池生命周期状态，这些都是设计文档里没有细化、但实现方补上的合理工程。137 个测试全绿。

问题集中在**新策略本身**：四个新策略目前是空壳，六张支撑数据表一张未建，期指策略未接入风控集合，策略 ID 与设计文档全不一致。当前配置恰好绕开了空壳策略，所以系统仍能正常交易，但这层保护很脆弱。

| 类别 | 数量 |
|---|---|
| 🔴 已确认问题 | 5 |
| 🟡 待确认问题 | 4 |

---

## 🔴 已确认问题

### 问题 1：四个新策略是空壳，且与聚合器 60% 门槛构成潜在死锁

**位置**：`src/stock_ai_agent/strategy_runtime.py:102-122`、`src/stock_ai_agent/strategy.py:191-193,219-230`

**现状**：`futures_sentiment`、`overseas_sentiment`、`lhb_follow`、`quant_sector_rotation` 四个策略全部指向 `_unavailable_signal()`，返回 `Direction.WATCH` + `score 0`：

```python
for strategy_id in ("futures_sentiment", "overseas_sentiment", "lhb_follow", "quant_sector_rotation"):
    if strategy_id in enabled:
        signals.append(_unavailable_signal(strategy_id, symbol))
```

**风险机制**：聚合器新增了有效权重门槛（`strategy.py:219`）：

```python
if configured_weights is not None and (not total_weight or effective_weight < configured_total * Decimal("0.60")):
    return ... Direction.WATCH, "有效策略权重不足 60%，本轮策略失效。"
```

而 `WATCH` 信号在 `strategy.py:191-193` 被 `continue` 跳过，**不累加 `effective_weight`**：

```python
if signal.direction == Direction.WATCH:
    objections.extend(...)
    continue
effective_weight += weight
```

因此一旦空壳策略被写入 `enabled` 且分配了权重，它们的权重进入分母 `configured_total` 却不进入分子 `effective_weight`。空壳权重合计超过总权重 40% 时，**聚合器每一轮都返回 WATCH，系统永久不交易**。

**当前是否已发生：否。** `config/default.yaml:115-118` 的 `enabled_by_asset_type` 只启用两个策略：

```json
"enabled_by_asset_type": {
  "etf": ["technical_composite", "time_series_momentum"],
  "stock": ["technical_composite", "time_series_momentum"]
}
```

`profile_from_config`（`strategy_runtime.py:40-41`）会按 `enabled` 过滤权重：

```python
weights = config.strategy.weights_by_asset_type.get(asset_type) or config.strategy.weights
weights = {key: value for key, value in weights.items() if key in enabled}
```

所以 `weights_by_asset_type.etf` 里配的 `futures_sentiment: 0.15` 和 `overseas_sentiment: 0.25` 被过滤掉，空壳策略权重为 0，在 `strategy.py:189` 的 `if weight <= 0: continue` 处就被跳过，不影响 `configured_total`。

**但这层保护很脆弱**：只要有人把空壳策略加进 `enabled`（无论改配置还是通过 `strategy_profiles` 表下发档案），就会立刻触发死锁。而 `weights_by_asset_type` 里已经为它们配好了权重（etf 合计 0.40 / 1.00 = 40%，stock 合计 0.65 / 1.00 = 65%），这看起来就像"随时准备启用"。

**修复建议**（两者都做）：
1. `_unavailable_signal` 返回的空壳策略，其权重应从 `effective_weight` 与 `configured_total` **两边同时排除**，而不是只排除分子。可在聚合器里区分"数据缺失导致的 WATCH"与"策略正常观望"——前者应视作该策略不参与本轮，后者才计入门槛判定。
2. 在 `strategy_runtime.py` 里加一道保护：空壳策略即使出现在 `enabled` 里也强制剔除，直到其数据集就位。

---

### 问题 2：期指策略未加入风控集合，语义与设计相反

**位置**：`src/stock_ai_agent/strategy.py:207`

**现状**：

```python
is_risk_control = signal.strategy_id in {"volatility_target", "drawdown_control"}
```

`futures_sentiment` 不在集合内。

**后果**：期指策略实现后会被当作**方向策略**处理 —— 走 `strategy.py:208` 的分支，其 `target_weight` 参与多头方向投票（取最大值）：

```python
if not is_risk_control and signal.target_weight > target_weight and normalized_score > 0:
    target_weight = signal.target_weight
```

而不是走 `strategy.py:210` 进入 `risk_caps` 做上限 clamp。这与设计文档第 2.3 节"期指策略只做约束，不做驱动"的意图完全相反：设计要求它在过热时把仓位**压到** 40%，实现路径下它会变成在某些情况下把仓位**推高到** 40%。

**修复建议**：

```python
RISK_CONTROL_STRATEGIES = {"volatility_target", "drawdown_control", "futures_sentiment"}
is_risk_control = signal.strategy_id in RISK_CONTROL_STRATEGIES
```

顺带把这个硬编码集合提为模块级常量（设计文档第 6.2 节已提出，[`2026-08-21-optimization.md`](../plans/2026-08-21-optimization.md) 低优先级第 18 项也提到聚合器魔数问题）。

---

### 问题 3：设计文档要求的六张数据表全部未创建

**位置**：`migrations/002_strategy_watchlist_rules.sql`

**现状**：该迁移脚本做的是：
- 新建 `market_quote_events`、`orders`
- 修改 `watchlist_exclusions`、`watchlist_items`、`trading_calendar`、`strategy_profiles`、`decisions`、`positions`

设计文档要求的六张表 —— `futures_positions`、`overseas_market_data`、`instrument_sector_mapping`、`lhb_records`、`lhb_seat_profile`、`lhb_quant_seats` —— **一张都没有**。`lhb_quant_seats` 的 15 条量化席位预置数据（幻方、九坤、明汯、灵均、天演、衍复）也未落库。

**关联**：这解释了问题 1 —— 四个策略之所以是空壳，是因为既没有数据源接入，也没有存放数据的表。

**修复建议**：补一份 `migrations/003_new_strategy_datasets.sql`，内容可直接取自设计文档第 8.2 节。注意设计文档里的 schema 用了 `DECIMAL(20,6)` 而非项目现有的 `VARCHAR(40)` 风格 —— 这是正确方向（见 [`2026-08-21-optimization.md`](../plans/2026-08-21-optimization.md) 高优先级第 5 项），新表直接用 `DECIMAL` 即可，不必迁就旧表。

---

### 问题 4：策略 ID 与设计文档全部不一致，龙虎榜五合二

**位置**：`src/stock_ai_agent/strategy_runtime.py:21-32`

| 设计文档 ID | 实际实现 ID | 状态 |
|---|---|---|
| `futures_position_sentiment` | `futures_sentiment` | 改名 |
| `overseas_market_sentiment` | `overseas_sentiment` | 改名 |
| `lhb_follow_star_seats` | `lhb_follow` | 改名 |
| `lhb_quant_sector` | `quant_sector_rotation` | 改名 |
| `lhb_reverse_institutional` | — | **缺失** |
| `lhb_seat_profile` | — | **缺失** |
| `lhb_consensus` | — | **缺失** |

龙虎榜 5 个子策略被压缩为 2 个。

**影响**：改名本身可接受（更简洁），但设计文档里的配置项键名、迁移 SQL 表名引用、测试文件命名、权重分配表全部对不上。三个缺失的子策略中，`lhb_reverse_institutional`（机构恐慌反向抄底）是唯一不依赖回测结果、可以立即实现的一个，设计文档第 4.5 节已明确它的触发条件和 9:25 集合竞价判断时点。

**修复建议**：二选一，不要两边都留：
- **方案 A**：以代码为准，更新设计文档的 ID 与策略清单，并明确说明为何合并龙虎榜子策略、三个缺失策略是否还要做
- **方案 B**：以文档为准，把代码 ID 改回长名并补齐三个子策略

建议方案 A —— 代码已经写了，文档更容易改。但要在文档里留下决策记录，说明龙虎榜从 5 个合并为 2 个的理由。

---

### 问题 5：聚合器引入分数归一化，改变了现有六策略的相对强度

**位置**：`src/stock_ai_agent/strategy.py:196-199`

**现状**：新增 `legacy_aggregation` 开关与归一化逻辑：

```python
normalized_score = signal.score if legacy_aggregation else max(
    Decimal("-1"),
    min(Decimal("1"), signal.score / Decimal("2") if signal.score.copy_abs() > 1 else signal.score),
)
```

非 legacy 模式下 score 被压缩到 [-1, 1]。

**后果**：现有策略的分数量级差异被抹平。举例：
- `technical_composite` 满分 6.0 → 归一化后 1.0
- `technical_composite` 得分 2.0 → 归一化后 1.0（**与满分相同**）
- `drawdown_control` 止损 -3.0 → 归一化后 -1.0
- `mean_reversion` 买入 1.5 → 归一化后 0.75

`score > 1` 时除以 2 再截断到 1，意味着**所有 score ≥ 2 的信号强度完全相同**。技术面"六维全多得 6 分"和"勉强得 2 分"在聚合时权重一样，原本设计的强弱梯度失效。

这个改动不在设计文档范围内，且影响的是**已经跑通的现有六个策略**，不只是新策略。

**修复建议**：确认这是有意为之。如果目的是防止某个策略的极端分数主导聚合，更合适的做法是按各策略的理论分数区间做**线性缩放**而非截断：

```python
# 例：technical_composite 区间 [-7.5, 6.0]，按上界缩放
normalized = signal.score / STRATEGY_SCORE_SCALE[signal.strategy_id]
```

这样保留强弱梯度，又统一了量纲。

---

## 🟡 待确认问题

### 待确认 1：三段式架构是否已实现

**背景**：设计文档第五节要求盘前（9:05 拉韩股 + 9:25 检查集合竞价低开）、盘中（9:30-15:00）、盘后（19:00 龙虎榜 + 19:30 期指）三段式运行。

**现状**：`monitor.py` 改动 130 行，commit message 提到 "market-hour scheduling"，但未逐行确认是否包含 `_execute_premarket_task` / `_execute_postmarket_task`，也未确认 `config/default.yaml` 是否有 `premarket_time` / `postmarket_start` / `postmarket_end` 三个新配置项。

**需要确认**：
- 盘前/盘后任务是否已实现，还是只做了盘中时段判断的重构
- 若已实现，`poll_seconds` 是否已从 60 改为 300（设计文档第 5.4 节要求，因为 monitor 需要全天运行）
- 若未实现，四个新策略即使补上逻辑也拿不到数据（数据拉取依赖盘前/盘后任务）

---

### 待确认 2：`strategy_profiles` 表下发档案能否绕过空壳保护

**背景**：`resolve_strategy_profile`（`strategy_runtime.py:60-75`）优先读数据库档案，配置只作 fallback：

```python
profile = store.load_active_strategy_profile(symbol, asset_type)
if not profile:
    return fallback
merged = deepcopy(fallback)
merged.update(profile)
merged["enabled"] = list(profile.get("enabled") or fallback["enabled"])
```

**需要确认**：数据库里的 `strategy_profiles` 记录如果 `enabled` 包含四个空壳策略，是否有任何校验阻止？从代码看没有 —— `merged["enabled"]` 直接取数据库值。这意味着问题 1 的死锁可以通过 Web 界面或直接改库触发，而不只是改配置文件。

如果 Web 端已经提供了策略档案编辑功能（`web_actions.py` 改动 76 行，可能相关），这个风险等级要上调。

---

### 待确认 3：`risk_config.py` 与 `positions.highest_price` 的用途

**背景**：新增了 `src/stock_ai_agent/risk_config.py`（84 行），迁移脚本给 `positions` 加了 `highest_price` 字段，注释写 "Keep the peak unadjusted price needed by trailing-stop risk checks"。

**需要确认**：
- 这是在实现移动止损（trailing stop）吗？设计文档没提这个功能，[`2026-08-21-optimization.md`](../plans/2026-08-21-optimization.md) 里“止盈止损”是列在中期优化第 7 项的
- `risk.py` 改动 75 行是否与此相关，是否会与 `drawdown_control` 策略的止损逻辑重叠或冲突
- 移动止损的阈值是否可配

功能本身合理，但属于设计范围外的新增，需要确认是有意扩展还是顺手加的。

---

### 待确认 4：`legacy_aggregation` 开关的默认值与切换条件

**背景**：问题 5 提到的 `legacy_aggregation` 参数。

**需要确认**：
- 默认值是 `True` 还是 `False`？这决定了归一化是否已经生效
- 由什么控制 —— 配置项、`config_schema_version`（`strategy_runtime.py:49` 出现了 `"config_schema_version": 2`），还是档案字段
- 如果默认走新逻辑，现有六策略的行为已经改变；如果默认 legacy，那新逻辑何时启用

这个开关的存在说明实现方意识到了兼容性问题，但需要明确切换路径。

---

## 修复优先级

### 立即（影响正确性）
1. **问题 2** — 期指策略加入风控集合。一行改动，但不改的话策略语义反了
2. **问题 1** — 空壳策略与 60% 门槛的交互。当前未触发，但要加保护，避免有人启用后系统静默停止交易
3. **待确认 2** — 确认 `strategy_profiles` 下发路径是否有校验，这决定问题 1 的实际风险等级

### 高（阻塞后续开发）
4. **问题 3** — 补建六张数据表。不建表，四个策略永远是空壳
5. **待确认 1** — 确认三段式架构状态。这决定数据能否自动流入

### 中（一致性与可维护性）
6. **问题 4** — 统一策略 ID 命名，明确龙虎榜合并决策
7. **问题 5 / 待确认 4** — 确认归一化是否有意，明确 `legacy_aggregation` 切换路径
8. **待确认 3** — 确认移动止损是否为计划内功能，检查与 `drawdown_control` 是否冲突

---

## 值得肯定的部分

以下是设计文档没有细化、实现方补上的合理工程，建议保留并补进设计文档：

- **策略档案持久化**（`strategy_profiles` + `strategy_catalog.py`）：比设计文档里"改 YAML 配置"的方案灵活得多，支持按标的/资产类型下发不同策略组合，还带 `confirmed_by` / `confirmed_at` 的人工确认元数据
- **按资产类型分流权重**（`weights_by_asset_type`）：ETF 和个股用不同权重，设计文档里没想到这一层
- **多市场交易日历**（`trading_calendar.market` 字段）：为韩股/美股日历预留了位置，比设计文档只考虑 A 股更前瞻
- **观察池生命周期**（`lifecycle_status` / `trading_enabled` / `dormant_since`）：把"观察中"和"可交易"分开，这是设计文档没有的概念，但对风控有实际价值
- **原始行情事件保留 7 天**（`market_quote_events`）：便于排查数据源与限流问题，正对着 [`2026-08-21-optimization.md`](../plans/2026-08-21-optimization.md) 里可观测性不足的问题
- **迁移脚本质量**：开头写明"需先做 mysqldump 备份、不要整段粘贴执行"，结尾带 `SHOW CREATE TABLE` 验证语句，这是很专业的做法
