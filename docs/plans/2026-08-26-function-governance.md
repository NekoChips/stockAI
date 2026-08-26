# StockAI 重复功能治理实施计划

## 阶段一：测试基线

1. 在 `tests/test_app.py` 增加 `run-once` 使用完整订单状态机的失败测试。
2. 在 `tests/test_monitor.py` 增加 monitor 与单轮执行器共享结果的失败测试。
3. 在 `tests/test_history_sync.py` 增加 CLI/monitor 共享历史同步服务的失败测试。
4. 在 `tests/test_storage_contract.py` 增加 Mock/MySQL 存储契约测试入口。
5. 在 `tests/test_web_spa.py` 增加根路径无 SPA 时返回 503、旧 HTML 不再打包的失败测试。
6. 在 `tests/test_web.py` 增加聚合接口弃用响应行为测试。

## 阶段二：统一交易轮次

1. 新建 `src/stock_ai_agent/trading_round.py`。
2. 将行情读取、历史读取、策略评估、风控、订单状态机和持久化统一放入执行器。
3. monitor 调用执行器，并保留正式日报和实时任务状态语义。
4. `run_once_from_store()` 调用同一执行器，并保留临时运行不写正式日报的语义。
5. 删除 `app.run_once()` 中的简化 `broker.execute()` 路径。
6. 运行交易相关测试并修复回归。

## 阶段三：统一历史同步

1. 在 `src/stock_ai_agent/history_sync.py` 增加观察池历史同步服务。
2. 统一缺失范围、强制刷新、复权/不复权价格轨迹、主备切换和任务状态记录。
3. `app.sync_history()` 改为调用服务。
4. `monitor._sync_watchlist_history()` 改为调用服务并转换 warnings。
5. 保留指数历史同步独立边界，但复用公共 provider 调用和错误分类。
6. 运行历史同步测试。

## 阶段四：统一存储契约

1. 删除 `monitor.py` 内的 `PaperTradingStore` 协议。
2. monitor 和应用服务改用 `MarketDataStore` 或细粒度能力协议。
3. 移除可由正式协议保证的方法上的 `hasattr()` 分支。
4. 对 Mock/MySQL 执行相同的契约测试。

## 阶段五：Web 清理

1. 删除 `src/stock_ai_agent/dashboard.html`。
2. 删除 `render_dashboard_html()` 及 `web.py`、`web_server.py` 的兼容导出。
3. 根路径无 SPA 时返回 503，不再回退旧页面。
4. 从 `pyproject.toml` 删除旧 HTML 包数据声明。
5. `/api/dashboard` 与 `/api/dashboard/orders` 增加弃用响应头和日志。
6. 删除客户端和测试中的旧聚合接口依赖。

## 阶段六：React 收口与验收

1. 统一看板刷新和缓存失效函数。
2. 策略保存/确认后失效 `strategies`、`strategy-readiness` 和必要的 `overview`。
3. 检查加载、空状态、失败重试、键盘焦点、图表图例和响应式布局。
4. 执行 `PYTHONPATH=src python3 -m unittest discover -s tests -q`。
5. 执行 `git diff --check`。
6. 在具备 npm 的环境执行 `npm run build`。
7. 进行代码复核并输出 `review.md`。
