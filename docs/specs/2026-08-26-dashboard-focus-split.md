# 交易看板聚焦拆分 — 设计共识

**日期：** 2026-08-26  
**状态：** 已对齐

## 目标

交易看板按任务意图拆成「实时 / 复盘」，消除一页混堆导致的无法聚焦。

## 信息架构

| Tab | URL | 内容 |
|-----|-----|------|
| 实时（默认） | `?view=live` | AccountStrip（实时 KPI）+ 持仓 + 决策轨道（单流 Timeline） |
| 复盘 | `?view=review` | AccountStrip（复盘 KPI）+ 绩效 + 盈亏日历 + 排行榜 |

硬边界：实时不出现绩效/日历/排行榜；复盘不出现持仓表与决策轨道。去掉独立「最近模拟成交」卡片，成交并入 Timeline。

## 布局

- lg+：左持仓 / 右 Timeline
- xs：上持仓 / 下 Timeline

## 决策轨道

- 单流 chronological：决策 + 订单 + 成交（均有 `event_at`）
- 顶部状态条（替代虚假「待命」节点）
- 前端筛选：类型 / 标的 / 操作
- 成交行内 Accordion 展开详情
- 只读 + 跳转（标的详情 / 策略中心）

## API

`GET /api/dashboard/decision-events`

- 服务端合并 `decision_events` + 当日 fills，统一 event shape（`type: decision|order|fill` + `event_at`）
- Query：`date`（默认今日）、`limit`（默认 100）
- 筛选第一版前端做
- overview 保留 `today_decisions` / `recent_fills`；Timeline 只消费本接口

## AccountStrip KPI

- 实时：总资产 · 日盈亏 · 持仓数 · 有效决策数 · 更新时间
- 复盘：总资产 · 日盈亏 · 周期收益 · 更新时间（去掉待批决策分心项）

## 其它

- 两 Tab 同频轮询 overview；Timeline 另请求 decision-events
- Tab 文案：实时 / 复盘
