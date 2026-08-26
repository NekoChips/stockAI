# StockAI 优化清单

| 项 | 值 |
|---|---|
| 分析日期 | 2026-08-21 |
| 分析分支 | `develop` (commit `7ea3e4e`) |
| 代码规模 | 约 6279 行 Python，27 个模块，28 个测试文件 |
| 分析方式 | 静态代码阅读 |
| 覆盖维度 | 架构、性能、可靠性、可观测性、测试、部署、代码质量、UX |

> **前提说明**：本次分析未能执行代码（环境 PATH 中无 `python`），因此所有性能结论是**结构性推断**（查询次数、算法复杂度），而非实测耗时。在投入缓存与连接池改造前，建议先对着有数据的库 profile 一次真实的 `/api/dashboard` 请求，确认时间实际花在哪里。
>
> 本文档只覆盖优化项，不含安全问题。安全问题见 `CODE_REVIEW_ISSUES.md`。

## 项目现状

这个项目在同等规模里算状态良好。数据源 fallback、`extends` 配置分层、带 mock/MySQL 双实现的 `MarketDataStore` 协议、分布式 monitor 锁，都是实打实的设计工作。下面的问题主要关于**规模与可运维性**，而非正确性。

---

## 快赢清单（合计约 1 天）

低风险，且正对着最尖锐的性能边缘。建议先做这一组。

| # | 问题 | 位置 | 工作量 |
|---|---|---|---|
| 3 | Dashboard 基准数据 N+1 | `web.py:137-140` | 1 小时 |
| 4 | 循环内重复查询快照 | `monitor.py:191` | 15 分钟 |
| 2 | MySQL 无连接池 | `storage/mysql.py:500-540` | 半天 |
| 10 | 依赖未锁版本 | `pyproject.toml`、`Dockerfile` | 2 小时 |
| 11 | Docker 以 root 运行 | `Dockerfile` | 2 小时 |

---

## 🔴 高优先级

### 1. `web.py` 1079 行混合五种职责

**位置**：`src/stock_ai_agent/web.py`

**问题**：payload 构建、HTTP 路由、Basic Auth、响应编码，以及一整个内联的 HTML/CSS/JS 看板（约 500-1000 行）全在一个文件里。`do_GET` 是一条约 15 分支的 `if/elif` 字符串前缀匹配链（`web.py:380-439`），加一个路由就要改这个不断长大的条件。

**修复方向**：

```
src/stock_ai_agent/web/
├── __init__.py          # serve_dashboard 入口
├── payloads.py          # build_dashboard_* 系列函数
├── routes.py            # 路由表 + handler
├── auth.py              # Basic Auth
└── static/
    └── dashboard.html   # 从磁盘加载，不再内联
```

路由表替代前缀匹配：

```python
ROUTES = [
    (re.compile(r"^/healthz$"), "GET", handle_healthz),
    (re.compile(r"^/api/dashboard$"), "GET", handle_dashboard),
    (re.compile(r"^/api/instruments/(?P<symbol>[^/]+)/detail$"), "GET", handle_instrument_detail),
    (re.compile(r"^/api/watchlist$"), "POST", handle_watchlist_add),
    (re.compile(r"^/api/watchlist/(?P<symbol>[^/]+)$"), "DELETE", handle_watchlist_remove),
]

def _dispatch(self, method: str, path: str):
    for pattern, verb, handler in ROUTES:
        if verb != method:
            continue
        match = pattern.match(path)
        if match:
            return handler(self, **match.groupdict())
    self.send_error(404, "Not Found")
```

**工作量**：1-2 天

**为什么优先**：这是杠杆最高的一项，它让看板能独立于服务器测试，后续所有 Web 层改动都受益。

---

### 2. MySQL 无连接池，每次查询新开 TCP 连接

**位置**：`src/stock_ai_agent/storage/mysql.py:500-540` 附近

**问题**：`_execute`、`_executemany`、`_fetchone`、`_fetchall` 各自调用 `self._connect()`，做一次完整的 `pymysql.connect()` 后在 `finally` 里关闭。一个 `/api/dashboard` 请求会扇出几十次连接，每次都付 TCP 握手加 MySQL 认证握手的代价。

**修复方向**：

```python
from dbutils.pooled_db import PooledDB

class MySQLMarketDataStore:
    def __init__(self, connection: MySQLConnectionConfig | None) -> None:
        ...
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            with self._initialize_lock:
                if self._pool is None:
                    import pymysql
                    self._pool = PooledDB(
                        creator=pymysql,
                        maxconnections=10,
                        mincached=2,
                        blocking=True,
                        ping=1,          # 取用前 ping 一次
                        host=self.host, port=self.port,
                        user=self.username, password=self.password,
                        database=self.database, charset="utf8mb4",
                    )
        return self._pool

    @contextmanager
    def _connect(self) -> Iterator:
        conn = self._get_pool().connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()   # 归还池，不是真关
```

需要在依赖里加 `DBUtils`。不想引入依赖的话，可以用 `threading.local()` 做一个简易线程本地连接缓存。

**工作量**：半天

**为什么优先**：这大概是可获得的最大单点延迟收益。

---

### 3. Dashboard 基准数据 N+1 查询

**位置**：`src/stock_ai_agent/web.py:137-140`

**问题**：

```python
benchmark_bars = {
    item.symbol: store.load_bars(item.symbol, interval="daily")
    for item in config.benchmarks
}
```

5 个基准 = 5 次独立查询，各开一条连接，且每次都拉**整段**日线历史，无 limit 无日期过滤。

`load_bars_batch` 在 `storage/mysql.py:202` 已经存在且正好做这件事，只是这里没用上。

**修复方向**：

```python
benchmark_symbols = [item.symbol for item in config.benchmarks]
if hasattr(store, "load_bars_batch"):
    benchmark_bars = store.load_bars_batch(
        benchmark_symbols,
        interval="daily",
        start=selected_start,
        end=selected_end,
    )
else:
    benchmark_bars = {s: store.load_bars(s, interval="daily") for s in benchmark_symbols}
```

如果 `load_bars_batch` 当前不支持日期区间参数，一并补上 —— 只加载区间内的数据比加载全量再在 Python 里过滤要好得多。

**工作量**：1 小时

**为什么优先**：性价比最高的一项，改动小、收益直接。

---

### 4. `load_portfolio_snapshots()` 在循环内被反复调用

**位置**：`src/stock_ai_agent/monitor.py:191`

**问题**：

```python
for instrument in universe.instruments:
    ...
    snapshots = self.store.load_portfolio_snapshots() if hasattr(...) else []
    historical_peak = max((value for _, value in snapshots), default=...)
```

snapshots 在整个循环里是不变量，却每个标的都重查一次全表。2 个标的看不出来，50 个标的就是每 60 秒 50 次全表读。

**修复方向**：提到循环外。

```python
snapshots = self.store.load_portfolio_snapshots() if hasattr(self.store, "load_portfolio_snapshots") else []
historical_peak = max(
    (value for _, value in snapshots),
    default=self.config.paper_account.initial_cash,
)

for instrument in universe.instruments:
    ...
    quant_context = QuantContext(
        histories=histories,
        current_weights=current_weights,
        peak_values={instrument.symbol: max(historical_peak, current_value)},
        current_values={instrument.symbol: current_value},
    )
```

注意 `current_value = portfolio.total_asset()` 会随本轮成交变化，这个应保留在循环内；只有 `snapshots` 和 `historical_peak` 提出去。

**工作量**：15 分钟

---

### 5. 数值全部存为 `VARCHAR(40)`

**位置**：`src/stock_ai_agent/storage/mysql.py:77-141`

**问题**：`bars`、`positions`、`market_quotes`、`portfolio_snapshots` 的价格、成交量、权重全部存成字符串。保 `Decimal` 精度的动机是合理的，但代价很重：

- SQL 里无法做任何算术、聚合或范围过滤，每次计算都得把整行拉进 Python
- `timestamp_value VARCHAR(40)` 无法为 `BETWEEN` 日期查询走索引
- 无法建有意义的价格或日期区间索引

**修复方向**：迁到 `DECIMAL(20,6)` + `DATETIME`。PyMySQL 返回 `DECIMAL` 列就是 Python `Decimal`，精度不丢。

```sql
CREATE TABLE bars_v2 (
    symbol VARCHAR(32) NOT NULL,
    interval_name VARCHAR(16) NOT NULL,
    timestamp_value DATETIME NOT NULL,
    open_price DECIMAL(20,6) NOT NULL,
    high_price DECIMAL(20,6) NOT NULL,
    low_price DECIMAL(20,6) NOT NULL,
    close_price DECIMAL(20,6) NOT NULL,
    volume DECIMAL(24,4) NOT NULL,
    amount DECIMAL(24,4) NOT NULL,
    source VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, interval_name, timestamp_value),
    INDEX idx_symbol_ts (symbol, timestamp_value)
);
```

迁移路径：建 v2 表 → 双写 → 后台回填历史 → 切读 → 删旧表。

**工作量**：2-3 天（含迁移路径）

**判断**：当前数据量小可以缓，但这是未来查询性能的天花板。建议当作独立项目排期，不要塞进日常迭代。

---

### 6. 可观测性基本空白

**位置**：全项目

**问题**：

- 全项目 9 处 `logging` 引用，只有 `monitor.py` 有 logger
- `app.py:296-318` 的 CLI 路径用 `print()` 输出到 stdout/stderr
- 没有指标、没有结构化日志、没有关联 ID
- `/healthz` 只探活，**不检查 MySQL 可达性或行情源状态** —— 一个已经静默失去数据源的 monitor 仍然报告健康

**修复方向**：

入口配置结构化日志：

```python
# app.py
import logging, json, sys

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def _configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
```

把 `print` 全部转成 logger 调用。补关键路径日志：策略决策、订单执行、风控拒绝、数据源切换、限流触发。

加真正的就绪检查：

```python
def handle_readyz(self) -> None:
    checks = {}
    try:
        store.ping()                      # 需在 store 上新增
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"failed: {exc}"

    last_quote_age = store.last_quote_age_seconds()
    checks["market_data"] = "ok" if last_quote_age is not None and last_quote_age < 600 else "stale"

    healthy = all(v == "ok" for v in checks.values())
    self.send_response(200 if healthy else 503)
    ...
```

`docker-compose.yml` 的 healthcheck 指向 `/readyz` 而非 `/healthz`。

**工作量**：1-2 天

**为什么优先**：没有这个，生产排障基本靠猜。

---

## ⚠️ 中优先级

### 7. 数据源没有熔断器

**位置**：`src/stock_ai_agent/data/providers.py:107-108`

**问题**：`FallbackHistoryDataProvider._call` 有指数退避重试，这是对的，但没有熔断器。AlphaFeed 被限流时，每个标的仍然要走完整个 provider 链、烧完重试预算才落到 AKShare。

按 README 记录的 Free 套餐限制（8 次/60 秒、相邻请求最少 7.5 秒），熔断后快速失败到 AKShare 并冷却一段时间，能明显改善故障期吞吐。

**修复方向**：

```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 120.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._opened_at: float | None = None

    def is_open(self, now: float) -> bool:
        if self._opened_at is None:
            return False
        if now - self._opened_at >= self.cooldown_seconds:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self, now: float) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = now
```

每个 provider 一个 breaker，`_call` 里先查 `is_open()`，开路就直接跳到下一个 provider。

**工作量**：1 天

---

### 8. `macd()` 是 O(n²)

**位置**：`src/stock_ai_agent/features.py:35-51`

**问题**：

```python
for index in range(26, len(items) + 1):
    subset = items[:index]
    fast = ema(subset, 12)
    slow = ema(subset, 26)
```

每轮迭代重新切片并从头计算两条 EMA。按配置的 `monitor_history_limit: 80`，每标的每轮约 4600 次 Decimal 运算。现在能忍，规模上去就是二次爆炸。

另外 `sma()` 和 `ema()` 每次调用都做 `list(values)`，而 `build_features` 对同一组 closes 调了七次。

**修复方向**：单次增量遍历，维护运行态 EMA。

```python
def _ema_series(values: List[Decimal], period: int) -> List[Decimal]:
    """返回从第 period-1 个位置开始的 EMA 序列，单次遍历。"""
    if len(values) < period:
        return []
    multiplier = Decimal("2") / Decimal(period + 1)
    result = sum(values[:period], Decimal("0")) / Decimal(period)
    series = [result]
    for value in values[period:]:
        result = (value - result) * multiplier + result
        series.append(result)
    return series


def macd(values: Iterable[Decimal]) -> Optional[dict]:
    items = list(values)
    if len(items) < 35:
        return None
    fast_series = _ema_series(items, 12)
    slow_series = _ema_series(items, 26)
    # 对齐：fast 从 index 11 开始，slow 从 index 25 开始
    offset = 26 - 12
    macd_line_series = [f - s for f, s in zip(fast_series[offset:], slow_series)]
    signal_series = _ema_series(macd_line_series, 9)
    if not signal_series:
        return None
    line = macd_line_series[-1]
    signal = signal_series[-1]
    return {"macd": line, "macd_signal": signal, "macd_histogram": line - signal}
```

改完务必用现有测试校验数值一致（EMA 对齐容易错位）。顺手让 `build_features` 只把 closes 转 list 一次并复用。

**工作量**：2 小时

---

### 9. 完全没有缓存层

**位置**：`src/stock_ai_agent/web.py` — `build_dashboard_payload`

**问题**：每个请求都从全量历史重算基准对比、盈亏日历、排行榜、周期收益。而这些数据最多每个轮询周期（60 秒）变一次。

**修复方向**：按 `(as_of, performance_start, performance_end)` 做 TTL 缓存。

```python
from threading import Lock
import time

class TTLCache:
    def __init__(self, ttl_seconds: float = 45.0) -> None:
        self.ttl = ttl_seconds
        self._entries: dict[tuple, tuple[float, Any]] = {}
        self._lock = Lock()

    def get_or_compute(self, key: tuple, compute) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._entries.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = compute()          # 锁外计算，避免阻塞其他 key
        with self._lock:
            self._entries[key] = (now, value)
            if len(self._entries) > 64:      # 简单上界，防止无限增长
                oldest = min(self._entries, key=lambda k: self._entries[k][0])
                del self._entries[oldest]
        return value
```

TTL 建议略小于 `poll_seconds`（如 45 秒），保证看板不会显示超过一个轮询周期的旧数据。写操作（增删观察池、确认回测）后应主动失效。

**工作量**：半天

**注意**：先 profile 再决定。如果瓶颈其实在连接开销（问题 2），缓存的收益会被高估。

---

### 10. 依赖未锁版本

**位置**：`pyproject.toml:6-10`、`Dockerfile:17-19`

**问题**：

```
alphafeed>=0.1.4
akshare>=1.15
PyMySQL>=1.1
```

开放下界，`akshare` 又频繁发布 breaking change。更要紧的是 Dockerfile 构建时安装且无 lockfile —— **同一个 commit 的两次构建可能产出不同镜像**。

另外 Dockerfile 重复了一遍依赖列表而不是从 `pyproject.toml` 安装，两处会漂移。

**修复方向**：

`pyproject.toml` 锁到确切版本：

```toml
dependencies = [
  "alphafeed==0.1.4",
  "akshare==1.15.60",
  "PyMySQL==1.1.1",
]
```

Dockerfile 改为从 `pyproject.toml` 安装，消除重复：

```dockerfile
COPY pyproject.toml README.md ./
COPY src ./src
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" .; \
    else \
        python -m pip install --no-cache-dir .; \
    fi
```

进一步可以生成 `requirements.lock`（`pip freeze` 或 `uv pip compile`）并在 CI 校验。

**工作量**：2 小时

---

### 11. Docker 以 root 运行且无多阶段构建

**位置**：`Dockerfile`

**问题**：没有 `USER` 指令，容器以 root 运行。另外 `akshare` 拉进 pandas/numpy/scipy，镜像偏大。

`docker-compose.yml` 本身写得不错 —— YAML anchors、日志轮转、healthcheck、`stop_grace_period` 都在。

**修复方向**：

```dockerfile
FROM python:3.12-slim AS builder
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ARG PIP_INDEX_URL
COPY pyproject.toml README.md ./
COPY src ./src
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir --index-url "$PIP_INDEX_URL" .; \
    else \
        pip install --no-cache-dir .; \
    fi

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin stockai
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY config ./config
USER stockai
ENTRYPOINT ["python", "-m", "stock_ai_agent.app"]
CMD ["monitor", "--config", "config/release.container.yaml"]
```

**工作量**：2 小时

---

### 12. `_execute_iteration` 约 120 行

**位置**：`src/stock_ai_agent/monitor.py:120-236`

**问题**：一个函数里处理市场时段判断、universe 构建、批量与单标的取价、特征构建、策略评估、风控检查、broker 执行、持久化。内含六个独立的 `try/except Exception` + `noqa: BLE001`。

那些解释每处异常抑制原因的注释是好实践，值得保留；但函数需要拆解。

**修复方向**：

```python
def _execute_iteration(self, ...) -> MonitorIterationResult:
    market_data = self._load_market_data(universe, trade_date)      # 取价 + K线 + 告警收集
    for instrument in universe.instruments:
        outcome = self._evaluate_symbol(instrument, market_data, portfolio, context)
        if outcome.order:
            self._execute_decision(outcome, broker, trade_date, portfolio)
    return self._finalize_iteration(...)
```

拆分时保留原有的异常隔离语义 —— 单个标的失败不应中断整轮。

**工作量**：1 天

---

### 13. 测试缺集成、性能、压力覆盖

**位置**：`tests/`、`.github/workflows/publish-image.yml`

**问题**：

- 28 个测试文件对 27 个模块，单元广度不错，但**全部针对 `MockMarketDataStore`**
- 没有跑真实 MySQL schema 的测试。`storage/mysql.py:160-181` 的 `_migrate_market_quotes` 升级路径从未被真实 MySQL 验证 —— 它显式捕获 `AttributeError` 来兼容"轻量单测 cursor"，恰好印证了这点
- 没有配置覆盖率测量
- CI 跑 `python -m unittest discover`，尽管 `pyproject.toml` 配的是 pytest

**修复方向**：

CI 加 MySQL service container：

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: test
          MYSQL_DATABASE: stockai_test
        ports: ["3306:3306"]
        options: >-
          --health-cmd="mysqladmin ping -ptest"
          --health-interval=10s --health-timeout=5s --health-retries=10
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --upgrade pip && python -m pip install . coverage
      - name: Unit tests with coverage
        run: |
          python -m coverage run -m pytest
          python -m coverage report --fail-under=70
      - name: Integration tests against real MySQL
        env:
          STOCK_AI_MYSQL_HOST: 127.0.0.1
          STOCK_AI_MYSQL_DATABASE: stockai_test
          STOCK_AI_MYSQL_USERNAME: root
          STOCK_AI_MYSQL_PASSWORD: test
        run: python -m pytest tests/integration -v
```

优先补的集成测试：
- schema 初始化 + `_migrate_market_quotes` 升级路径
- `save_portfolio` / `load_portfolio` 往返
- `acquire_monitor_lock` 的互斥（两个连接抢锁）
- 端到端：看多行情 + 空账户 → 断言产生买入订单

统一测试运行器为 pytest（配置已在 `pyproject.toml`）。

**工作量**：2-3 天

---

### 14. 八处用 `hasattr` 做能力探测

**位置**：`monitor.py`、`web.py` 多处

**问题**：`hasattr(self.store, "load_bars_batch")`、`hasattr(self.store, "save_quotes")`、`hasattr(store, "instrument_catalog_status")` 等散布各处。

`monitor.py:40-72` 的 `PaperTradingStore` Protocol 已经是正确机制，这些可选方法应该声明在上面，让类型检查器强制而不是运行时探测。

**修复方向**：把可选方法加进 Protocol，并在一个基类里给默认实现：

```python
class PaperTradingStore(Protocol):
    def load_bars(self, symbol: str, interval: str = "daily", limit: int | None = None) -> List[Bar]: ...
    def load_portfolio(self, initial_cash: Decimal) -> Portfolio: ...
    # 原先靠 hasattr 探测的，改为显式声明
    def load_bars_batch(self, symbols: List[str], interval: str = "daily", limit: int | None = None) -> Dict[str, List[Bar]]: ...
    def save_quotes(self, quotes: List[Quote]) -> None: ...
    def load_portfolio_snapshots(self) -> List[tuple[date, Decimal]]: ...
    def compact_watch_decisions(self) -> None: ...
    def prune_market_quotes(self, trade_date: date) -> None: ...


class BaseStore:
    """给可选能力提供 no-op 默认实现，两个 store 都继承它。"""
    def load_bars_batch(self, symbols, interval="daily", limit=None):
        return {s: self.load_bars(s, interval, limit) for s in symbols}

    def save_quotes(self, quotes): pass
    def compact_watch_decisions(self): pass
    def prune_market_quotes(self, trade_date): pass
```

**工作量**：半天

---

### 15. Web 线程无上界

**位置**：`src/stock_ai_agent/web.py` — `ThreadingHTTPServer`

**问题**：每连接一个线程，无上界。配合无连接池（问题 2），一波 dashboard 请求能同时耗尽线程和 MySQL 连接。

**修复方向**：短期用带上界的线程池 mixin；长期换成真正的 WSGI/ASGI 服务器（如 `waitress`，纯 Python 无编译依赖）。

```python
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer
from socketserver import ThreadingMixIn

class BoundedThreadingHTTPServer(HTTPServer):
    daemon_threads = True

    def __init__(self, *args, max_workers: int = 16, **kwargs):
        super().__init__(*args, **kwargs)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def process_request(self, request, client_address):
        self._executor.submit(self._handle_request_thread, request, client_address)

    def _handle_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self):
        super().server_close()
        self._executor.shutdown(wait=True)
```

线程池大小应与连接池上限匹配（两者都设 10-16 比较协调）。

**工作量**：1 天

---

## 🔧 低优先级

### 16. `config/default.yaml` 实际是 JSON

`config.py:219` 用 `json.loads` 解析这个 `.yaml` 文件，内容也是 JSON。合法但误导。改名为 `.json`，或引入 YAML 解析器（YAML 支持注释，对配置文件是加分项）。

### 17. 配置无 schema 校验

`load_config` 用散布在约 90 行里的 `.get()` 默认值读取键。配置键拼错会**静默回落到默认值**而不是报错。建议加一个 dataclass 驱动的校验步骤，在启动时暴露错误。

### 18. 聚合逻辑里的魔数

`strategy.py:196-217` 硬编码 `Decimal("1.5")`、`Decimal("-1.5")`、`Decimal("0.20")`、`Decimal("5")`。各个子策略都正确地从配置读阈值，聚合器的决策边界也该可配：

```yaml
strategy:
  aggregator:
    buy_score_threshold: "1.5"
    exit_score_threshold: "-1.5"
    conflict_max_weight: "0.20"
    confidence_divisor: "5"
```

### 19. `ANALYSIS_START_DATE` 硬编码

`web.py:31` 的 `ANALYSIS_START_DATE = date(2026, 1, 1)` 是模块级常量，调整要改代码重新发版。移到配置里。

### 20. 混合语言标识符与消息

代码和注释是英文，所有面向用户的字符串和错误消息是中文。对目标用户是一致且合适的，但没有 i18n 间接层，API 是单语言的。除非国际化是目标，否则不用动。

### 21. 错误消息泄露内部细节

`web.py:389` 和 `web.py:427` 的 `_send_error(self, 400, str(exc))` 把原始异常文本转发给 API 客户端。改为记录详情、返回通用消息：

```python
except ValueError as exc:
    logger.warning("dashboard 参数无效：%s", exc)
    _send_error(self, 400, "请求参数无效。")
```

### 22. `optimize_strategy_parameters` 三层嵌套网格搜索

`backtest.py:95-117`，27 种组合各跑一次完整的 Decimal 组合模拟。当前规模没问题，网格变大再用 `multiprocessing` 并行。

---

## 建议执行顺序

### 第一阶段：快赢（约 1 天）

低风险，对着最尖锐的性能边缘。

1. 问题 3 — 修 `web.py:137` 的 N+1（1 小时）
2. 问题 4 — 把 snapshot 加载提出 `monitor.py:191` 的循环（15 分钟）
3. 问题 2 — 加 MySQL 连接池（半天）
4. 问题 10 — 锁定依赖版本、消除 Dockerfile 重复（2 小时）
5. 问题 11 — Docker 加非 root 用户（2 小时）

### 第二阶段：结构与可运维性（约 1 周）

6. 问题 1 — 拆分 `web.py`（1-2 天）
7. 问题 6 — 补结构化日志与 `/readyz`（1-2 天）
8. 问题 9 — 引入缓存层（半天，**先 profile**）
9. 问题 8 — 重写 `macd()` 为单次遍历（2 小时）

### 第三阶段：健壮性（约 1 周）

10. 问题 12 — 拆解 `_execute_iteration`（1 天）
11. 问题 7 — 数据源熔断器（1 天）
12. 问题 14 — Protocol 替代 `hasattr` 探测（半天）
13. 问题 15 — Web 线程池上界（1 天）
14. 问题 13 — CI 集成测试 + 覆盖率门禁（2-3 天）

### 独立项目

15. 问题 5 — `VARCHAR` → `DECIMAL` 迁移（2-3 天，需要独立排期和迁移路径）

### 随手清理

低优先级的 16-22 项可以在碰到相关代码时顺手处理，不必单独排期。

---

## 前置动作

在开始第二阶段的缓存和连接池工作前，建议先做一次实测：

```bash
# 对着有数据的库 profile 一次真实请求
python -m cProfile -s cumtime -m stock_ai_agent.app web --config config/release.example.yaml
# 另一个终端
curl -s -u user:pass 'http://127.0.0.1:8765/api/dashboard' > /dev/null
```

确认时间实际花在连接建立、SQL 执行，还是 Python 侧计算。这决定了问题 2（连接池）和问题 9（缓存）哪个收益更大。

