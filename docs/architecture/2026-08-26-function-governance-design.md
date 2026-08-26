# StockAI 重复功能治理与模块拆分设计

## 1. 文档状态

- 状态：待确认设计
- 目标分支：`codex-neko`
- 设计范围：前端唯一入口、交易执行、历史数据同步、存储契约、Web 接口、供应商容错
- 本阶段：只定义设计与迁移边界，不改变业务代码

## 2. 问题结论

当前重复问题不是单一文件问题，而是多个入口分别保留了同一份业务规则：

1. `dashboard.html` 与 React 页面同时实现交易看板、回测、策略、日报、标的详情和观察池操作。
2. `app.run_once()` 与 `RealTimePaperTradingMonitor.run_iteration()` 各自实现策略评估、风控和模拟成交，订单状态机不一致。
3. `app.sync_history()` 与 monitor 的 `_sync_watchlist_history()` 各自实现历史 K 线同步，数据覆盖、强制刷新和任务状态规则不一致。
4. `PaperTradingStore` 与 `MarketDataStore` 重复描述存储能力，容易因新增方法而漂移。
5. React 使用拆分接口，但后端仍保留 `/api/dashboard` 一次性聚合接口和未使用的 `/api/dashboard/orders`。
6. `FallbackMarketDataProvider` 与 `FallbackHistoryDataProvider` 有相似的熔断和回退流程，后续规则可能分叉。

## 3. 目标与非目标

### 目标

- React 成为唯一业务前端。
- 所有正式模拟交易都经过同一套订单状态机。
- CLI 单轮运行与实时 monitor 共享同一套交易轮次执行器。
- CLI 和 monitor 共享同一套历史数据同步服务。
- 存储能力只保留一份正式契约，并保持 MySQL 与 Mock 的实现一致。
- 用拆分接口替代一次性 Dashboard 聚合接口，减少无关数据查询。
- 保留 AlphaFeed、AKShare 和其他数据源的可替换性，不改变主备顺序与限流规则。

### 非目标

- 本轮不改变策略指标、仓位阈值和交易规则本身。
- 本轮不切换数据库，不新增备份或发布流程。
- 本轮不重做整套品牌视觉，不增加暗色模式作为额外功能。
- 本轮不删除仍有明确外部调用方的接口，先经过弃用观察期。
- 本轮删除旧 `dashboard.html`，不保留旧页面兜底。

## 4. 总体架构

```text
React SPA (/app)
  ├─ DashboardPage
  ├─ BacktestPage
  ├─ StrategyPage
  ├─ DailyReportPage
  └─ InstrumentDetailPage
          │
          ▼
HTTP 路由层 web_http.py
          │
          ├─ dashboard payload builders
          ├─ web actions
          ├─ trading round executor
          ├─ history sync service
          └─ storage contract
                  │
                  ├─ MySQLMarketDataStore
                  └─ MockMarketDataStore
```

业务规则只允许向下流动：页面调用 API，API 调用应用服务，应用服务调用存储和数据源。页面、CLI 和 monitor 不直接复制业务流程。

## 5. 前端唯一入口设计

### 5.1 页面结构

React 路由继续使用 `/app` 作为唯一业务入口：

- `/app/`：交易看板
- `/app/backtests`：回测记录
- `/app/strategies`：策略中心
- `/app/reports`：日报归档
- `/app/instruments/:symbol`：标的详情

根路径 `/` 在 SPA 构建存在时重定向到 `/app/`；SPA 构建缺失时直接返回 HTTP 503，并返回明确的构建错误信息。

本轮删除 `src/stock_ai_agent/dashboard.html`，同时移除 `render_dashboard_html()` 及相关兼容导出。发布包和本地服务都不再提供旧页面入口。

### 5.2 视觉与交互方向

产品定位：面向股民的 A 股模拟交易执行工作台。

视觉方向：

- 主色：深蓝 `#0F2747`
- 交互蓝：`#1677FF`
- 页面背景：`#F4F7FB`
- 工作区表面：`#FFFFFF`
- 盈利：A 股语义红 `#D9363E`
- 亏损：A 股语义绿 `#16855B`
- 警告：琥珀 `#D89614`
- 主要文字：`#172033`
- 次要文字：`#667085`
- 边框：`#D9E2F0`

字体和数据呈现：

- 页面正文使用系统无衬线字体，优先保证中文可读性。
- 价格、金额、收益率、时间戳使用等宽数字和 `font-variant-numeric: tabular-nums`。
- 代码、策略 ID 和数据源名称使用等宽字体，但不让技术字段压过中文解释。

核心视觉签名：

- 在策略中心保留“数据就绪度”轨道，按 `可交易 / 降级 / 禁止交易` 展示策略输入是否齐全。
- 交易看板首屏先展示账户、执行状态和数据更新时间，再展示图表与长列表。

交互约束：

- 重要状态不能只靠红绿颜色表达，同时显示文字和图标。
- 所有异步按钮必须有 loading、成功和失败状态。
- 空数据必须给出原因和下一步动作。
- 列表超过可视区域时使用分页、折叠或内部滚动，不拉长整页。
- 保持键盘焦点、可访问名称和 `prefers-reduced-motion` 支持。
- 375px、768px、1024px、1440px 四档检查布局，不引入移动端横向滚动。

### 5.3 数据请求策略

- React Query 作为唯一客户端缓存层。
- 同一个查询键只能对应一个 fetcher。
- 页面刷新只失效当前页面相关 query，不再无差别刷新全部页面。
- 看板概览、收益分析、日历分别查询；禁止恢复全量 `/api/dashboard` 请求。
- 策略保存或确认后，同时失效 `strategies`、`strategy-readiness` 和必要的 `overview` 查询。

## 6. 统一交易轮次执行器

新增应用服务，例如：

```text
src/stock_ai_agent/trading_round.py
```

建议职责：

1. 从有效观察池构建交易 universe。
2. 读取历史 K 线、最新行情和外部策略上下文。
3. 解析标的对应的策略组合。
4. 生成技术、量化、外部市场和龙虎榜信号。
5. 聚合信号并记录参与策略、排除策略和归一化权重。
6. 统一执行风险检查。
7. 统一执行订单状态机：创建 → 审批 → 提交 → 尝试成交 → 成交/拒绝/部分成交。
8. 统一记录决策、订单、成交和组合快照。

`run_once()` 只负责准备一次运行所需的输入，并调用该执行器；monitor 的 `run_iteration()` 也调用同一执行器。两者只允许在以下方面不同：

- 是否持续运行
- 是否跳过交易时段限制
- 是否将结果标记为临时运行
- 是否写入正式日报

临时运行不应再复制一套简化成交逻辑。

## 7. 统一历史数据同步服务

新增或扩展：

```text
src/stock_ai_agent/history_sync.py
```

建议提供：

```python
sync_watchlist_history(
    config,
    store,
    provider,
    *,
    as_of,
    force=False,
    minimum_bars=None,
    task_name="watchlist_history",
)
```

服务统一负责：

- 有效观察池解析
- 缺失区间计算
- 前复权、不复权和原始复权因子三套价格轨迹获取
- 主备数据源切换
- 单标的错误隔离
- 写入 `data_sync_status`
- 返回每个标的的同步结果

CLI `sync-history` 与 monitor 只负责调用，不再自行实现循环、范围计算和保存逻辑。

指数同步继续由 `reference_data.sync_benchmark_history()` 管理，与观察池历史 K 线分开，但复用同一个历史同步基础能力和数据源容错组件。

## 8. 统一存储契约

删除 monitor 内部的 `PaperTradingStore` 协议，统一依赖：

```text
src/stock_ai_agent/storage/base.py::MarketDataStore
```

如果完整协议过大，则拆分成能力协议：

- `QuoteStore`
- `BarStore`
- `TradingStore`
- `ReportStore`
- `StrategyStore`
- `ReferenceDataStore`

应用服务通过能力协议声明依赖，禁止使用大量 `hasattr()` 来隐藏协议缺失。Mock 与 MySQL 必须通过同一组契约测试。

## 9. Web 接口退场策略

### 保留并作为正式接口

- `/api/dashboard/overview`
- `/api/dashboard/performance`
- `/api/dashboard/calendar`
- `/api/dashboard/backtests`
- `/api/dashboard/strategies`
- `/api/dashboard/reports`
- `/api/strategy-readiness`
- `/api/instruments/:symbol/detail`
- 观察池、策略、风控和回测操作接口

### 弃用观察

- `/api/dashboard`
- `/api/dashboard/orders`

弃用阶段：

1. 在路由中增加日志和 `Deprecation` 响应头。
2. 观察至少一个发布周期是否仍有访问。
3. 若无访问，删除路由、payload builder、兼容导出和对应测试。

## 10. 数据源容错抽象

保留 AlphaFeed、AKShare、Eastmoney 和 Biying 的独立适配器，因为它们是不同外部协议，不属于重复业务逻辑。

抽取共同的 provider 执行器，统一：

- 熔断
- 冷却
- 主备顺序
- 限流错误识别
- 重试次数
- 来源记录
- 最后成功来源

实时行情和历史 K 线可以使用不同的调用策略，但必须复用同一个错误分类和熔断基础类。

外部市场分析数据继续保持“只参与策略分析，不进入 A 股持仓和收益统计”的边界。

## 11. 实施顺序

### 阶段一：先补测试

- 为 `run_once` 与 monitor 构造同输入同结果测试。
- 为统一历史同步服务补主源、备用源、空数据和部分失败测试。
- 为 MySQL/Mock 增加存储契约测试。
- 为弃用接口增加访问日志测试。

### 阶段二：抽取交易执行器

- 先迁移 monitor，确保现有实时交易行为不变。
- 再迁移 `run_once`。
- 删除旧的简化 broker 调用路径。

### 阶段三：抽取历史同步服务

- 迁移 CLI `sync-history`。
- 迁移 monitor 初始化与后台刷新。
- 保留任务状态和强制刷新语义。

### 阶段四：统一存储契约

- 删除 `PaperTradingStore`。
- 补齐 Mock/MySQL 方法。
- 清理应用层 `hasattr()` 分支。

### 阶段五：Web 与旧接口清理

- 删除 `dashboard.html` 及 `render_dashboard_html()`。
- 删除根路径回退旧页面的分支；SPA 缺失时返回 503。
- 从 Python 包数据和构建检查中移除旧 HTML。
- 增加 `/api/dashboard` 和 `/api/dashboard/orders` 弃用日志。
- 更新测试，并删除旧页面相关兼容导出。

### 阶段六：React 体验收口

- 统一刷新和缓存失效策略。
- 优化策略中心就绪度轨道。
- 检查空状态、错误状态、键盘焦点、移动端布局。
- 执行 React 构建和四档视口检查。

## 12. 验收标准

### 业务一致性

- `run-once` 与 monitor 对同一批输入生成一致的策略、风控和订单结果。
- CLI 和 monitor 对同一标的计算出一致的历史同步范围。
- 所有正式订单都经过完整订单状态机。
- 旧日报不会因新入口再次生成重复记录。

### 架构一致性

- 交易执行逻辑只有一份。
- 历史 K 线同步逻辑只有一份。
- 存储契约只有一份正式定义。
- React 是唯一业务前端。
- 无客户端继续依赖 `/api/dashboard` 聚合接口。

### UI 质量

- 生产根路径进入 React `/app/`。
- `dashboard.html` 不存在，仓库和发布包中只有 React SPA 业务前端。
- SPA 构建缺失时返回 503，不回退到第二套业务页面。
- 375px、768px、1024px、1440px 下无页面级横向溢出。
- 关键操作具有 loading、错误恢复和键盘可达状态。
- 收益、亏损、降级和禁止交易状态同时具备文本语义。

## 13. 待确认项

在开始实现前，需要确认以下默认决策：

1. 是否确认 `run-once` 必须与实时 monitor 共用完整订单状态机？
2. 是否没有外部系统依赖 `/api/dashboard` 和 `/api/dashboard/orders`，可以进入弃用观察？
3. 是否接受先做后端统一，再做 React 与旧接口清理的分阶段提交方式？

除以上三项外，本设计默认采用前述建议，不再新增产品能力。
