# StockAI 双主题与交互增强设计

**Date:** 2026-08-26  
**Status:** 已实现（待手动验收主题切换与暗色漏白）  
**Product:** StockAI 策略执行台（React + Ant Design SPA）  
**规范权威：** 长期设计规范以 [`docs/design-system/README.md`](../../design-system/README.md) 为准；本文保留为该次改造的设计/验收记录。  
**关联：** 延续 `2026-08-25-react-antd-spa-design.md`；该规格中「不做视觉重设计 / 暗色主题」对本任务作废，其余 API / 双入口约束不变。

## Problem

SPA 已完成 Ant Design 组件化，但整体仍偏「白底 + Ant 默认蓝 + 硬编码灰边」：

- `ConfigProvider` 未接入自定义 `theme.token` / `darkAlgorithm`
- `AppShell` Header 写死 `background: '#fff'`
- `global.css` 大量 `#fff` / `#edf1f6` / `#fbfdff` 等亮色硬编码，暗色无法落地
- 交互反馈偏少（hover / 入场 / 主题切换），页面显得单调

## Goals

1. 提供可切换的 **亮色 / 暗色** 两套主题，切换状态持久化到 `localStorage`。
2. 建立统一语义色 Token（CSS 变量 + Ant Design token 同源），覆盖布局、边框、品牌色、涨跌色。
3. 用克制的微交互提升层次感（hover、选中、入场 stagger、刷新反馈），不引入娱乐风动效。
4. 保持 A 股涨跌语义：**红涨 / 绿跌**（与现有 `--gain` / `--loss` 一致）。

## Non-Goals

- 不引入 Tailwind / styled-components / 新 UI 库。
- 不引入 GSAP；动效用 CSS transition / 少量 CSS animation。
- 不把图表库换成 ECharts（沿用现有 Canvas）。
- 不做营销落地页式大 hero / 紫粉渐变 / 大面积 glow。
- 不改 `/api/*` 契约与认证方式。

## Design Direction

| 维度 | 决策 |
|------|------|
| 产品气质 | 金融工具型：冷静、密信息、可信 |
| 密度 | Dashboard 高密度（约 8–24px 间距） |
| 字体 | 继续 Fira Sans + Fira Code（数字等宽） |
| 品牌色 | 石板蓝结构 + Teal 交互强调；涨跌色独立，不与 brand 混用 |
| 默认主题 | 亮色（日间）；暗色为夜间 OLED 友好模式 |
| 模式支持 | `light` \| `dark`，Header 一键切换 |

## Color Tokens

语义名固定，亮/暗只换值。实现时 CSS 变量与 Ant `theme.token` 共用同一数据源。

### Light

| Token | 色值 | 用途 |
|-------|------|------|
| `--bg` | `#F4F7FB` | 页面底 |
| `--surface` | `#FFFFFF` | Card / Header / Drawer |
| `--surface-2` | `#EEF3F9` | 次级块、斑马纹 |
| `--ink` | `#0F172A` | 主文字 |
| `--subtle` | `#64748B` | 次要文字 |
| `--line` | `#D8E2F0` | 分割线 / 边框 |
| `--brand` | `#0F766E` | 主按钮、选中、链接 |
| `--brand-soft` | `#CCFBF1` | 选中浅底、Tag 底 |
| `--accent` | `#0369A1` | 次要强调 / 信息态 |
| `--gain` | `#DC2626` | 涨 / 盈利 |
| `--loss` | `#059669` | 跌 / 亏损 |
| `--gain-wash` | `#FEF2F2` | 日历盈利格 |
| `--loss-wash` | `#ECFDF5` | 日历亏损格 |
| `--warning` | `#D97706` | 风险指标 |
| `--ring` | `#0F766E` | Focus 环 |

Ant 映射：`colorPrimary: #0F766E`，`colorBgLayout: #F4F7FB`，`colorBgContainer: #FFFFFF`，`borderRadius: 8`。

### Dark

| Token | 色值 | 用途 |
|-------|------|------|
| `--bg` | `#020617` | 页面底 |
| `--surface` | `#0B1220` | Card / Header |
| `--surface-2` | `#111827` | 次级块 |
| `--ink` | `#F1F5F9` | 主文字 |
| `--subtle` | `#94A3B8` | 次要文字 |
| `--line` | `#1E293B` | 边框 |
| `--brand` | `#2DD4BF` | 主色（暗底提亮） |
| `--brand-soft` | `#134E4A` | 选中浅底 |
| `--accent` | `#38BDF8` | 信息 / 基准 |
| `--gain` | `#F87171` | 涨 |
| `--loss` | `#34D399` | 跌 |
| `--gain-wash` | `#3F1515` | 盈利格底 |
| `--loss-wash` | `#0F2E24` | 亏损格底 |
| `--warning` | `#FBBF24` | 风险 |
| `--ring` | `#2DD4BF` | Focus |

Ant 映射：`algorithm: theme.darkAlgorithm`，`colorPrimary: #2DD4BF`，`colorBgLayout: #020617`，`colorBgContainer: #0B1220`。

### Chart notes

- 亮色网格：浅灰线；暗色网格：`#1E293B` 低对比线。
- K 线 / 盈亏序列使用 `--gain` / `--loss`，禁止用 brand 表示涨跌。
- 涨跌含义不得仅依赖颜色：保留符号 / 箭头 / 文案。

## Interaction Spec

### Theme toggle

- 入口：`AppShell` Header 右侧图标按钮（`aria-label` 标明当前可切到的主题）。
- 状态：`uiStore.theme: 'light' | 'dark'` + `localStorage` 键 `stockai-theme`。
- 驱动：`html` 或根节点 `data-theme="light|dark"` + `ConfigProvider theme` 同步。
- 过渡：背景/文字 `150–200ms`；`prefers-reduced-motion: reduce` 时瞬时切换。
- 正确性：以 store 最终值为准，不依赖 `transitionend`。

### Micro-interactions（克制）

| 场景 | 行为 |
|------|------|
| 页面进入 | 看板区块 stagger：`opacity` + `translateY(8px)`，错开约 50ms，总时长 ≤400ms |
| Card / 行 hover | 边框或背景微亮，`150ms`；不大阴影、不大抬升 |
| 刷新 | 按钮 loading +「刚刚更新」文案（沿用 `DashboardRefreshControls`，配色走 token） |
| 涨跌数字变化 | 短暂 wash 高亮 ≤300ms，不闪屏 |
| 菜单选中 | 底边 brand 线或 soft 底，替代默认大蓝块观感 |
| Drawer / Modal | 遮罩约 0.45 黑；内容侧滑约 200ms |
| 空态 / 错误 | 沿用 Alert + 重试；暗色用 soft surface |

### Accessibility

- 可点元素：`cursor: pointer` + hover；关键控件触控高度 ≥36px。
- Focus：`outline: 2px solid var(--ring); outline-offset: 2px`，禁止裸 `outline: none`。
- 尊重 `prefers-reduced-motion`。
- 正文对比度目标 ≥ 4.5:1。

## Architecture

```
Browser
  ThemeProvider
    ├─ reads/writes uiStore.theme + localStorage
    ├─ sets data-theme on documentElement
    └─ ConfigProvider theme={getAntdTheme(mode)}
  CSS variables in global.css
    :root / [data-theme="dark"] 映射同一套 token
  Components
    禁止硬编码 #fff / #edf1f6；改用 var(--surface) 等
```

目标文件（新增 / 重点修改）：

```
frontend/src/theme/tokens.ts
frontend/src/theme/antdTheme.ts
frontend/src/theme/ThemeProvider.tsx
frontend/src/components/theme/ThemeToggle.tsx
frontend/src/stores/uiStore.ts          # + theme / setTheme / toggleTheme
frontend/src/main.tsx                   # wrap ThemeProvider
frontend/src/layouts/AppShell.tsx       # ThemeToggle + 去硬编码背景
frontend/src/styles/global.css          # 双主题变量 + 硬编码替换
```

## Rollout Priority

1. **P0** Token + ThemeProvider + Header 切换 + 持久化  
2. **P0** AppShell / Content / Card 底色走变量  
3. **P1** 看板入场与 hover；图表配色跟主题  
4. **P1** 日历 wash、图例、周期 Tab 暗色适配  
5. **P2** 数字闪动反馈、reduced-motion 收口  

## Explicit Anti-Patterns

- 紫色渐变、大面积 glow、圆角胶囊堆砌  
- 将 brand 当作涨跌色  
- 仅靠颜色传达涨跌  
- 为动效引入重型动画库  

## Acceptance Criteria

- [x] Header 可在亮/暗之间切换，刷新后主题仍保留（实现已落地，待手动确认）
- [x] 亮色与暗色下看板、策略、回测、日报、标的详情主路径可读，无大片未适配白块（硬编码已替换为 CSS 变量）
- [x] Ant 主色与 CSS `--brand` 一致；涨跌色仍为红涨绿跌
- [x] 键盘 Focus 环在两主题下均可见（`:focus-visible`）
- [x] `prefers-reduced-motion` 下无强制入场动画
- [x] 不改变任何 `/api/*` 行为
