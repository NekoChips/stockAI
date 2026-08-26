# 交易看板聚焦拆分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将交易看板拆成「实时 / 复盘」两 Tab，并新增独立决策流接口驱动单流 Timeline。

**Architecture:** 后端新增 `build_dashboard_decision_events_payload`，合并当日 `decision_events` 与 fills 为统一事件列表；HTTP 暴露 `GET /api/dashboard/decision-events`。前端用 URL query `view=live|review` 切 Tab；实时 Tab 布局为持仓+Timeline，复盘 Tab 为绩效+日历+排行榜；Timeline 自行拉取新接口并做前端筛选。

**Tech Stack:** Python（web_dashboard / web_http / unittest）、React + Ant Design + TanStack Query、现有 `frontend/src/api` 与 types。

**Spec:** `docs/specs/2026-08-26-dashboard-focus-split.md`

## Global Constraints

- 所有用户可见文案使用简体中文
- Timeline **不得**再使用 overview 拼装假「待命」节点；状态条单独展示
- overview 字段 `today_decisions` / `recent_fills` **保留**（AccountStrip / 兼容），但 DecisionTimeline 只消费新接口
- TDD：先写失败测试再写实现；提交仅在用户明确要求时执行（本计划步骤中的 Commit 可跳过，除非用户要求）
- 默认 `limit=100`；无效 `date` 返回 400

---

### Task 1: 后端 decision-events payload + 路由

**Files:**
- Modify: `src/stock_ai_agent/web_dashboard.py`（新增 builder）
- Modify: `src/stock_ai_agent/web_http.py`（路由）
- Modify: `src/stock_ai_agent/web.py`（导出）
- Modify: `src/stock_ai_agent/web_server.py`（若有再导出）
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `store.load_decision_events(trade_date)`, `store.load_fills(trade_date)`（或等价）
- Produces:
  ```python
  def build_dashboard_decision_events_payload(
      store,
      as_of: date | None = None,
      limit: int = 100,
  ) -> dict[str, Any]:
      # {"events": [...], "as_of": "YYYY-MM-DD", "fill_count": int}
  ```
  每条 event 统一字段：
  - `type`: `"decision"` | `"order"` | `"fill"`
  - `event_at`: ISO datetime string
  - `symbol`: str
  - `direction`: str（可空）
  - `approved`: bool | null（decision）
  - `status`: str | null（order）
  - `reasons`: list[str]
  - `strategy_id`: str | null
  - `order_id`: str | null
  - `quantity`: int | null（fill）
  - `price`: str | null（fill）
  - `fee`: str | null（fill）
  - `slippage`: str | null（fill）
  - `target_weight`: str | null（decision）
  - `phase`: 保留原 phase（decision/order）；fill 时为 `"fill"` 或省略用 type

- [ ] **Step 1: 写失败测试**

在 `tests/test_web.py` 增加：

```python
def test_decision_events_payload_merges_decisions_orders_and_fills_chronologically(self):
    from datetime import datetime, timezone
    from stock_ai_agent.models import Decision, Direction, Fill, Portfolio
    from stock_ai_agent.storage.mock import MockStore  # 或测试里惯用的 store
    from stock_ai_agent.web_dashboard import build_dashboard_decision_events_payload

    # 使用项目现有测试 store 模式（MockStore / SQLite），录 1 条 decision、1 条 order、1 笔 fill
    # as_of 固定日期；断言：
    # - payload keys 含 events / as_of / fill_count
    # - events 按 event_at 升序
    # - type 集合包含 decision 与 fill（及 order 若已录）
    # - fill_count == 当日 fill 数
    # - limit=1 时 events 长度 <= 1（取时间序上最新或最旧——实现约定：按时间升序后取最后 limit 条，即最近 N 条）
```

另加 HTTP 边界测试（若已有 HTTP handler 测试模式则跟随；否则测 builder + 在现有 section boundary 测试中断言 overview **不含** 强制迁移）：

```python
def test_decision_events_invalid_date_raises(self):
    # build 或路由层：date 非法 -> ValueError / 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web.py::TestWebDashboard::test_decision_events_payload_merges_decisions_orders_and_fills_chronologically -v`  
（类名以文件内实际 TestCase 为准）  
Expected: FAIL（函数未定义）

- [ ] **Step 3: 最小实现**

在 `web_dashboard.py`：

```python
def build_dashboard_decision_events_payload(store, as_of: date | None = None, limit: int = 100) -> dict[str, Any]:
    as_of = as_of or date.today()
    limit = max(1, min(int(limit), 500))
    events: list[dict[str, Any]] = []
    raw = store.load_decision_events(as_of) if hasattr(store, "load_decision_events") else []
    for item in raw:
        phase = item.get("phase") or "decision"
        events.append({
            "type": "order" if phase == "order" else "decision",
            "event_at": item.get("event_at"),
            "symbol": item.get("symbol") or "",
            "direction": item.get("direction") or "",
            "approved": item.get("approved"),
            "status": item.get("status"),
            "reasons": item.get("reasons") or [],
            "strategy_id": item.get("strategy_id") or None,
            "order_id": item.get("order_id") or None,
            "quantity": None,
            "price": None,
            "fee": None,
            "slippage": None,
            "target_weight": item.get("target_weight"),
            "phase": phase,
        })
    fills = store.load_fills(as_of) if hasattr(store, "load_fills") else []
    for fill in fills:
        ts = fill.timestamp
        events.append({
            "type": "fill",
            "event_at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "symbol": fill.symbol,
            "direction": fill.direction.value if hasattr(fill.direction, "value") else str(fill.direction),
            "approved": None,
            "status": None,
            "reasons": [],
            "strategy_id": None,
            "order_id": fill.order_id or None,
            "quantity": int(fill.quantity),
            "price": str(fill.price),
            "fee": str(fill.fee),
            "slippage": str(fill.slippage),
            "target_weight": None,
            "phase": "fill",
        })
    events.sort(key=lambda e: e.get("event_at") or "")
    if len(events) > limit:
        events = events[-limit:]
    return _to_jsonable({"events": events, "as_of": as_of.isoformat(), "fill_count": len(fills)})
```

在 `web_http.py` overview 路由旁：

```python
if request.path == "/api/dashboard/decision-events":
    try:
        query = parse_qs(request.query)
        as_of = _query_date(query, "date")  # None = today inside builder
        raw_limit = query.get("limit", ["100"])[0]
        limit = int(raw_limit)
    except ValueError as exc:
        logger.warning("决策流参数无效：%s", exc)
        _send_error(self, 400, "请求参数无效。")
        return
    payload = build_dashboard_decision_events_payload(store, as_of=as_of, limit=limit)
    _send(...)
    return
```

导出符号同步 `web.py` / `web_server.py`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_web.py -k decision_events -v`  
Expected: PASS

- [ ] **Step 5: Commit**（仅当用户要求时）

---

### Task 2: 前端类型与 API

**Files:**
- Modify: `frontend/src/types/dashboard.ts`
- Modify: `frontend/src/api/dashboard.ts`
- Modify: `frontend/src/components/dashboard/DashboardRefreshControls.tsx`（`DASHBOARD_QUERY_KEYS` 加入 `decision-events`）

**Interfaces:**
- Consumes: Task 1 HTTP 契约
- Produces:
  ```ts
  export type DecisionEventType = 'decision' | 'order' | 'fill';
  export interface DecisionEvent {
    type: DecisionEventType;
    event_at: string;
    symbol: string;
    direction?: string;
    approved?: boolean | null;
    status?: string | null;
    reasons?: string[];
    strategy_id?: string | null;
    order_id?: string | null;
    quantity?: number | null;
    price?: JsonDecimal | null;
    fee?: JsonDecimal | null;
    slippage?: JsonDecimal | null;
    target_weight?: JsonDecimal | null;
    phase?: string;
  }
  export interface DecisionEventsPayload {
    events: DecisionEvent[];
    as_of: string;
    fill_count: number;
  }
  export function fetchDecisionEvents(params?: { date?: string; limit?: number }, signal?: AbortSignal)
  ```

- [ ] **Step 1: 写类型与 fetch（无前端单测时，以 TypeScript 编译与后续组件消费为验收）**

```ts
// dashboard.ts
export function fetchDecisionEvents(
  params?: { date?: string; limit?: number },
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams();
  if (params?.date) qs.set('date', params.date);
  if (params?.limit != null) qs.set('limit', String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : '';
  return apiGet<DecisionEventsPayload>(`/api/dashboard/decision-events${suffix}`, signal);
}
```

`DASHBOARD_QUERY_KEYS` 增加 `['decision-events']`。

- [ ] **Step 2: `npx tsc --noEmit`（在 frontend 目录）确认类型通过**

- [ ] **Step 3: Commit**（仅当用户要求时）

---

### Task 3: Dashboard Tab 结构（实时 / 复盘）

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx`
- Modify: `frontend/src/components/account/AccountStrip.tsx`（加 `view: 'live' | 'review'`）

**Interfaces:**
- Consumes: overview query；`useSearchParams` 读写 `view`
- Produces: Tab 切换；实时区无 Performance/Calendar/Leaderboard/RecentActivity；复盘区无 Positions/DecisionTimeline

- [ ] **Step 1: 重构 DashboardPage**

```tsx
const [searchParams, setSearchParams] = useSearchParams();
const view = searchParams.get('view') === 'review' ? 'review' : 'live';

// Segmented / Tabs: 实时 | 复盘
// onChange -> setSearchParams({ view })

// live:
//   AccountStrip view="live"
//   Row: Col xs={24} lg={16} PositionsTable; Col xs={24} lg={8} DecisionTimeline（不传 overview data 做事件）
// review:
//   AccountStrip view="review"
//   Row: Performance + ProfitCalendar; Row: Leaderboard
```

移除 `RecentActivity` 的 import 与渲染。

- [ ] **Step 2: AccountStrip 按 view 切换 KPI**

- live：保留今日收益率、今日决策、最后刷新（可保留最近成交笔数若仍有价值；共识以决策数+更新时间为主，去掉「待确认回测」在实时的强调——复盘可显示周期相关；待确认回测可两侧都弱化或仅导航提示）
- review：总资产、今日收益率、去掉「今日决策」为主 KPI；可用「待确认回测」或简单日收益强调

按共识严格落地：
- 实时：总资产 · 日盈亏 · 持仓数 · 有效决策数 · 更新时间
- 复盘：总资产 · 日盈亏 · （可用 pending_backtest 或持仓市值比作次要；**不要**突出待批决策 distraction——共识写的是周期收益；若 overview 无独立周期字段，先用今日收益率 + 持仓市值/现金摘要，周期收益留给 PerformancePanel）

- [ ] **Step 3: 浏览器手测 Tab + URL 持久化**

- [ ] **Step 4: Commit**（仅当用户要求时）

---

### Task 4: DecisionTimeline 单流 + 筛选 + 展开

**Files:**
- Modify: `frontend/src/components/decisions/DecisionTimeline.tsx`（可拆子组件同目录）
- Optionally delete usage only of `RecentActivity`（组件文件可保留供别处，看板不再引用）

**Interfaces:**
- Consumes: `fetchDecisionEvents`；可选 watchlist 长度作状态条
- Props 改为例如：
  ```ts
  interface DecisionTimelineProps {
    watchlistCount?: number;
    statusHint?: string; // 如更新时间
  }
  ```

- [ ] **Step 1: 用 useQuery 拉 decision-events**

```ts
const { data, isLoading } = useQuery({
  queryKey: ['decision-events'],
  queryFn: ({ signal }) => fetchDecisionEvents(undefined, signal),
  refetchInterval: OVERVIEW_POLL_MS,
});
```

- [ ] **Step 2: UI**

1. Card title「决策轨道」；extra 显示 `今日 {fill_count} 笔成交 · {events.length} 条事件`
2. 顶部状态条：监控中 · 观察池 N 只（来自 props）
3. 筛选条：`Select` 类型（全部/决策/订单/成交）、标的（events 中 uniq）、操作（direction uniq）
4. Timeline：过滤后按 `event_at` 展示；点色：approved 绿 / rejected 红 / fill 蓝 / 其它灰
5. fill 节点可展开：quantity / price / fee / slippage / order_id
6. **删除** readiness 假节点逻辑与 overview `buildRecords`

- [ ] **Step 3: 手测筛选与展开；空数据 Empty**

- [ ] **Step 4: Commit**（仅当用户要求时）

---

### Task 5: 验收与清理

**Files:**
- 可能修改：`docs/specs/...` 无需改；检查 `parity-checklist` 若存在则勾选

- [ ] **Step 1: 跑后端相关测试**

Run: `python -m pytest tests/test_web.py -k "decision_events or overview or section" -v`

- [ ] **Step 2: frontend `npm run build` 或 `tsc --noEmit`**

- [ ] **Step 3: 对照 Spec 清单**

- [ ] 实时 / 复盘 Tab + URL
- [ ] lg 左右、xs 上下（持仓在上）
- [ ] Timeline 仅新接口、有筛选与成交展开
- [ ] 无 RecentActivity 卡片
- [ ] overview 仍含 today_decisions / recent_fills

- [ ] **Step 4: Commit**（仅当用户要求时）

---

## Spec coverage（自检）

| 共识项 | Task |
|--------|------|
| Tab 实时/复盘 + URL | 3 |
| 硬边界组件归属 | 3 |
| lg/xs 布局 | 3 |
| 单流 Timeline + 筛选 + Accordion | 4 |
| 独立 decision-events API | 1–2 |
| overview 保留字段 | 1、3 |
| AccountStrip KPI | 3 |
| 去掉 RecentActivity | 3 |
| 状态条替代待命节点 | 4 |
| 同频轮询 | 3–4 |

## Placeholder scan

无 TBD；limit 行为约定为「升序后取最近 limit 条」。
