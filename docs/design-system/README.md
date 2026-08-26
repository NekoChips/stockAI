# StockAI 前端设计规范

**状态：** 生效中（2026-08-26 grill 共识）  
**产品：** StockAI 策略执行台（React + Ant Design SPA）  
**性质：** 活的设计规范 — 原则与关键模式强约束；页面级布局为推荐而非逐组件死规矩。

## 读者指南

| 你是… | 读这些 |
|-------|--------|
| 产品 / 验收 | §1 气质与锁定决策 · §6 禁止项 · §8 短验收清单 |
| 实现前端 / Agent | 全文；改色前先读 §2 与 §7 |

## 权威来源（代码为真）

| 层级 | Canonical 路径 |
|------|----------------|
| 语义色 TS | `frontend/src/theme/tokens.ts` |
| Ant Design 主题 | `frontend/src/theme/antdTheme.ts` |
| CSS 变量与布局类 | `frontend/src/styles/global.css` |
| 主题状态 | `frontend/src/stores/uiStore.ts`（键 `stockai-theme`） |
| 主题 Provider | `frontend/src/theme/ThemeProvider.tsx` |

**文档中的色表是镜像。** 色值冲突时以代码为准，并按 §7 回写本文。

历史实现记录（非权威）：[`docs/superpowers/specs/2026-08-26-dual-theme-ux-design.md`](../superpowers/specs/2026-08-26-dual-theme-ux-design.md)。功能门禁另见 [`docs/superpowers/parity-checklist.md`](../superpowers/parity-checklist.md)。

---

## 1. 产品气质与锁定决策

**一句话：** 冷静、密信息、可信的金融工具台 — 不是营销站，不是娱乐看板。

| 决策 | 锁定值 |
|------|--------|
| 涨跌语义 | **A 股：红涨 / 绿跌**（`--gain` / `--loss`）；不得用 brand 表示涨跌 |
| 主题 | 仅 `light` \| `dark`；**默认亮色**；Header 可切换并持久化 |
| 品牌色 | Teal 族交互强调 + 石板结构色；涨跌色独立 |
| 字体 | **Fira Sans**（UI）+ **Fira Code**（数字/代码）；中文回落 PingFang SC / Microsoft YaHei |
| 密度 | Dashboard **高密度**，间距带约 **8–24px** |
| UI 栈 | React + Ant Design 5 + 少量全局 CSS；**不引入** Tailwind / styled-components / 新 UI 库 |
| 动效 | CSS transition / 少量 CSS animation；**不引入 GSAP** |
| 图表 | 现有 Canvas；本阶段**不换 ECharts** |
| 圆角 | Ant `borderRadius: 8` 为默认 |

签名记忆点：品牌字标 `Stock` + 青色 `AI`；导航选中底边 Teal；日月主题切换。

---

## 2. 颜色 Token

语义名固定，亮/暗只换值。CSS 使用 kebab（如 `--surface-2`）；TS 使用 camel（如 `surface2`）。

### 2.1 Light

| Token (CSS) | 色值 | 用途 |
|-------------|------|------|
| `--bg` | `#F4F7FB` | 页面底 |
| `--surface` | `#FFFFFF` | Card / Header / Drawer |
| `--surface-2` | `#EEF3F9` | 次级块、斑马纹 |
| `--ink` | `#0F172A` | 主文字 |
| `--subtle` | `#64748B` | 次要文字 |
| `--quiet` | `#64748B` | 更弱说明（须满足对比度） |
| `--line` | `#D8E2F0` | 分割线 / 边框 |
| `--brand` | `#0F766E` | 主按钮、选中、链接 |
| `--brand-soft` | `#CCFBF1` | 选中浅底 |
| `--accent` | `#0369A1` | 次要强调 / 信息态 |
| `--gain` | `#DC2626` | 涨 / 盈利 |
| `--loss` | `#059669` | 跌 / 亏损 |
| `--gain-wash` | `#FEF2F2` | 盈利格底 |
| `--loss-wash` | `#ECFDF5` | 亏损格底 |
| `--warning` | `#D97706` | 风险 |
| `--ring` | `#0F766E` | Focus 环 |

### 2.2 Dark

| Token (CSS) | 色值 | 用途 |
|-------------|------|------|
| `--bg` | `#020617` | 页面底 |
| `--surface` | `#0B1220` | Card / Header |
| `--surface-2` | `#111827` | 次级块 |
| `--ink` | `#F1F5F9` | 主文字 |
| `--subtle` | `#94A3B8` | 次要文字 |
| `--quiet` | `#94A3B8` | 更弱说明 |
| `--line` | `#1E293B` | 边框 |
| `--brand` | `#2DD4BF` | 主色（暗底提亮） |
| `--brand-soft` | `#134E4A` | 选中浅底 |
| `--accent` | `#38BDF8` | 信息 / 基准 |
| `--gain` | `#F87171` | 涨 |
| `--loss` | `#34D399` | 跌 |
| `--gain-wash` | `#3F1515` | 盈利格底 |
| `--loss-wash` | `#0F2E24` | 亏损格底 |
| `--warning` | `#FBBF24` | 风险 |
| `--ring` | `#2DD4BF` | Focus 环 |

### 2.3 Ant Design 映射原则

- `colorPrimary` ← `brand`；`colorInfo` ← `accent`；`colorWarning` ← `warning`
- `colorError` / `colorSuccess` 槽位可映射到 gain/loss **仅供 Ant 默认组件态**；**业务涨跌展示一律用 `.gain` / `.loss` 或对应 CSS 变量**，不要把 `Tag color="success"` 当成「上涨」
- `colorBgLayout` ← `bg`；`colorBgContainer` ← `surface`
- 暗色：`algorithm: theme.darkAlgorithm`

### 2.4 对比度

- 正文（`--ink`）对表面：**≥ 4.5:1**（亮/暗均要测）
- 次要文字（`--subtle` / `--quiet`）对所用背景：**≥ 4.5:1**；不够则改 Token，不要硬编码浅灰
- 非文本控件 / Focus 环：目标 **≥ 3:1** 状态对比

---

## 3. 字体与数字

- UI 文案：Fira Sans
- 价格、收益率、代码、时间戳：Fira Code + `font-variant-numeric: tabular-nums`（类名 `.tabular`）
- 字重以 400 / 500 / 600 / 700 为主；避免依赖非标准字重名冒充精确渲染

---

## 4. 关键模式（推荐且应遵守）

### 4.1 主题切换

- 入口：`AppShell` Header 右侧；`aria-label` 描述将切到的主题
- 触控目标：**≥ 44×44px**
- 状态：`uiStore` + `localStorage`（`stockai-theme`）
- 驱动：`document.documentElement.dataset.theme` + `ConfigProvider`
- 过渡：背景/文字约 150–200ms；`prefers-reduced-motion: reduce` 时瞬时
- 正确性以 store 最终值为准，**不依赖** `transitionend`

### 4.2 选中 / 图例 / 周期 Tab

- 选中：`border` + `background: var(--brand-soft)` + 文字 `var(--brand)`
- 未选中可降透明度；**不要用删除线**作为唯一「隐藏」暗示（暗色难读）

### 4.3 表格与分区

- 斑马 / 次级底：`--surface-2`
- 分割：`--line`
- 禁止在组件里写死 `#fff` / `#edf1f6` / `#fbfdff` 等亮色字面量

### 4.4 涨跌展示

- 颜色 + 符号/文案/方向词（如「跑赢 / 跑输」）
- 日历等 wash 使用 `--gain-wash` / `--loss-wash`

### 4.5 动效（克制）

| 场景 | 约定 |
|------|------|
| 看板入场 | 可选 stagger，`opacity` + `translateY(≤8px)`，总时长 ≤400ms |
| Hover | 150ms 级边框/背景；不大阴影、不大抬升 |
| 刷新 | loading +「刚刚更新」类反馈 |
| Drawer | Ant 默认即可；遮罩保持可读 |

同一视口不要堆叠多种装饰性动画。必须尊重 `prefers-reduced-motion`。

### 4.6 Focus 与可访问性

```css
:focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}
```

- 禁止无替代的 `outline: none`
- 图标按钮必须有 accessible name（`aria-label` 或可见文本）
- 装饰性图标旁若有可见文字，图标可 `aria-hidden`

### 4.7 空态与错误

- 错误：顶部/就近 Alert + **重试**；文案说明「出了什么问题、下一步做什么」
- 空态：一句说明 + 一个主操作（若适用）；不要卖萌长文

---

## 5. 图表

- 网格、轴标签、十字线、空态文字：通过 `cssVar` / `chartPalette()` 读主题变量（见 `frontend/src/theme/cssVars.ts`）
- K 线涨跌：`--gain` / `--loss`；实心/空心等形态补充颜色语义
- 主序列「AI-Agent」线色跟 `--brand`
- 主题切换后必须重绘 Canvas（订阅 `uiStore.theme`）
- Tooltip 背景/文字用 `--surface` / `--ink`
- 系列分类色可固定色相区分，但须在**两主题下**仍可辨；过暗则调整

---

## 6. 禁止项

- 紫色 / 粉紫渐变主题、大面积 glow、霓虹酸绿点缀
- 用 brand / Ant `success` 色表示「上涨」
- **仅靠颜色**传达涨跌或状态
- 组件内硬编码亮色背景/边框（应使用 CSS 变量或 token）
- 引入 Tailwind、styled-components、GSAP、本阶段换 ECharts
- 用 emoji 充当系统/导航图标
- 去掉 Focus 环且无替代
- **仅 hover** 才能完成的关键操作（触控不可达）
- 为装饰而堆砌卡片阴影、胶囊标签墙、无信息编号（01/02/03）

---

## 7. 如何改本规范

1. **先改代码**：`tokens.ts`（及必要的 `antdTheme.ts` / `global.css`）  
2. **同步本文色表与受影响章节**  
3. PR 说明写清：影响亮/暗哪些表面；是否需手动扫暗色漏白  
4. 不新增第三套主题名，除非另开 grill 共识  

---

## 8. 短验收清单（设计向）

发版或大改 UI 前自检：

- [ ] Header 可切换亮/暗；刷新后主题保留  
- [ ] 暗色下看板 / 策略 / 日报 / 标的 / 观察池抽屉无大片未适配白块  
- [ ] 主文与次要文对比度达标；`--quiet` 未退化成不可读灰  
- [ ] 涨跌为红涨绿跌，且有非颜色线索  
- [ ] 主题按钮 ≥44×44，且有 `aria-label`  
- [ ] Focus 环两主题可见；`prefers-reduced-motion` 下无强制入场动画  
- [ ] 无新增硬编码 `#fff` / `#edf1f6` 一类亮色字面量（业务色除外且须有暗色方案）  

SPA 功能对等门禁仍以 [`parity-checklist.md`](../superpowers/parity-checklist.md) 为准。

---

## 9. 文案语气（界面）

- 简体中文；控件用能说清结果的动词（「保存更改」「确认生效」「重试」）  
- 同一操作全流程用词一致  
- 错误不道歉套话；说清原因与下一步  
- 空态是行动邀请，不是气氛散文  
