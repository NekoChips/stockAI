# StockAI 新策略设计文档

| 项 | 值 |
|---|---|
| 设计日期 | 2026-08-21 |
| 目标分支 | `develop` |
| 新增策略 | 3 大类，9 个子策略 |
| 架构变更 | 盘前/盘后任务，标的分类，回测模块 |
| 预计工作量 | 3-4 周（分三阶段） |

---

## 一、概述

### 1.1 策略分类

本次新增 **3 大策略，包含 9 个子策略**：

| 策略 ID | 类型 | 权重建议 | 数据源 | 时效 |
|---|---|---|---|---|
| **策略 1：期指情绪对冲** | 风控 | 0.25 | 中金所期指持仓 | T 日 19:30 → T+1 日 |
| **策略 2：外围市场情绪** | 方向 | 0.20 | 美股+韩股 | T-1 美股 + T 日韩股 9:05 |
| **策略 3：龙虎榜系列** | 方向 | 0.30 | 沪深交易所龙虎榜 | T 日 19:00 → T+1 日 |
| 3A - 跟单策略 | 方向 | 0.10 | 明星席位买入 | |
| 3B - 反向策略 | 方向 | 0.05 | 机构恐慌卖出 | |
| 3C - 席位画像 | 方向 | 0.08 | 历史胜率统计 | |
| 3D - 游资机构共振 | 方向 | 0.04 | 多方一致买入 | |
| 3E - 量化席位监控 | 方向 | 0.03 | 量化板块操作 | |

**与现有 6 策略的关系**：

现有策略权重合计 1.30，新增策略权重合计 0.75，**总权重 2.05**。聚合时会归一化，实际各策略占比：

- 现有 6 策略占比 ≈ 63%
- 新增 3 策略占比 ≈ 37%

**策略 1（期指）是风控类**，需加入 `strategy.py:184` 的硬编码集合。

---

### 1.2 架构变更概览

**当前架构**：monitor 只在盘中（9:30-15:00）每 60 秒轮询。

**目标架构**：三段式全天候运行。

```
09:05 盘前任务 → 拉韩股开盘数据、读取昨夜期指/龙虎榜数据
  ↓
09:30-15:00 盘中轮询 → 现有逻辑 + 使用盘前数据生成的信号
  ↓
19:00-20:00 盘后任务 → 拉龙虎榜、期指持仓、日报归档
```

**实现方式**（两个方案，建议方案 1）：

**方案 1（轻量改造）**：扩展 `monitor.py`
- `run_iteration` 开头加时段判断
- 盘前/盘后执行相应任务后返回
- 单服务，配置不变

**方案 2（重量改造）**：三个独立服务
- `monitor --mode=premarket`
- `monitor --mode=trading`
- `monitor --mode=postmarket`
- docker-compose 里三个容器 + cron 调度

本文档按**方案 1**设计，方案 2 的 compose 配置见附录。

---

## 二、策略 1：期指情绪对冲（风控类）

### 2.1 策略定位

**策略 ID**: `futures_position_sentiment`  
**类型**: 风控策略  
**权重建议**: 0.25  

**核心逻辑**：用机构股指期货净持仓作为"市场情绪指标"，调节 A 股现货仓位上限。

- 机构大量做多期指 → 短期过热风险 → **降低现货仓位上限**
- 机构大量做空期指 → 短期超卖机会 → **允许更高现货仓位**

**注意**：这不是真正的对冲（项目无做空能力），而是通过调节现货敞口实现风险缓释。

---

### 2.2 数据需求

**数据源**：中金所每日发布的《股指期货持仓排名》

**关注合约**：IC（中证 500 股指期货）

**关注数据**：
1. **前 10 席位综合**：多头前 10 合计、空头前 10 合计
2. **特定席位**（如中信期货）：该席位的多头持仓、空头持仓

**拉取时点**：T 日 19:30（中金所一般 16:30 发布，留 3 小时缓冲）

**数据时效**：T 日数据用于指导 T+1 日交易

**净持仓占比计算**：
```
净多单占比 = (多头持仓 - 空头持仓) / (多头持仓 + 空头持仓)

综合净持仓 = 前10净持仓 × 70% + 中信净持仓 × 30%
```

---

### 2.3 策略逻辑

**输入**：`综合净持仓占比`（-1 到 +1）

**判定规则**：

| 情况 | 综合净持仓占比 | 解读 | 仓位上限 | Direction | Score |
|---|---|---|---|---|---|
| 过热 | > 60% | 机构大量做多，短期回调风险 | 40% | REDUCE | 0 |
| 中性 | -60% ~ 60% | 多空平衡 | 不施加 | HOLD | 0 |
| 超卖 | < -60% | 机构大量做空，短期反弹机会 | 不施加 | HOLD | 0 |

**设计说明**：
- 期指策略只做"约束"，不做"驱动"。Score 始终为 0，不参与聚合器的正负分冲突判定。
- 过热时以 `REDUCE` 方向触发 `risk_caps`，将仓位上限压到 40%；中性和超卖时返回 `HOLD`，不施加任何上限，由方向性策略自行决定仓位。
- 超卖场景下"允许更高仓位"的效果通过**不压制**实现，而不是主动给出一个宽松上限——后者会绕过聚合器的正常流程。

**Evidence 示例**：
```python
evidence = [
    f"IC 前10净持仓 {top10_ratio:.1%}，中信净持仓 {citic_ratio:.1%}",
    f"综合净持仓 {combined_ratio:.1%}，判定为{'过热' if combined_ratio > 0.6 else '超卖' if combined_ratio < -0.6 else '中性'}",
]
```

**风控策略标记**：需加入 `strategy.py:184` 的集合：
```python
RISK_CONTROL_STRATEGIES = {"volatility_target", "drawdown_control", "futures_position_sentiment"}
```

---

### 2.4 数据表 Schema

**表名**：`futures_positions`

```sql
CREATE TABLE futures_positions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL,
    contract VARCHAR(16) NOT NULL COMMENT 'IF/IC/IH/IM',
    top10_long DECIMAL(20,2) NOT NULL COMMENT '前10多头合计（手）',
    top10_short DECIMAL(20,2) NOT NULL COMMENT '前10空头合计（手）',
    top10_net_ratio DECIMAL(10,6) NOT NULL COMMENT '前10净持仓占比',
    specific_seat_name VARCHAR(128) COMMENT '特定席位名称（如中信期货）',
    specific_seat_long DECIMAL(20,2) COMMENT '特定席位多头',
    specific_seat_short DECIMAL(20,2) COMMENT '特定席位空头',
    specific_seat_net_ratio DECIMAL(10,6) COMMENT '特定席位净持仓占比',
    combined_net_ratio DECIMAL(10,6) NOT NULL COMMENT '加权后综合净持仓占比',
    source VARCHAR(64) NOT NULL COMMENT '数据来源（如manual/cffex_api）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date_contract (trade_date, contract),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股指期货持仓数据';
```

---

### 2.5 数据源接入方案

**现状**：中金所无免费 API，需自建数据源。

**方案 A（推荐）**：人工录入 + 脚本辅助
```python
# scripts/import_futures_positions.py
import sys
from datetime import date
from stock_ai_agent.storage.mysql import MySQLMarketDataStore

def import_positions(trade_date: str, contract: str, 
                     top10_long: float, top10_short: float,
                     citic_long: float, citic_short: float):
    """
    用法：
    python scripts/import_futures_positions.py 2026-08-21 IC 70000 65000 12000 8000
    """
    store = MySQLMarketDataStore(...)
    store.save_futures_positions(
        trade_date=date.fromisoformat(trade_date),
        contract=contract,
        top10_long=Decimal(str(top10_long)),
        top10_short=Decimal(str(top10_short)),
        ...
    )
```

每日 19:30 后从中金所网站复制数据，运行脚本入库。

**方案 B**：爬虫自动化
- 爬取中金所网站持仓排名表格
- 解析 HTML/PDF
- 自动入库

工作量约 2-3 天，且网站结构变化会导致失效。建议先用方案 A，数据量不大（每日一条）。

---

### 2.6 配置项

```yaml
# config/default.yaml
strategy:
  futures_position_sentiment:
    # 合约选择
    contracts: ["IC"]              # 关注的合约，可多个
    
    # 阈值
    bullish_threshold: "0.60"      # 净多单超过此值视为过热
    bearish_threshold: "-0.60"     # 净空单超过此值（负数）视为超卖
    
    # 仓位档位
    overheated_cap: "0.40"         # 过热时的仓位上限
    neutral_cap: "0.60"            # 中性时的仓位上限
    oversold_cap: "0.80"           # 超卖时的仓位上限
    
    # 席位权重
    top10_weight: "0.70"           # 前10综合的权重
    specific_seats_weight: "0.30"  # 特定席位的权重
    specific_seats: ["中信期货"]   # 关注的特定席位列表
```

---

### 2.7 代码结构

**新增文件**：
```
src/stock_ai_agent/
├── quant_strategies.py
│   └── class FuturesPositionSentimentStrategy    # 新增
├── storage/
│   └── mysql.py
│       ├── save_futures_positions()              # 新增
│       └── load_latest_futures_position()        # 新增
```

**修改文件**：
```
src/stock_ai_agent/
├── monitor.py
│   └── run_iteration()                           # 盘前读取期指数据
├── strategy.py
│   └── RISK_CONTROL_STRATEGIES                   # 加入新策略 ID
├── config.py
│   └── StrategyConfig                            # 新增 futures_position_sentiment
```

**测试文件**：
```
tests/
└── test_futures_position_sentiment.py
    ├── test_overheated_scenario()
    ├── test_oversold_scenario()
    └── test_neutral_scenario()
```

---

## 三、策略 2：外围市场情绪（方向类）

### 3.1 策略定位

**策略 ID**: `overseas_market_sentiment`  
**类型**: 方向策略  
**权重建议**: 0.20  

**核心逻辑**：用美股+韩股的隔夜表现预测 A 股当日板块走向，根据标的所属板块给出看多/看空信号。

**板块映射机制**：
- 美股 11 个板块（XLK 科技、XLV 医疗等）→ A 股中证 10 个行业
- 每个观察池标的打上行业标签（自动推断 or 手动配置）
- 查询该行业对应的美股板块昨夜表现 + 韩股同类板块表现
- 综合打分

---

### 3.2 数据需求

#### 3.2.1 美股数据

**数据源**：Yahoo Finance API

**拉取标的**：
1. **三大指数**：`^IXIC`（纳斯达克）、`^GSPC`（标普 500）、`^DJI`（道琼斯）
2. **11 个行业 ETF**：

| ETF 代码 | 板块 | A股对应 |
|---|---|---|
| XLK | Technology | 信息技术 |
| XLV | Health Care | 医药卫生 |
| XLF | Financials | 金融地产 |
| XLE | Energy | 能源 |
| XLI | Industrials | 工业 |
| XLY | Consumer Discretionary | 可选消费 |
| XLP | Consumer Staples | 必需消费 |
| XLU | Utilities | 公用事业 |
| XLB | Materials | 材料 |
| XLRE | Real Estate | 金融地产 |
| XLC | Communication Services | 电信服务 |

**拉取时点**：T 日 9:00（拉取 T-1 美国交易日收盘数据）

**数据字段**：前收盘价、收盘价、涨跌幅

---

#### 3.2.2 韩股数据

**数据源**：AKShare `index_korea_*` 或其他韩股 API

**拉取标的**：
1. **KOSPI 综合指数**（韩国综合股价指数）
2. **KOSPI 200 信息技术指数**（或科技 ETF）

**拉取时点**：T 日 9:05（拉取当日开盘后 5 分钟数据）

**数据字段**：昨收盘价、当前价、涨跌幅

---

### 3.3 板块映射表

**美股 → A股映射**：

| 美股板块代码 | 美股板块名称 | A股行业（中证分类） |
|---|---|---|
| XLK | Technology | 信息技术 |
| XLV | Health Care | 医药卫生 |
| XLF | Financials | 金融地产 |
| XLE | Energy | 能源 |
| XLI | Industrials | 工业 |
| XLY | Consumer Discretionary | 可选消费 |
| XLP | Consumer Staples | 必需消费 |
| XLU | Utilities | 公用事业 |
| XLB | Materials | 材料 |
| XLRE | Real Estate | 金融地产 |
| XLC | Communication Services | 电信服务 |

**注**：XLF 和 XLRE 都映射到"金融地产"，信号会叠加。

---

### 3.4 标的→板块识别机制

**数据来源**：`instrument_catalog` 表的 `industry` 字段（AlphaFeed/AKShare 返回）

**识别流程**：
```python
def get_sector(symbol: str) -> str:
    # 1. 先查手动配置（优先级最高）
    manual_mapping = config.instrument_sector_overrides.get(symbol)
    if manual_mapping:
        return manual_mapping
    
    # 2. 查 instrument_catalog 表
    catalog_entry = store.load_instrument(symbol)
    if catalog_entry and catalog_entry.industry:
        return _normalize_industry(catalog_entry.industry)  # 归一化到中证10类
    
    # 3. 都没有，返回默认（如"综合"）
    return "综合"
```

**手动配置示例**（`config/default.yaml`）：
```yaml
instrument_sector_overrides:
  "588170.SH": "信息技术"    # 科创50ETF，虽然跨行业但科技占比最高
  "588200.SH": "信息技术"    # 科创芯片ETF
  "512010.SH": "医药卫生"    # 医药ETF
  "512880.SH": "金融地产"    # 证券ETF
```

**行业归一化**（将各数据源的行业分类统一到中证 10 类）：
```python
INDUSTRY_NORMALIZATION = {
    # AlphaFeed/AKShare 可能返回的行业名 → 中证分类
    "电子": "信息技术",
    "计算机": "信息技术",
    "通信": "电信服务",
    "医药生物": "医药卫生",
    "银行": "金融地产",
    "非银金融": "金融地产",
    "房地产": "金融地产",
    # ... 更多映射
}
```

---

### 3.5 策略逻辑

**输入数据**（盘前 9:05 已拉取并缓存）：
- `nasdaq_change`：纳斯达克涨跌幅 (%)
- `sp500_change`：标普 500 涨跌幅
- `dow_change`：道琼斯涨跌幅
- `us_sector_changes`：11 个美股板块涨跌幅字典 `{XLK: 2.3, XLV: -0.8, ...}`
- `kospi_change`：韩股综指涨跌幅
- `kr_tech_change`：韩股科技涨跌幅

**打分规则**（以信息技术板块标的为例）：

```python
def evaluate(symbol: str, features, context) -> StrategySignal:
    sector = self._get_sector(symbol)  # "信息技术"
    us_sector_code = self._sector_to_us_code(sector)  # "XLK"
    
    score = Decimal("0")
    evidence = []
    
    # 规则1：对应美股板块主导
    us_sector_change = self.us_sector_changes.get(us_sector_code, 0)
    if us_sector_change >= self.config.us_sector_bullish:  # 默认 2.0%
        score += Decimal(str(self.config.us_sector_weight))  # 默认 +2
        evidence.append(f"美股{us_sector_code}板块涨幅 {us_sector_change:.1f}% >= 阈值")
    elif us_sector_change <= self.config.us_sector_bearish:  # 默认 -2.0%
        score -= Decimal(str(self.config.us_sector_weight))  # -2
        evidence.append(f"美股{us_sector_code}板块跌幅 {us_sector_change:.1f}% <= 阈值")
    
    # 规则2：纳斯达克权重（配置了 nasdaq 相关联的板块才触发）
    if sector in self.config.nasdaq_correlated_sectors:
        if self.nasdaq_change >= self.config.nasdaq_bullish:  # 默认 1.5%
            score += Decimal(str(self.config.nasdaq_weight))  # +1.5
            evidence.append(f"纳斯达克涨幅 {self.nasdaq_change:.1f}%")
        elif self.nasdaq_change <= self.config.nasdaq_bearish:
            score -= Decimal(str(self.config.nasdaq_weight))
    
    # 规则3：韩股科技共振（配置了 kr_tech 相关联的板块才触发）
    if sector in self.config.kr_tech_correlated_sectors and self.kr_tech_change:
        if self.kr_tech_change >= self.config.kr_tech_bullish and us_sector_change > 0:
            score += Decimal(str(self.config.kr_tech_weight))  # +1
            evidence.append(f"韩股科技与美股科技共振向上")
        elif self.kr_tech_change <= self.config.kr_tech_bearish and us_sector_change < 0:
            score -= Decimal(str(self.config.kr_tech_weight))
            evidence.append(f"韩股科技与美股科技共振向下")
    
    # 规则4：美股三大指数全绿/全红（全局风险偏好）
    if self.nasdaq_change > 0 and self.sp500_change > 0 and self.dow_change > 0:
        score += Decimal("0.5")
        evidence.append("美股三大指数全涨，风险偏好回升")
    elif self.nasdaq_change < 0 and self.sp500_change < 0 and self.dow_change < 0:
        score -= Decimal("0.5")
        evidence.append("美股三大指数全跌，避险情绪升温")
    
    # 分数→方向+目标仓位
    if score >= self.config.strong_buy_score:  # 默认 2.5
        direction = Direction.BUY
        target_weight = Decimal("0.40")
    elif score >= self.config.buy_score:  # 默认 1.5
        direction = Direction.BUY
        target_weight = Decimal("0.30")
    elif score >= self.config.weak_buy_score:  # 默认 0.5
        direction = Direction.BUY
        target_weight = Decimal("0.20")
    elif score <= self.config.strong_reduce_score:  # 默认 -2.0
        direction = Direction.REDUCE
        target_weight = Decimal("0.10")
    elif score <= self.config.reduce_score:  # 默认 -1.0
        direction = Direction.REDUCE
        target_weight = Decimal("0.20")
    else:
        direction = Direction.HOLD
        target_weight = context.current_weight(symbol)
    
    return StrategySignal(
        strategy_id="overseas_market_sentiment",
        symbol=symbol,
        direction=direction,
        score=score,
        confidence=min(Decimal("1"), abs(score) / Decimal("5")),
        target_weight=target_weight,
        evidence=evidence,
        explanation=evidence[0] if evidence else "外围市场中性",
    )
```

---

### 3.6 数据表 Schema

**表 1**：`overseas_market_data`

```sql
CREATE TABLE overseas_market_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    market VARCHAR(32) NOT NULL COMMENT 'US/KR',
    symbol VARCHAR(32) NOT NULL COMMENT '^IXIC/XLK/KOSPI等',
    name VARCHAR(128) COMMENT '纳斯达克/科技板块/韩国综指',
    trade_date DATE NOT NULL COMMENT '交易日（美股为T-1，韩股为T）',
    prev_close DECIMAL(20,6) NOT NULL,
    close_price DECIMAL(20,6) NOT NULL,
    change_pct DECIMAL(10,6) NOT NULL COMMENT '涨跌幅',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_market_symbol_date (market, symbol, trade_date),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='外围市场行情数据';
```

**表 2**：`instrument_sector_mapping`（可选，手动配置也能用 YAML）

```sql
CREATE TABLE instrument_sector_mapping (
    symbol VARCHAR(32) PRIMARY KEY,
    sector VARCHAR(64) NOT NULL COMMENT '中证行业分类',
    source VARCHAR(32) NOT NULL COMMENT 'manual/auto',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='标的板块映射（手动覆盖）';
```

---

### 3.7 数据源接入代码示例

**美股数据（Yahoo Finance）**：

```python
import yfinance as yf
from datetime import date, timedelta

def fetch_us_market_data(trade_date: date) -> list:
    """拉取美股三大指数 + 11个板块ETF的前一交易日数据"""
    symbols = [
        "^IXIC", "^GSPC", "^DJI",  # 三大指数
        "XLK", "XLV", "XLF", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"
    ]
    
    results = []
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")  # 拉最近2天，取倒数第二天（T-1）
        if len(hist) < 2:
            continue
        
        prev_close = hist.iloc[-2]["Close"]
        close = hist.iloc[-1]["Close"]
        change_pct = (close - prev_close) / prev_close * 100
        
        results.append({
            "market": "US",
            "symbol": symbol,
            "trade_date": trade_date - timedelta(days=1),  # T-1美国时间
            "prev_close": prev_close,
            "close_price": close,
            "change_pct": change_pct,
        })
    
    return results
```

**韩股数据（AKShare 示例）**：

```python
import akshare as ak

def fetch_kr_market_data(current_time: datetime) -> list:
    """拉取韩股开盘后5分钟数据"""
    # AKShare 韩国指数接口（需确认实际可用接口）
    kospi = ak.index_korea_hist(symbol="KOSPI")  # 示例，实际接口待确认
    # 取当日开盘价 vs 昨收盘
    ...
    return results
```

**注**：AKShare 的韩股接口可能不稳定或无实时数据，可能需要其他数据源（如韩国交易所 API、第三方金融数据服务）。

---

### 3.8 配置项

```yaml
# config/default.yaml
strategy:
  overseas_market_sentiment:
    # 权重
    us_sector_weight: "2.0"         # 美股对应板块的打分权重
    nasdaq_weight: "1.5"            # 纳斯达克的打分权重
    kr_tech_weight: "1.0"           # 韩股科技的打分权重
    
    # 阈值
    us_sector_bullish: "2.0"        # 美股板块涨幅超过此值视为强势 (%)
    us_sector_bearish: "-2.0"       # 美股板块跌幅超过此值视为弱势
    nasdaq_bullish: "1.5"
    nasdaq_bearish: "-1.5"
    kr_tech_bullish: "1.0"
    kr_tech_bearish: "-1.0"
    
    # 目标仓位映射
    strong_buy_score: "2.5"         # score >= 此值 → 目标仓位 0.40
    buy_score: "1.5"                # score >= 此值 → 目标仓位 0.30
    weak_buy_score: "0.5"           # score >= 此值 → 目标仓位 0.20
    reduce_score: "-1.0"            # score <= 此值 → 目标仓位 0.20
    strong_reduce_score: "-2.0"     # score <= 此值 → 目标仓位 0.10
    
    # 板块关联配置（哪些板块额外关注纳指/韩股科技）
    nasdaq_correlated_sectors: ["信息技术"]       # 这些板块额外关注纳斯达克
    kr_tech_correlated_sectors: ["信息技术"]      # 这些板块额外关注韩股科技

# 手动板块映射（覆盖自动推断）
instrument_sector_overrides:
  "588170.SH": "信息技术"
  "588200.SH": "信息技术"
  "512010.SH": "医药卫生"
  "512880.SH": "金融地产"
```

---

### 3.9 代码结构

**新增文件**：
```
src/stock_ai_agent/
├── quant_strategies.py
│   └── class OverseasMarketSentimentStrategy     # 新增
├── data/
│   └── overseas.py                               # 新增：美股/韩股数据拉取
│       ├── fetch_us_market_data()
│       ├── fetch_kr_market_data()
│       └── YahooFinanceProvider
├── storage/
│   └── mysql.py
│       ├── save_overseas_market_data()           # 新增
│       ├── load_latest_overseas_data()           # 新增
│       └── load_instrument_sector()              # 新增
```

**修改文件**：
```
src/stock_ai_agent/
├── monitor.py
│   └── run_iteration()                           # 盘前拉取外围数据
├── config.py
│   └── StrategyConfig                            # 新增 overseas_market_sentiment
│   └── instrument_sector_overrides               # 新增配置段
```

**测试文件**：
```
tests/
├── test_overseas_market_sentiment.py
│   ├── test_tech_sector_bullish()
│   ├── test_healthcare_sector_bearish()
│   └── test_sector_mapping()
└── test_data_overseas.py
    ├── test_fetch_us_data()
    └── test_fetch_kr_data()
```

---

## 四、策略 3：龙虎榜系列（5 个子策略）

### 4.1 概述

**策略组合**：5 个独立子策略，共享龙虎榜数据源，各自独立打分，最终由聚合器统一处理。

| 子策略 ID | 类型 | 权重 | 核心逻辑 |
|---|---|---|---|
| `lhb_follow_star_seats` | 方向 | 0.10 | 跟随明星席位买入 |
| `lhb_reverse_institutional` | 方向 | 0.05 | 机构恐慌卖出时反向抄底 |
| `lhb_seat_profile` | 方向 | 0.08 | 基于席位历史胜率跟单 |
| `lhb_consensus` | 方向 | 0.04 | 游资+机构共振买入 |
| `lhb_quant_sector` | 方向 | 0.03 | 量化席位板块操作 |

**数据依赖**：
- **3A、3D** 依赖回测产出的"明星席位列表"
- **3C** 依赖回测产出的"席位胜率统计"
- **3E** 依赖手动维护的"量化席位映射表"

**实施顺序**：
1. 数据接入（龙虎榜拉取入库）
2. 回测模块（一年数据 → 明星席位 + 胜率统计）
3. 策略实现（3B 可先上线，3A/3C/3D/3E 等回测完成）

---

### 4.2 龙虎榜数据结构

**沪深交易所每日公布**：
- 哪些标的上榜（涨跌幅异常、换手率异常等）
- 上榜原因
- 买入前 5 席位：席位名称、买入金额
- 卖出前 5 席位：席位名称、卖出金额

**席位分类**：
- **游资**：营业部席位（如"中信证券杭州延安路"）
- **机构**：名称为"机构专用"
- **量化**：通过映射表识别（如"银河证券北京中关村大街" → 幻方量化）

---

### 4.3 数据表 Schema

#### 表 1：`lhb_records`（原始榜单记录）

```sql
CREATE TABLE lhb_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(128),
    reason VARCHAR(256) COMMENT '上榜原因',
    close_price DECIMAL(20,6),
    change_pct DECIMAL(10,6) COMMENT '当日涨跌幅',
    turnover_rate DECIMAL(10,6),
    total_amount DECIMAL(24,2) COMMENT '成交金额（万元）',
    buy_seat_1 VARCHAR(256),
    buy_amount_1 DECIMAL(24,2),
    buy_seat_2 VARCHAR(256),
    buy_amount_2 DECIMAL(24,2),
    buy_seat_3 VARCHAR(256),
    buy_amount_3 DECIMAL(24,2),
    buy_seat_4 VARCHAR(256),
    buy_amount_4 DECIMAL(24,2),
    buy_seat_5 VARCHAR(256),
    buy_amount_5 DECIMAL(24,2),
    sell_seat_1 VARCHAR(256),
    sell_amount_1 DECIMAL(24,2),
    sell_seat_2 VARCHAR(256),
    sell_amount_2 DECIMAL(24,2),
    sell_seat_3 VARCHAR(256),
    sell_amount_3 DECIMAL(24,2),
    sell_seat_4 VARCHAR(256),
    sell_amount_4 DECIMAL(24,2),
    sell_seat_5 VARCHAR(256),
    sell_amount_5 DECIMAL(24,2),
    net_buy DECIMAL(24,2) COMMENT '净买入（买入前5合计 - 卖出前5合计）',
    source VARCHAR(64) DEFAULT 'akshare',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date_symbol (trade_date, symbol),
    INDEX idx_trade_date (trade_date),
    INDEX idx_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='龙虎榜原始记录';
```

#### 表 2：`lhb_seat_profile`（席位画像统计）

```sql
CREATE TABLE lhb_seat_profile (
    id INT AUTO_INCREMENT PRIMARY KEY,
    seat_name VARCHAR(256) NOT NULL,
    seat_type VARCHAR(32) COMMENT 'retail/institutional/quant',
    quant_firm VARCHAR(128) COMMENT '量化机构名（如幻方量化）',
    
    # 统计指标
    total_appearances INT DEFAULT 0 COMMENT '上榜次数',
    buy_count INT DEFAULT 0 COMMENT '买入次数',
    sell_count INT DEFAULT 0 COMMENT '卖出次数',
    
    # T+1 表现
    t1_avg_return DECIMAL(10,6) COMMENT 'T+1平均收益率',
    t1_win_rate DECIMAL(10,6) COMMENT 'T+1胜率（收益>0的占比）',
    t1_max_return DECIMAL(10,6),
    t1_min_return DECIMAL(10,6),
    
    # T+3 表现
    t3_avg_return DECIMAL(10,6),
    t3_win_rate DECIMAL(10,6),
    
    # T+5 表现
    t5_avg_return DECIMAL(10,6),
    t5_win_rate DECIMAL(10,6),
    
    # 元数据
    first_seen DATE COMMENT '首次上榜日期',
    last_seen DATE COMMENT '最近上榜日期',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_seat_name (seat_name),
    INDEX idx_t3_win_rate (t3_win_rate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='龙虎榜席位画像';
```

#### 表 3：`lhb_quant_seats`（量化席位映射表）

```sql
CREATE TABLE lhb_quant_seats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    seat_name VARCHAR(256) NOT NULL,
    quant_firm VARCHAR(128) NOT NULL COMMENT '量化机构',
    strategy_style VARCHAR(128) COMMENT '策略风格（如高频/中性/指增）',
    notes TEXT COMMENT '备注',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_seat_name (seat_name),
    INDEX idx_quant_firm (quant_firm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='量化席位映射';
```

**预置数据**（根据你提供的信息）：

```sql
INSERT INTO lhb_quant_seats (seat_name, quant_firm, strategy_style, notes) VALUES
('银河证券北京中关村大街', '幻方量化', '高频/中性/指增', '买卖同时上榜'),
('中信证券杭州延安路', '幻方量化', '高频/中性/指增', '买卖同时上榜'),
('华泰证券杭州求是路', '幻方量化', '高频/中性/指增', '买卖同时上榜'),
('开源证券西安西大街', '九坤投资', 'CTA+多因子', '高频交易量大'),
('开源证券西安太华路', '九坤投资', 'CTA+多因子', '高频交易量大'),
('中信证券北京总部', '九坤投资', 'CTA+多因子', '高频交易量大'),
('华泰证券上海福山路', '明汯投资', '全频段量化', '中高频'),
('华鑫证券上海淞滨路', '明汯投资', '全频段量化', '中高频'),
('申万宏源上海陆家嘴环路', '明汯投资', '全频段量化', '中高频'),
('中信证券杭州凤起路', '灵均投资', '中性/指增', NULL),
('华泰证券杭州解放东路', '灵均投资', '中性/指增', NULL),
('中信建投北京朝阳门内大街', '天演资本', 'Alpha/中性', NULL),
('华泰证券北京分公司', '天演资本', 'Alpha/中性', NULL),
('国泰君安上海江苏路', '衍复投资', '中高频量化', NULL),
('华泰南京江宁天元东路', '衍复投资', '中高频量化', NULL);
```

---

### 4.4 策略 3A：跟单策略

**策略 ID**: `lhb_follow_star_seats`

**逻辑**：明星席位（高胜率席位）昨日买入，今日跟进。

**触发条件**：
1. T 日龙虎榜中，标的 X 的买入前 5 里有**明星席位**
2. 该席位买入金额 ≥ `min_buy_amount`（默认 1000 万）**或** 占成交额比例 ≥ `min_buy_ratio`（默认 5%）
3. 标的 X 在观察池里

**信号**：
- Direction: BUY
- Score: `+1.0`（可配）
- Target Weight: 不直接调仓位，由聚合器根据 score 决定

**明星席位来源**：回测模块产出，写入配置或数据库。

**配置示例**：
```yaml
strategy:
  lhb_follow_star_seats:
    star_seats:                      # 回测后填入
      - "某某证券某某路"
      - "某某证券某某路"
    min_buy_amount: "1000"           # 万元
    min_buy_ratio: "0.05"            # 5%
    signal_score: "1.0"
```

**实现占位**：先返回 WATCH，回测完成后补逻辑。

---

### 4.5 策略 3B：反向策略

**策略 ID**: `lhb_reverse_institutional`

**逻辑**：机构集中卖出视为恐慌，次日低开时抄底。

**触发条件**：
1. T 日龙虎榜中，标的 X 的卖出前 5 里有 ≥ `min_institutional_count`（默认 3）个"机构专用"席位
2. 各机构席位卖出金额均 ≥ `min_sell_amount`（默认 500 万）
3. T+1 日集合竞价结束（9:25），标的 X 集合竞价价格相比昨收盘低开幅度 ≥ `min_gap_down`（默认 -3%）
4. 标的 X 在观察池里

**判断时点**：盘前任务（9:25）检查集合竞价价格。满足条件的标的提前生成抄底信号缓存，9:30 第一轮 monitor 直接读取，避免因策略计算延迟而错过低开价位。

**设计说明**：低开信号依赖集合竞价价格（9:25 就能获取），而不是开盘后的实时价格。这样可以在 9:30 开盘第一秒就执行，不会因为行情拉取或策略计算耗时导致买入价格高于预期。

**信号**：
- Direction: BUY（抄底）
- Score: `+1.5`（可配）
- Target Weight: `0.20`

**配置示例**：
```yaml
strategy:
  lhb_reverse_institutional:
    min_institutional_count: 3       # 至少3个机构卖出
    min_sell_amount: "500"           # 万元
    min_gap_down: "-3.0"             # 低开-3%触发
    signal_score: "1.5"
    target_weight: "0.20"
```

---

### 4.6 策略 3C：席位画像

**策略 ID**: `lhb_seat_profile`

**逻辑**：基于席位历史胜率，只跟高胜率席位。

**触发条件**：
1. T 日龙虎榜中，标的 X 的买入前 5 里有席位满足：
   - T+3 胜率 ≥ `min_win_rate`（默认 60%）
   - 历史上榜次数 ≥ `min_sample_size`（默认 20 次）
2. 该席位买入金额 ≥ `min_buy_amount`
3. 标的 X 在观察池里

**信号**：
- Direction: BUY
- Score: 根据胜率映射（60%-70% → +1，70%-80% → +1.5，>80% → +2）
- Target Weight: 不直接指定

**席位画像更新**：
- 初始：回测一年数据生成
- 日常：每周日凌晨增量更新（计算本周新上榜席位的 T+3 表现）

**配置示例**：
```yaml
strategy:
  lhb_seat_profile:
    min_win_rate: "0.60"             # 60%胜率
    min_sample_size: 20              # 至少20次样本
    min_buy_amount: "1000"
    observe_period: "t3"             # t1/t3/t5
    score_mapping:
      "0.60": "1.0"
      "0.70": "1.5"
      "0.80": "2.0"
```

---

### 4.7 策略 3D：游资机构共振

**策略 ID**: `lhb_consensus`

**逻辑**：游资和机构同时买入，多方共识信号更强。

**触发条件**：
1. T 日龙虎榜中，标的 X 的买入前 5 里**同时**满足：
   - 至少 1 个明星游资席位（从 3A 的列表取）
   - 至少 1 个"机构专用"席位
2. 两方买入金额均 ≥ `min_buy_amount`
3. 标的 X 在观察池里

**信号**：
- Direction: BUY
- Score: `+2.5`（高于单独跟单的 +1）
- Target Weight: 不直接指定

**配置示例**：
```yaml
strategy:
  lhb_consensus:
    min_buy_amount: "1000"
    signal_score: "2.5"              # 共振信号更强
```

**依赖**：明星席位列表（与 3A 共享）

---

### 4.8 策略 3E：量化席位监控

**策略 ID**: `lhb_quant_sector`

**逻辑**：量化私募集中买入同板块多只标的，判断为因子看多该板块。

**触发条件**：
1. T 日龙虎榜中，某量化机构的席位买入了 ≥ `min_symbols_in_sector`（默认 3）只**同板块**标的
2. 各笔买入金额均 ≥ `min_buy_amount`
3. 观察池里有该板块的标的

**设计说明**：策略只对观察池内的同板块标的触发信号，观察池外的量化操作不产生任何影响。这是有意为之的边界——如果需要感知更广的量化板块动向，通过在观察池里加入对应板块 ETF 来扩展覆盖，而不是让本策略隐性地影响全局情绪。这样信号来源保持清晰，不与策略 2（外围市场情绪）重叠。

**信号**：
- Direction: BUY
- Score: `+1.0`
- Target Weight: 对该板块所有观察池标的生效

**配置示例**：
```yaml
strategy:
  lhb_quant_sector:
    min_symbols_in_sector: 3         # 同板块至少3只
    min_buy_amount: "500"
    signal_score: "1.0"
```

**板块识别**：复用策略 2 的标的→板块机制。

**示例场景**：
- T 日龙虎榜：幻方量化买入了"宁德时代"、"比亚迪"、"亿纬锂能"（均为新能源板块）
- 判断：量化因子看多新能源
- 信号：观察池里的新能源标的（如新能源 ETF）score +1

---

### 4.9 数据源接入

**AKShare 接口**：

```python
import akshare as ak

def fetch_lhb_data(trade_date: str) -> list:
    """
    拉取指定日期的龙虎榜数据
    
    Args:
        trade_date: 格式 "20260821"
    
    Returns:
        list of dict，每条记录对应一个上榜标的
    """
    # AKShare 龙虎榜接口
    df_detail = ak.stock_lhb_detail_em(start_date=trade_date, end_date=trade_date)
    
    # 解析成记录列表
    records = []
    for _, row in df_detail.iterrows():
        record = {
            "trade_date": row["交易日期"],
            "symbol": row["代码"],
            "name": row["名称"],
            "close_price": row["收盘价"],
            "change_pct": row["涨跌幅"],
            "turnover_rate": row["换手率"],
            "total_amount": row["成交额"],
            "reason": row["上榜原因"],
            "buy_seat_1": row.get("买一席位"),
            "buy_amount_1": row.get("买一金额"),
            # ... 其余买卖席位
        }
        records.append(record)
    
    return records
```

**盘后任务**（每日 19:00）：

```python
def postmarket_task(trade_date: date, store):
    # 1. 拉取龙虎榜
    lhb_data = fetch_lhb_data(trade_date.strftime("%Y%m%d"))
    store.save_lhb_records(lhb_data)
    
    # 2. 拉取期指持仓（19:30，这里可以延迟执行或单独任务）
    # futures_data = fetch_futures_positions(...)
    # store.save_futures_positions(futures_data)
    
    # 3. 日报归档（已有逻辑）
    # build_daily_report(...)
```

---

### 4.10 回测模块设计

**目标**：
1. 拉取近一年龙虎榜数据
2. 统计每个席位的 T+1/T+3/T+5 表现
3. 产出"明星席位列表"（T+3 胜率 > 60% 且样本 ≥ 20）
4. 写入 `lhb_seat_profile` 表

**流程**：

```python
# scripts/backtest_lhb_seats.py
from datetime import date, timedelta
from stock_ai_agent.storage.mysql import MySQLMarketDataStore
from stock_ai_agent.data.lhb import fetch_lhb_data
import akshare as ak

def backtest_seats(start_date: date, end_date: date, store):
    """
    回测席位表现
    
    Args:
        start_date: 开始日期（如一年前）
        end_date: 结束日期（如今天）
        store: 数据库存储
    """
    # 1. 拉取一年龙虎榜数据（如果已入库则跳过）
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # 工作日
            print(f"拉取 {current} 龙虎榜...")
            data = fetch_lhb_data(current.strftime("%Y%m%d"))
            store.save_lhb_records(data)
        current += timedelta(days=1)
    
    # 2. 统计每个席位
    seats = {}  # {seat_name: {appearances: [], buy_records: [], ...}}
    
    all_records = store.load_lhb_records(start_date, end_date)
    for record in all_records:
        # 提取买入席位
        for i in range(1, 6):
            seat_name = record[f"buy_seat_{i}"]
            if not seat_name:
                continue
            
            if seat_name not in seats:
                seats[seat_name] = {
                    "buy_records": [],
                    "sell_records": [],
                }
            
            # 记录这次买入
            seats[seat_name]["buy_records"].append({
                "date": record["trade_date"],
                "symbol": record["symbol"],
                "amount": record[f"buy_amount_{i}"],
            })
    
    # 3. 计算每次买入的 T+1/T+3/T+5 收益
    for seat_name, seat_data in seats.items():
        t1_returns = []
        t3_returns = []
        t5_returns = []
        
        for buy_record in seat_data["buy_records"]:
            symbol = buy_record["symbol"]
            buy_date = buy_record["date"]
            
            # 查该标的后续价格
            bars = store.load_bars(symbol, interval="daily", limit=10)
            buy_bar = next((b for b in bars if b.trade_date == buy_date), None)
            if not buy_bar:
                continue
            
            buy_price = buy_bar.close_price
            
            # T+1
            t1_bar = next((b for b in bars if b.trade_date == buy_date + timedelta(days=1)), None)
            if t1_bar:
                t1_return = (t1_bar.close_price - buy_price) / buy_price
                t1_returns.append(float(t1_return))
            
            # T+3, T+5 类似...
        
        # 4. 统计胜率
        t1_win_rate = sum(1 for r in t1_returns if r > 0) / len(t1_returns) if t1_returns else 0
        t3_win_rate = sum(1 for r in t3_returns if r > 0) / len(t3_returns) if t3_returns else 0
        
        # 5. 写入 lhb_seat_profile
        store.save_seat_profile({
            "seat_name": seat_name,
            "total_appearances": len(seat_data["buy_records"]) + len(seat_data["sell_records"]),
            "buy_count": len(seat_data["buy_records"]),
            "t1_avg_return": sum(t1_returns) / len(t1_returns) if t1_returns else 0,
            "t1_win_rate": t1_win_rate,
            "t3_win_rate": t3_win_rate,
            # ...
        })
    
    # 6. 输出明星席位列表
    star_seats = store.query(
        "SELECT seat_name, t3_win_rate, buy_count FROM lhb_seat_profile "
        "WHERE t3_win_rate >= 0.60 AND buy_count >= 20 "
        "ORDER BY t3_win_rate DESC"
    )
    
    print("\n明星席位列表（T+3胜率 > 60%，样本 >= 20）：")
    for seat in star_seats:
        print(f"  {seat['seat_name']}: 胜率 {seat['t3_win_rate']:.1%}，{seat['buy_count']} 次买入")
    
    return star_seats
```

**使用**：
```bash
# 第一次运行：回测一年
python scripts/backtest_lhb_seats.py --start 2025-08-21 --end 2026-08-21

# 日常更新：每周日增量更新本周数据
python scripts/backtest_lhb_seats.py --start 2026-08-14 --end 2026-08-21 --incremental
```

---

### 4.11 配置项汇总

```yaml
# config/default.yaml
strategy:
  # 3A 跟单策略
  lhb_follow_star_seats:
    enabled: false                   # 回测完成后改为 true
    star_seats: []                   # 回测后填入，如 ["某某证券某某路", ...]
    min_buy_amount: "1000"
    min_buy_ratio: "0.05"
    signal_score: "1.0"
  
  # 3B 反向策略
  lhb_reverse_institutional:
    enabled: true
    min_institutional_count: 3
    min_sell_amount: "500"
    min_gap_down: "-3.0"
    signal_score: "1.5"
    target_weight: "0.20"
  
  # 3C 席位画像
  lhb_seat_profile:
    enabled: false                   # 回测完成后改为 true
    min_win_rate: "0.60"
    min_sample_size: 20
    min_buy_amount: "1000"
    observe_period: "t3"
    score_mapping:
      "0.60": "1.0"
      "0.70": "1.5"
      "0.80": "2.0"
  
  # 3D 共振策略
  lhb_consensus:
    enabled: false                   # 依赖 3A，回测后启用
    min_buy_amount: "1000"
    signal_score: "2.5"
  
  # 3E 量化监控
  lhb_quant_sector:
    enabled: true                    # 量化席位映射表预置好了，可直接启用
    min_symbols_in_sector: 3
    min_buy_amount: "500"
    signal_score: "1.0"
```

---

### 4.12 代码结构

**新增文件**：
```
src/stock_ai_agent/
├── quant_strategies.py
│   ├── class LhbFollowStarSeatsStrategy          # 3A
│   ├── class LhbReverseInstitutionalStrategy     # 3B
│   ├── class LhbSeatProfileStrategy              # 3C
│   ├── class LhbConsensusStrategy                # 3D
│   └── class LhbQuantSectorStrategy              # 3E
├── data/
│   └── lhb.py                                    # 新增：龙虎榜数据拉取
│       ├── fetch_lhb_data()
│       ├── classify_seat_type()                  # 识别席位类型
│       └── parse_lhb_record()
├── storage/
│   └── mysql.py
│       ├── save_lhb_records()
│       ├── load_lhb_records()
│       ├── save_seat_profile()
│       ├── load_seat_profile()
│       └── load_quant_seats()
├── backtest/
│   └── lhb_backtest.py                           # 新增：席位回测模块
│       ├── backtest_seats()
│       ├── calculate_seat_returns()
│       └── export_star_seats()

scripts/
└── backtest_lhb_seats.py                         # CLI 入口
```

**测试文件**：
```
tests/
├── test_lhb_strategies.py
│   ├── test_follow_star_seats()
│   ├── test_reverse_institutional()
│   ├── test_seat_profile()
│   ├── test_consensus()
│   └── test_quant_sector()
├── test_data_lhb.py
└── test_backtest_lhb.py
```

---

## 五、架构扩展：三段式运行模式

### 5.1 当前架构

**monitor.py** 只在盘中运行：
- 启动时间：手动或 cron 触发
- 运行时段：`is_market_hours()` 判断 9:30-11:30 / 13:00-15:00
- 轮询间隔：60 秒
- 盘外行为：直接返回，不执行任何操作

**问题**：
- 无盘前准备（无法在 9:05 拉韩股数据）
- 无盘后任务（无法在 19:00 拉龙虎榜、19:30 拉期指）

---

### 5.2 目标架构

**三段式全天候运行**：

```
时段               触发时间      任务内容
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
盘前准备         09:05        1. 拉取韩股开盘数据
                              2. 读取昨夜期指/龙虎榜数据
                              3. 生成外围市场/期指信号缓存
                              4. 返回（不进入轮询）

盘中交易         09:30-15:00  1. 读取盘前信号缓存
                              2. 拉取实时行情
                              3. 执行策略（现有6策略 + 新3策略）
                              4. 风控 + 下单
                              5. 每60秒轮询

盘后复盘         19:00-20:00  1. 拉取龙虎榜（19:00）
                              2. 拉取期指持仓（19:30）
                              3. 生成日报归档
                              4. 更新席位画像（每周日）
                              5. 返回（不进入轮询）
```

---

### 5.3 实现方案（推荐方案 1）

#### 方案 1：扩展 monitor.py（轻量改造）

**核心思路**：`run_iteration` 开头加时段判断，盘前/盘后执行相应任务后立即返回。

**代码示例**：

```python
# monitor.py

from datetime import time as clock_time

PREMARKET_TIME = clock_time(9, 5)
POSTMARKET_START = clock_time(19, 0)
POSTMARKET_END = clock_time(20, 0)

def run_iteration(self, now: datetime | None = None, ignore_market_hours: bool = False) -> MonitorIterationResult:
    local_now = self._local_now(now)
    current_time = local_now.time()
    trade_date = local_now.date()
    
    # 1. 盘前任务
    if current_time >= PREMARKET_TIME and current_time < clock_time(9, 25):
        if trade_date not in self._premarket_attempted_dates:
            self._premarket_attempted_dates.append(trade_date)
            return self._execute_premarket_task(local_now)
        # 已执行过，返回等待
        return MonitorIterationResult(action="premarket_done", message="盘前任务已完成，等待开盘")
    
    # 2. 盘后任务
    if current_time >= POSTMARKET_START and current_time <= POSTMARKET_END:
        if trade_date not in self._postmarket_attempted_dates:
            self._postmarket_attempted_dates.append(trade_date)
            return self._execute_postmarket_task(local_now)
        return MonitorIterationResult(action="postmarket_done", message="盘后任务已完成")
    
    # 3. 盘中交易（现有逻辑）
    if not ignore_market_hours and not self._is_market_hours(local_now):
        return MonitorIterationResult(action="wait", message="非交易时段")
    
    # 现有的 _execute_iteration 逻辑...
    return self._execute_iteration(local_now, portfolio, ...)

def _execute_premarket_task(self, local_now: datetime) -> MonitorIterationResult:
    """盘前准备任务"""
    tasks_completed = []
    warnings = []
    trade_date = local_now.date()
    
    # 1. 拉取韩股开盘数据（9:05）
    try:
        kr_data = fetch_kr_market_data(local_now)
        self.store.save_overseas_market_data(kr_data)
        tasks_completed.append("韩股数据已更新")
    except Exception as exc:
        warnings.append(f"韩股数据拉取失败：{exc}")
    
    # 2. 读取昨夜美股数据（应该在昨日盘后或今日凌晨已拉取）
    us_data = self.store.load_latest_overseas_data(market="US", limit=1)
    if not us_data:
        warnings.append("未找到最新美股数据")
    else:
        tasks_completed.append(f"美股数据已就绪（{us_data[0]['trade_date']}）")
    
    # 3. 读取昨夜期指持仓
    futures_data = self.store.load_latest_futures_position()
    if futures_data:
        tasks_completed.append(f"期指数据已就绪（{futures_data['trade_date']}）")
    else:
        warnings.append("未找到最新期指数据")
    
    # 4. 检查龙虎榜 3B 反向策略的集合竞价低开信号（9:25）
    if local_now.time() >= clock_time(9, 25):
        try:
            lhb_reverse_signals = self._check_lhb_reverse_gap_down(trade_date)
            if lhb_reverse_signals:
                self._cache_lhb_reverse_signals(lhb_reverse_signals)  # 缓存信号
                tasks_completed.append(f"龙虎榜反向策略：检测到 {len(lhb_reverse_signals)} 个低开抄底信号")
        except Exception as exc:
            warnings.append(f"龙虎榜反向策略检查失败：{exc}")
    
    logger.info(f"盘前任务完成：{', '.join(tasks_completed)}")
    if warnings:
        logger.warning(f"盘前告警：{'; '.join(warnings)}")
    
    return MonitorIterationResult(
        action="premarket_completed",
        message=f"盘前任务完成（{len(tasks_completed)} 项）",
        warnings=warnings,
    )

def _execute_postmarket_task(self, local_now: datetime) -> MonitorIterationResult:
    """盘后复盘任务"""
    tasks_completed = []
    warnings = []
    trade_date = local_now.date()
    
    # 1. 拉取龙虎榜（19:00-19:30）
    if local_now.time() >= clock_time(19, 0) and local_now.time() < clock_time(19, 30):
        try:
            lhb_data = fetch_lhb_data(trade_date.strftime("%Y%m%d"))
            self.store.save_lhb_records(lhb_data)
            tasks_completed.append(f"龙虎榜已更新（{len(lhb_data)} 条）")
        except Exception as exc:
            warnings.append(f"龙虎榜拉取失败：{exc}")
    
    # 2. 拉取期指持仓（19:30-20:00）
    if local_now.time() >= clock_time(19, 30):
        # 这里是占位，实际需要人工录入或爬虫
        # futures_data = fetch_futures_positions(trade_date)
        # self.store.save_futures_positions(futures_data)
        tasks_completed.append("期指持仓待人工录入")
    
    # 3. 生成日报（已有逻辑）
    try:
        build_daily_report(self.config, self.store, trade_date)
        tasks_completed.append("日报已归档")
    except Exception as exc:
        warnings.append(f"日报生成失败：{exc}")
    
    # 4. 每周日更新席位画像
    if local_now.weekday() == 6:  # 周日
        try:
            # 增量更新本周的席位表现
            # update_seat_profile_incremental(self.store, trade_date - timedelta(days=7), trade_date)
            tasks_completed.append("席位画像已更新（周度）")
        except Exception as exc:
            warnings.append(f"席位画像更新失败：{exc}")
    
    logger.info(f"盘后任务完成：{', '.join(tasks_completed)}")
    return MonitorIterationResult(
        action="postmarket_completed",
        message=f"盘后任务完成（{len(tasks_completed)} 项）",
        warnings=warnings,
    )
```

**优点**：
- 单服务，部署不变
- 代码改动集中在 monitor.py
- 通过时间判断自动切换模式

**缺点**：
- monitor 需要 24 小时运行（或 cron 多次触发）
- 盘前/盘后任务和盘中逻辑混在一起

---

#### 方案 2：三个独立服务（重量改造）

**思路**：拆成三个独立进程，各负其责。

**docker-compose.yml**：

```yaml
services:
  # 盘前任务（cron 触发，9:05 执行一次）
  premarket:
    <<: *stockai-service
    command: ["premarket", "--config", "config/release.container.yaml"]
    restart: "no"  # cron 触发，不自动重启
  
  # 盘中交易（守护进程，9:30-15:00 轮询）
  monitor:
    <<: *stockai-service
    command: ["monitor", "--config", "config/release.container.yaml"]
    restart: unless-stopped
  
  # 盘后任务（cron 触发，19:00 执行一次）
  postmarket:
    <<: *stockai-service
    command: ["postmarket", "--config", "config/release.container.yaml"]
    restart: "no"
  
  # Web 看板
  web:
    <<: *stockai-service
    command: ["web", "--config", "config/release.container.yaml", "--host", "0.0.0.0", "--port", "8765"]
    ports: ["8765:8765"]
```

**crontab**（宿主机或 cron 容器）：

```cron
# 盘前任务（每个交易日 9:05）
5 9 * * 1-5 docker compose -f /path/to/docker-compose.yml run --rm premarket

# 盘后任务（每个交易日 19:00）
0 19 * * 1-5 docker compose -f /path/to/docker-compose.yml run --rm postmarket
```

**app.py** 新增子命令：

```python
@click.command()
def premarket():
    """盘前准备任务"""
    config = load_config(...)
    store = create_store(config)
    
    # 执行盘前逻辑
    execute_premarket_task(config, store)

@click.command()
def postmarket():
    """盘后复盘任务"""
    config = load_config(...)
    store = create_store(config)
    
    execute_postmarket_task(config, store)

cli.add_command(premarket)
cli.add_command(postmarket)
```

**优点**：
- 职责清晰，各服务独立
- 盘中 monitor 不需要关心盘前/盘后逻辑
- 更容易调试和监控

**缺点**：
- 部署变复杂（需要 cron 或 K8s CronJob）
- 代码拆分工作量大

---

### 5.4 推荐方案与理由

**推荐方案 1**，理由：
1. 项目当前是单体架构，拆分成三个服务过度工程化
2. NAS 部署场景下，单容器更简单（只需一个 compose 服务）
3. 通过 `poll_seconds: 300`（5 分钟）让 monitor 全天运行，资源消耗可控
4. 后续如果规模变大，再迁移到方案 2

**配置调整**（方案 1 下）：

```yaml
# config/default.yaml
monitor:
  poll_seconds: 300                  # 改为 5 分钟（盘外也轮询，但只检查时段）
  market_hours:
    morning_start: "09:30"
    morning_end: "11:30"
    afternoon_start: "13:00"
    afternoon_end: "15:00"
  premarket_time: "09:05"            # 新增：盘前任务执行时间
  postmarket_start: "19:00"          # 新增：盘后任务开始时间
  postmarket_end: "20:00"            # 新增：盘后任务结束时间
```

---

## 六、与现有策略的交互分析

### 6.1 权重分配

**现有 6 策略**（权重合计 1.30）：

| 策略 ID | 类型 | 权重 | 占比 |
|---|---|---|---|
| technical_composite | 方向 | 0.30 | 14.6% |
| time_series_momentum | 方向 | 0.20 | 9.8% |
| mean_reversion | 方向 | 0.15 | 7.3% |
| relative_strength | 方向 | 0.20 | 9.8% |
| volatility_target | 风控 | 0.15 | 7.3% |
| drawdown_control | 风控 | 0.30 | 14.6% |

**新增 3 策略**（权重合计 0.75）：

| 策略 ID | 类型 | 权重 | 占比 |
|---|---|---|---|
| futures_position_sentiment | 风控 | 0.25 | 12.2% |
| overseas_market_sentiment | 方向 | 0.20 | 9.8% |
| lhb_follow_star_seats | 方向 | 0.10 | 4.9% |
| lhb_reverse_institutional | 方向 | 0.05 | 2.4% |
| lhb_seat_profile | 方向 | 0.08 | 3.9% |
| lhb_consensus | 方向 | 0.04 | 2.0% |
| lhb_quant_sector | 方向 | 0.03 | 1.5% |

**总权重 2.05**（聚合时归一化）

**占比分布**：
- 现有策略占 63.4%
- 新增策略占 36.6%
- 方向策略占 62.9%
- 风控策略占 37.1%

---

### 6.2 聚合机制回顾

`strategy.py:aggregate_signals` 的核心逻辑：

1. **加权平均分** = Σ(score × weight) / Σweight
2. **候选目标仓位** = 方向策略中 score > 0 且 target_weight 最大的
3. **风控上限** = 风控策略（REDUCE/EXIT）中 target_weight 最小的
4. **最终目标** = min(候选目标, 风控上限)
5. **冲突判定**：同时存在正分和负分 → 仓位压到 0.20，方向 HOLD

**风控策略集合**（需扩展）：
```python
# strategy.py:184
RISK_CONTROL_STRATEGIES = {
    "volatility_target",
    "drawdown_control",
    "futures_position_sentiment",  # 新增
}
```

---

### 6.3 典型场景模拟

#### 场景 1：外围看多 + 技术面中性 + 期指过热

**输入**：
- 美股科技大涨 → `overseas_market_sentiment`: score +2.5, target 0.40
- 技术指标中性 → `technical_composite`: score +1, target 0.20
- 其他方向策略 HOLD → score 0
- 机构期指净多单 70% → `futures_position_sentiment`: REDUCE, score -1.5, **上限 0.40**

**聚合过程**：
1. 加权平均分 = (2.5×0.20 + 1×0.30 + ... - 1.5×0.25) / 2.05 ≈ +0.5
2. 候选目标 = 0.40（外围策略）
3. 风控上限 = 0.40（期指策略）
4. 最终目标 = min(0.40, 0.40) = **0.40**
5. 判定：平均分 > 0 → Direction: BUY

**结果**：外围看多被期指风控压制，仓位上不去（原本外围想给 0.40，但期指也说最多 0.40）。

---

#### 场景 2：龙虎榜共振 + 技术面看空

**输入**：
- 龙虎榜游资+机构共振 → `lhb_consensus`: score +2.5, target 不指定
- 技术面跌破均线 → `technical_composite`: score -2, target 0, Direction: EXIT
- 期指中性 → `futures_position_sentiment`: HOLD, 上限 0.60

**聚合过程**：
1. 加权平均分 = (2.5×0.04 + ... - 2×0.30) / 2.05 ≈ -0.1
2. **触发冲突**：有正分（龙虎榜 +2.5）也有负分（技术面 -2）
3. 仓位压到 **0.20**，Direction: HOLD

**结果**：龙虎榜强信号被技术面看空冲突，聚合器保守处理，只给 20% 仓位。

**启示**：龙虎榜策略的权重相对较小（合计 0.30 vs 技术面 0.30），很容易被现有策略压制。如果你认为龙虎榜信号更重要，可以提高权重或降低其他策略权重。

---

#### 场景 3：期指超卖 + 外围看多 + 技术面看多

**输入**：
- 机构期指净空单 70% → `futures_position_sentiment`: HOLD, 上限 **0.80**
- 美股+韩股全涨 → `overseas_market_sentiment`: score +3, target 0.40
- 技术面多头排列 → `technical_composite`: score +5, target 0.60
- 时序动量强 → `time_series_momentum`: score +2, target 0.40

**聚合过程**：
1. 加权平均分 = (3×0.20 + 5×0.30 + 2×0.20 + ...) / 2.05 ≈ +2.8
2. 候选目标 = 0.60（技术面）
3. 风控上限 = 0.80（期指允许更高仓位）
4. 最终目标 = min(0.60, 0.80, `max_total_exposure` 0.90) = **0.60**
5. 判定：平均分 2.8 > 2.5 → Direction: BUY

**结果**：多方一致看多，期指也允许加仓，最终给到 60% 仓位。

---

### 6.4 潜在问题与调优建议

#### 问题 1：龙虎榜信号容易被冲突压制

**原因**：龙虎榜 5 个子策略权重合计 0.30，单个最高 0.10，而技术面单策略 0.30。只要技术面看空（score < 0），就会触发冲突，仓位压到 0.20。

**调优方向**：
- 方案 A：提高龙虎榜权重（如 3A 跟单改为 0.15）
- 方案 B：降低技术面权重（如改为 0.20）
- 方案 C：修改聚合器逻辑，弱负分（如 -0.5）不触发冲突

**建议**：先运行一段时间观察，如果龙虎榜信号频繁被压制且后验看错过了机会，再调权重。

---

#### 问题 2：风控策略过多可能过度保守

**现状**：3 个风控策略（波动率、回撤、期指），都可能压低仓位上限。

**极端场景**：
- 波动率高 → 上限 0.20
- 回撤 7%（接近 8% 阈值）→ 上限 1.0（实际不压）
- 期指过热 → 上限 0.40
- 最终 = min(0.20, 0.40) = **0.20**

如果三个风控策略经常同时触发，仓位会被压得很低。

**调优方向**：
- 调整各风控策略的阈值（如期指过热阈值从 60% 提到 70%）
- 或者降低某个风控策略的权重（让它在聚合时影响力变小）

---

#### 问题 3：外围市场与技术面可能频繁冲突

**场景**：美股大涨但 A 股技术面已经超买（RSI > 75）。

- 外围策略：score +2.5（看多）
- 技术面：score -1.5（超买看空）
- 触发冲突 → 仓位 0.20

**这是合理的**：两个信号确实矛盾，聚合器保守处理是对的。但如果你认为外围信号优先级更高，可以：
- 提高外围策略权重
- 或调整技术面的超买判定阈值（RSI > 75 → RSI > 80）

---

### 6.5 权重调优工具

**建议开发一个权重回测工具**（不在本次设计范围，但值得后续做）：

```python
# scripts/optimize_strategy_weights.py
def backtest_with_weights(start_date, end_date, weights: dict):
    """
    用指定权重跑回测，返回收益率、夏普比率、最大回撤
    
    Args:
        weights: {"technical_composite": 0.30, "overseas_market_sentiment": 0.25, ...}
    
    Returns:
        {"total_return": 0.15, "sharpe": 1.8, "max_drawdown": -0.08}
    """
    ...

# 网格搜索最优权重组合
best_weights = None
best_sharpe = 0

for overseas_weight in [0.15, 0.20, 0.25]:
    for lhb_total_weight in [0.25, 0.30, 0.35]:
        weights = {
            "overseas_market_sentiment": overseas_weight,
            "lhb_follow_star_seats": lhb_total_weight * 0.33,
            # ...
        }
        result = backtest_with_weights("2025-01-01", "2026-08-01", weights)
        if result["sharpe"] > best_sharpe:
            best_sharpe = result["sharpe"]
            best_weights = weights

print(f"最优权重组合（夏普 {best_sharpe:.2f}）：")
print(best_weights)
```

---

## 七、实施计划

### 7.1 分阶段实施

整个项目分 **3 个阶段**，预计总工作量 **3-4 周**。

---

### 阶段 1：基础架构 + 数据接入（1 周）

**目标**：搭建三段式运行框架，接入所有数据源（不含策略逻辑）。

#### 任务清单

**1.1 数据表创建**（1 天）
- [ ] `futures_positions`
- [ ] `overseas_market_data`
- [ ] `instrument_sector_mapping`（可选）
- [ ] `lhb_records`
- [ ] `lhb_seat_profile`
- [ ] `lhb_quant_seats`（预置量化席位数据）
- [ ] 编写迁移脚本 `migrations/add_new_strategy_tables.sql`

**1.2 三段式架构改造**（2 天）
- [ ] 修改 `monitor.py`：
  - [ ] 新增 `_execute_premarket_task()`
  - [ ] 新增 `_execute_postmarket_task()`
  - [ ] `run_iteration()` 加时段判断
  - [ ] 新增 `_premarket_attempted_dates` 等去重集合
- [ ] 修改 `config.py`：
  - [ ] 新增 `premarket_time`、`postmarket_start`、`postmarket_end`
- [ ] 测试：手动触发盘前/盘后任务

**1.3 数据源接入**（2 天）
- [ ] **外围市场**：
  - [ ] 新建 `src/stock_ai_agent/data/overseas.py`
  - [ ] 实现 `fetch_us_market_data()`（Yahoo Finance）
  - [ ] 实现 `fetch_kr_market_data()`（AKShare 或其他）
  - [ ] `storage/mysql.py` 新增 `save_overseas_market_data()` / `load_latest_overseas_data()`
  - [ ] 盘前任务调用外围数据拉取
- [ ] **龙虎榜**：
  - [ ] 新建 `src/stock_ai_agent/data/lhb.py`
  - [ ] 实现 `fetch_lhb_data()`（AKShare）
  - [ ] 实现 `classify_seat_type()`（识别游资/机构/量化）
  - [ ] `storage/mysql.py` 新增 `save_lhb_records()` / `load_lhb_records()`
  - [ ] 盘后任务调用龙虎榜拉取
- [ ] **期指持仓**：
  - [ ] 编写 `scripts/import_futures_positions.py`（人工录入脚本）
  - [ ] `storage/mysql.py` 新增 `save_futures_positions()` / `load_latest_futures_position()`
  - [ ] 文档说明数据录入流程

**1.4 集成测试**（半天）
- [ ] 完整跑一遍：盘前（9:05）→ 盘中（9:30-15:00）→ 盘后（19:00）
- [ ] 检查数据表是否正确入库
- [ ] 检查日志无异常

**交付物**：
- ✅ 6 张新表已创建并初始化
- ✅ 三段式架构可正常运行
- ✅ 外围市场、龙虎榜数据可自动拉取
- ✅ 期指持仓可手动录入

---

### 阶段 2：策略 1、2 实现 + 测试（1 周）

**目标**：期指情绪对冲 + 外围市场情绪两个策略上线。

#### 任务清单

**2.1 策略 1：期指情绪对冲**（2 天）
- [ ] 新建 `FuturesPositionSentimentStrategy` 类
  - [ ] `evaluate()` 实现：读取期指数据、计算综合净持仓、判定档位
  - [ ] 配置项解析（`config.py`）
- [ ] 修改 `strategy.py`：
  - [ ] `RISK_CONTROL_STRATEGIES` 加入 `futures_position_sentiment`
- [ ] 修改 `monitor.py`：
  - [ ] signals 列表加入期指策略
- [ ] 单元测试（`tests/test_futures_position_sentiment.py`）：
  - [ ] 过热场景（净多 > 60% → 上限 0.40）
  - [ ] 超卖场景（净空 > 60% → 上限 0.80）
  - [ ] 中性场景
- [ ] 手动录入一条测试数据，跑一轮 monitor 验证

**2.2 策略 2：外围市场情绪**（3 天）
- [ ] 新建 `OverseasMarketSentimentStrategy` 类
  - [ ] `evaluate()` 实现：
    - [ ] 标的→板块识别（`_get_sector()`）
    - [ ] 板块→美股代码映射（`_sector_to_us_code()`）
    - [ ] 行业归一化（`INDUSTRY_NORMALIZATION`）
    - [ ] 打分逻辑（规则 1-4）
    - [ ] 分数→方向+仓位
  - [ ] 配置项解析
- [ ] 修改 `config.py`：
  - [ ] 新增 `overseas_market_sentiment` 段
  - [ ] 新增 `instrument_sector_overrides` 段
- [ ] 修改 `monitor.py`：
  - [ ] signals 列表加入外围策略
- [ ] 单元测试（`tests/test_overseas_market_sentiment.py`）：
  - [ ] 科技板块看多场景
  - [ ] 医药板块看空场景
  - [ ] 板块映射测试
  - [ ] 行业归一化测试
- [ ] 集成测试：
  - [ ] 盘前拉取美股+韩股数据
  - [ ] 9:30 第一轮生成外围信号
  - [ ] 检查 evidence 字段

**2.3 配置调优**（1 天）
- [ ] 填写 `instrument_sector_overrides`（科创 50、医药 ETF 等）
- [ ] 调整权重（现有 6 策略 + 新 2 策略）
- [ ] 跑一周模拟盘，观察信号质量
- [ ] 根据结果微调阈值

**交付物**：
- ✅ 策略 1、2 已上线
- ✅ 单元测试全绿
- ✅ 集成测试通过
- ✅ 模拟盘运行稳定

---

### 阶段 3：龙虎榜回测 + 策略 3 实现（1.5-2 周）

**目标**：完成龙虎榜一年回测，产出明星席位和席位画像，实现 5 个子策略。

#### 任务清单

**3.1 回测模块开发**（3 天）
- [ ] 新建 `src/stock_ai_agent/backtest/lhb_backtest.py`
  - [ ] `backtest_seats(start_date, end_date)` 主函数
  - [ ] `calculate_seat_returns()` 计算 T+1/T+3/T+5 收益
  - [ ] `export_star_seats()` 输出明星席位列表
- [ ] 新建 `scripts/backtest_lhb_seats.py` CLI 入口
- [ ] 单元测试（`tests/test_backtest_lhb.py`）

**3.2 执行一年回测**（1 天 + 等待时间）
- [ ] 拉取一年龙虎榜数据（约 200-300 个交易日）
- [ ] 拉取对应标的的后续 K 线（计算收益用）
- [ ] 运行回测脚本（预计运行时间：数小时）
- [ ] 检查输出：
  - [ ] `lhb_seat_profile` 表已填充
  - [ ] 明星席位列表已产出（T+3 胜率 > 60%，样本 ≥ 20）

**3.3 策略 3B 实现**（1 天，优先，不依赖回测）
- [ ] 新建 `LhbReverseInstitutionalStrategy` 类
- [ ] 配置项解析
- [ ] 单元测试
- [ ] 上线验证

**3.4 策略 3A、3C、3D、3E 实现**（3 天）
- [ ] **3A 跟单策略**：
  - [ ] 将回测产出的明星席位填入配置
  - [ ] 实现 `LhbFollowStarSeatsStrategy`
  - [ ] 单元测试
- [ ] **3C 席位画像**：
  - [ ] 实现 `LhbSeatProfileStrategy`
  - [ ] 从 `lhb_seat_profile` 表读取胜率
  - [ ] 胜率→score 映射
  - [ ] 单元测试
- [ ] **3D 共振策略**：
  - [ ] 实现 `LhbConsensusStrategy`
  - [ ] 复用 3A 的明星席位列表
  - [ ] 单元测试
- [ ] **3E 量化监控**：
  - [ ] 实现 `LhbQuantSectorStrategy`
  - [ ] 从 `lhb_quant_seats` 表读取映射
  - [ ] 板块聚合逻辑
  - [ ] 单元测试

**3.5 集成测试 + 调优**（2 天）
- [ ] 所有 9 个策略同时运行
- [ ] 权重调优（观察冲突场景）
- [ ] 跑一周模拟盘，记录所有信号
- [ ] 分析：
  - [ ] 哪些策略频繁触发
  - [ ] 是否有过度保守或激进的情况
  - [ ] 聚合后的仓位分布是否合理

**3.6 文档与部署**（1 天）
- [ ] 更新 README.md（新策略说明）
- [ ] 补充配置文档（各策略参数说明）
- [ ] 部署到生产环境（NAS）
- [ ] 监控前 3 天运行情况

**交付物**：
- ✅ 龙虎榜一年回测完成
- ✅ 明星席位列表已产出
- ✅ 席位画像表已填充
- ✅ 5 个龙虎榜子策略全部上线
- ✅ 9 个新策略集成测试通过
- ✅ 生产环境稳定运行

---

### 7.2 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|---|---|---|---|
| 韩股数据源不稳定 | 高 | 中 | 准备备用方案（用 T-1 韩股收盘代替 T 日开盘） |
| 期指数据无自动化源 | 确定 | 中 | 接受手动录入，编写脚本简化操作 |
| 龙虎榜回测耗时过长 | 中 | 低 | 分批回测（先 3 个月，确认无误再跑全年） |
| 明星席位列表为空 | 低 | 高 | 降低胜率阈值（60% → 55%）或样本量（20 → 15） |
| 策略信号冲突频繁 | 中 | 中 | 调整权重或修改聚合器冲突判定逻辑 |
| 新策略收益不及预期 | 中 | 高 | 保留 `enabled: false` 开关，随时可关闭单个策略 |

---

### 7.3 里程碑与验收标准

| 阶段 | 里程碑 | 验收标准 | 预计完成 |
|---|---|---|---|
| 阶段 1 | 架构与数据接入 | 三段式运行正常，数据可入库 | 第 1 周末 |
| 阶段 2 | 策略 1、2 上线 | 模拟盘运行 1 周无异常 | 第 2 周末 |
| 阶段 3 | 龙虎榜回测完成 | 产出明星席位列表和席位画像 | 第 3 周中 |
| 阶段 3 | 策略 3 全部上线 | 9 个策略集成测试通过 | 第 4 周初 |
| 最终 | 生产环境稳定 | 连续运行 3 天无异常，日志正常 | 第 4 周末 |

---

### 7.4 后续优化方向

**短期（1-3 个月内）**：
1. **权重回测工具**：网格搜索最优权重组合
2. **席位画像自动更新**：从每周手动改为每日增量更新
3. **期指数据自动化**：爬虫或购买数据服务
4. **策略开关**：Web 看板上可视化开关各策略

**中期（3-6 个月内）**：
5. **板块轮动**：扩展观察池到多个板块（医药、金融、消费等）
6. **多因子融合**：将龙虎榜 5 个子策略合并为一个多因子模型
7. **止盈止损**：加入动态止盈逻辑（如持仓收益 > 8% 自动减仓）
8. **风险预算**：按波动率或 VaR 动态分配各策略权重

**长期（6-12 个月内）**：
9. **机器学习增强**：用 XGBoost 训练席位胜率预测模型
10. **高频信号**：加入分时图形态识别（如尾盘拉升、跳水）
11. **多账户**：支持多个模拟账户，对比不同策略组合
12. **实盘对接**：如果效果好，对接券商 API 进行真实交易

---

## 八、附录

### 8.1 配置文件完整示例

```yaml
# config/default.yaml
environment: "development"

market:
  timezone: "Asia/Shanghai"
  allowed_exchanges: ["SH", "SZ"]
  allowed_asset_types: ["stock", "etf"]

monitor:
  poll_seconds: 300                   # 改为5分钟（全天运行）
  market_hours:
    morning_start: "09:30"
    morning_end: "11:30"
    afternoon_start: "13:00"
    afternoon_end: "15:00"
  premarket_time: "09:05"             # 新增
  postmarket_start: "19:00"           # 新增
  postmarket_end: "20:00"             # 新增

strategy:
  # 现有策略（权重不变）
  weights:
    technical_composite: "0.30"
    time_series_momentum: "0.20"
    mean_reversion: "0.15"
    relative_strength: "0.20"
    volatility_target: "0.15"
    drawdown_control: "0.30"
    # 新增策略权重
    futures_position_sentiment: "0.25"
    overseas_market_sentiment: "0.20"
    lhb_follow_star_seats: "0.10"
    lhb_reverse_institutional: "0.05"
    lhb_seat_profile: "0.08"
    lhb_consensus: "0.04"
    lhb_quant_sector: "0.03"
  
  # 策略1：期指情绪对冲
  futures_position_sentiment:
    contracts: ["IC"]
    bullish_threshold: "0.60"
    bearish_threshold: "-0.60"
    overheated_cap: "0.40"
    neutral_cap: "0.60"
    oversold_cap: "0.80"
    top10_weight: "0.70"
    specific_seats_weight: "0.30"
    specific_seats: ["中信期货"]
  
  # 策略2：外围市场情绪
  overseas_market_sentiment:
    us_sector_weight: "2.0"
    nasdaq_weight: "1.5"
    kr_tech_weight: "1.0"
    us_sector_bullish: "2.0"
    us_sector_bearish: "-2.0"
    nasdaq_bullish: "1.5"
    nasdaq_bearish: "-1.5"
    kr_tech_bullish: "1.0"
    kr_tech_bearish: "-1.0"
    strong_buy_score: "2.5"
    buy_score: "1.5"
    weak_buy_score: "0.5"
    reduce_score: "-1.0"
    strong_reduce_score: "-2.0"
  
  # 策略3A：跟单
  lhb_follow_star_seats:
    enabled: false                    # 回测后改为 true
    star_seats: []                    # 回测后填入
    min_buy_amount: "1000"
    min_buy_ratio: "0.05"
    signal_score: "1.0"
  
  # 策略3B：反向
  lhb_reverse_institutional:
    enabled: true
    min_institutional_count: 3
    min_sell_amount: "500"
    min_gap_down: "-3.0"
    signal_score: "1.5"
    target_weight: "0.20"
  
  # 策略3C：席位画像
  lhb_seat_profile:
    enabled: false
    min_win_rate: "0.60"
    min_sample_size: 20
    min_buy_amount: "1000"
    observe_period: "t3"
    score_mapping:
      "0.60": "1.0"
      "0.70": "1.5"
      "0.80": "2.0"
  
  # 策略3D：共振
  lhb_consensus:
    enabled: false
    min_buy_amount: "1000"
    signal_score: "2.5"
  
  # 策略3E：量化监控
  lhb_quant_sector:
    enabled: true
    min_symbols_in_sector: 3
    min_buy_amount: "500"
    signal_score: "1.0"

# 手动板块映射
instrument_sector_overrides:
  "588170.SH": "信息技术"              # 科创50ETF
  "588200.SH": "信息技术"              # 科创芯片ETF
  "512010.SH": "医药卫生"              # 医药ETF
  "512880.SH": "金融地产"              # 证券ETF
```

---

### 8.2 数据库迁移 SQL

```sql
-- migrations/add_new_strategy_tables.sql

-- 表1：期指持仓
CREATE TABLE IF NOT EXISTS futures_positions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL,
    contract VARCHAR(16) NOT NULL COMMENT 'IF/IC/IH/IM',
    top10_long DECIMAL(20,2) NOT NULL,
    top10_short DECIMAL(20,2) NOT NULL,
    top10_net_ratio DECIMAL(10,6) NOT NULL,
    specific_seat_name VARCHAR(128),
    specific_seat_long DECIMAL(20,2),
    specific_seat_short DECIMAL(20,2),
    specific_seat_net_ratio DECIMAL(10,6),
    combined_net_ratio DECIMAL(10,6) NOT NULL,
    source VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date_contract (trade_date, contract),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表2：外围市场数据
CREATE TABLE IF NOT EXISTS overseas_market_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    market VARCHAR(32) NOT NULL COMMENT 'US/KR',
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(128),
    trade_date DATE NOT NULL,
    prev_close DECIMAL(20,6) NOT NULL,
    close_price DECIMAL(20,6) NOT NULL,
    change_pct DECIMAL(10,6) NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_market_symbol_date (market, symbol, trade_date),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表3：龙虎榜记录
CREATE TABLE IF NOT EXISTS lhb_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trade_date DATE NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(128),
    reason VARCHAR(256),
    close_price DECIMAL(20,6),
    change_pct DECIMAL(10,6),
    turnover_rate DECIMAL(10,6),
    total_amount DECIMAL(24,2),
    buy_seat_1 VARCHAR(256), buy_amount_1 DECIMAL(24,2),
    buy_seat_2 VARCHAR(256), buy_amount_2 DECIMAL(24,2),
    buy_seat_3 VARCHAR(256), buy_amount_3 DECIMAL(24,2),
    buy_seat_4 VARCHAR(256), buy_amount_4 DECIMAL(24,2),
    buy_seat_5 VARCHAR(256), buy_amount_5 DECIMAL(24,2),
    sell_seat_1 VARCHAR(256), sell_amount_1 DECIMAL(24,2),
    sell_seat_2 VARCHAR(256), sell_amount_2 DECIMAL(24,2),
    sell_seat_3 VARCHAR(256), sell_amount_3 DECIMAL(24,2),
    sell_seat_4 VARCHAR(256), sell_amount_4 DECIMAL(24,2),
    sell_seat_5 VARCHAR(256), sell_amount_5 DECIMAL(24,2),
    net_buy DECIMAL(24,2),
    source VARCHAR(64) DEFAULT 'akshare',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_date_symbol (trade_date, symbol),
    INDEX idx_trade_date (trade_date),
    INDEX idx_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表4：席位画像
CREATE TABLE IF NOT EXISTS lhb_seat_profile (
    id INT AUTO_INCREMENT PRIMARY KEY,
    seat_name VARCHAR(256) NOT NULL,
    seat_type VARCHAR(32),
    quant_firm VARCHAR(128),
    total_appearances INT DEFAULT 0,
    buy_count INT DEFAULT 0,
    sell_count INT DEFAULT 0,
    t1_avg_return DECIMAL(10,6),
    t1_win_rate DECIMAL(10,6),
    t1_max_return DECIMAL(10,6),
    t1_min_return DECIMAL(10,6),
    t3_avg_return DECIMAL(10,6),
    t3_win_rate DECIMAL(10,6),
    t5_avg_return DECIMAL(10,6),
    t5_win_rate DECIMAL(10,6),
    first_seen DATE,
    last_seen DATE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_seat_name (seat_name),
    INDEX idx_t3_win_rate (t3_win_rate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表5：量化席位映射
CREATE TABLE IF NOT EXISTS lhb_quant_seats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    seat_name VARCHAR(256) NOT NULL,
    quant_firm VARCHAR(128) NOT NULL,
    strategy_style VARCHAR(128),
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_seat_name (seat_name),
    INDEX idx_quant_firm (quant_firm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 预置量化席位数据
INSERT INTO lhb_quant_seats (seat_name, quant_firm, strategy_style, notes) VALUES
('银河证券北京中关村大街', '幻方量化', '高频/中性/指增', '买卖同时上榜'),
('中信证券杭州延安路', '幻方量化', '高频/中性/指增', '买卖同时上榜'),
('华泰证券杭州求是路', '幻方量化', '高频/中性/指增', '买卖同时上榜'),
('开源证券西安西大街', '九坤投资', 'CTA+多因子', '高频交易量大'),
('开源证券西安太华路', '九坤投资', 'CTA+多因子', '高频交易量大'),
('中信证券北京总部', '九坤投资', 'CTA+多因子', '高频交易量大'),
('华泰证券上海福山路', '明汯投资', '全频段量化', '中高频'),
('华鑫证券上海淞滨路', '明汯投资', '全频段量化', '中高频'),
('申万宏源上海陆家嘴环路', '明汯投资', '全频段量化', '中高频'),
('中信证券杭州凤起路', '灵均投资', '中性/指增', NULL),
('华泰证券杭州解放东路', '灵均投资', '中性/指增', NULL),
('中信建投北京朝阳门内大街', '天演资本', 'Alpha/中性', NULL),
('华泰证券北京分公司', '天演资本', 'Alpha/中性', NULL),
('国泰君安上海江苏路', '衍复投资', '中高频量化', NULL),
('华泰南京江宁天元东路', '衍复投资', '中高频量化', NULL);
```

---

### 8.3 关键 API 接口示例

**期指持仓录入**：
```bash
python scripts/import_futures_positions.py \
  --date 2026-08-21 \
  --contract IC \
  --top10-long 70000 \
  --top10-short 65000 \
  --citic-long 12000 \
  --citic-short 8000
```

**龙虎榜回测**：
```bash
python scripts/backtest_lhb_seats.py \
  --start 2025-08-21 \
  --end 2026-08-21 \
  --output star_seats.json
```

**策略开关**：
```bash
# 临时关闭某个策略（修改配置后重启）
# config/default.yaml
strategy:
  lhb_follow_star_seats:
    enabled: false
```

---

## 结语

本设计文档涵盖了从架构改造、数据接入、策略实现到测试部署的完整方案。关键要点：

1. **分阶段实施**：避免一次性改动过大，每个阶段都有明确交付物
2. **数据先行**：先把数据接入做扎实，策略可以慢慢迭代
3. **回测验证**：龙虎榜策略必须先回测，不能拍脑袋
4. **权重可调**：所有策略权重都可配置，随时可调优
5. **开关机制**：每个策略都有 `enabled` 开关，效果不好随时可关

**下一步**：审阅本文档，确认无误后开始阶段 1 的实施。

---

**文档版本**: v1.0  
**作者**: Claude (Opus 5)  
**最后更新**: 2026-08-21

