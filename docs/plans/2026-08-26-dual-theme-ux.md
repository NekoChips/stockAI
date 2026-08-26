# StockAI 双主题与交互增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 React + Ant Design SPA 落地可切换的亮色/暗色主题与克制微交互，消除页面单调感，并保持 A 股红涨绿跌语义。

**Architecture:** 以 `tokens.ts` 为唯一色值源，同步驱动 CSS `data-theme` 变量与 Ant Design `ConfigProvider`（含 `darkAlgorithm`）。主题状态放在现有 zustand `uiStore`，并用 `localStorage` 持久化。组件侧逐步消除硬编码亮色，图表/日历在 P1 跟主题。

**Tech Stack:** React 18、TypeScript、Ant Design 5（`theme` / `darkAlgorithm`）、zustand、现有 Vite SPA、CSS 变量（无 Tailwind / GSAP）。

**Spec:** `docs/specs/2026-08-26-dual-theme-ux-design.md`

## Global Constraints

- 涨跌语义固定：红涨 / 绿跌（`--gain` / `--loss`），禁止用 brand 表示涨跌。
- 主题仅 `light` | `dark`；持久化键名固定为 `stockai-theme`。
- 不改 `/api/*` 契约、认证、路由结构。
- 不引入 Tailwind、styled-components、GSAP、ECharts。
- 文档与 UI 文案使用中文；代码标识符用英文。
- 动效默认 150–200ms；必须尊重 `prefers-reduced-motion`。
- Focus 环可见：`outline: 2px solid var(--ring); outline-offset: 2px`。
- 不提交构建产物；前端改动以 `frontend/` 源码为准。
- 每完成一个 Task 且自测通过后再提交（若用户要求提交）。

---

## File Structure (target)

```
frontend/src/
  theme/
    tokens.ts              # light/dark 语义色与 Ant token 映射数据
    antdTheme.ts           # getAntdTheme(mode)
    ThemeProvider.tsx      # ConfigProvider + data-theme 同步
  components/theme/
    ThemeToggle.tsx        # Header 切换按钮
  stores/uiStore.ts        # + theme / setTheme / toggleTheme
  main.tsx                 # ThemeProvider 包裹
  layouts/AppShell.tsx     # 接入 ThemeToggle，去掉硬编码白底
  styles/global.css        # :root / [data-theme="dark"] + 替换硬编码色
  pages/DashboardPage.tsx  # 可选：入场 class（P1）
  components/performance/  # 图表网格/tooltip 跟主题（P1）
  components/calendar/     # wash 走变量（P1）
  components/instrument/   # 周期 Tab / tooltip（P1）
docs/
  specs/2026-08-26-dual-theme-ux-design.md
  plans/2026-08-26-dual-theme-ux.md
```

---

### Task 1: Theme tokens + Ant Design theme 工厂

**Files:**
- Create: `frontend/src/theme/tokens.ts`
- Create: `frontend/src/theme/antdTheme.ts`

**Interfaces:**
- Consumes: 无
- Produces:
  - `export type ThemeMode = 'light' | 'dark'`
  - `export const THEME_STORAGE_KEY = 'stockai-theme'`
  - `export const themeTokens: Record<ThemeMode, { /* 见下 */ }>`
  - `export function getAntdTheme(mode: ThemeMode): ThemeConfig`

- [ ] **Step 1: 创建 `tokens.ts`**

```ts
export type ThemeMode = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'stockai-theme';

export interface SemanticTokens {
  bg: string;
  surface: string;
  surface2: string;
  ink: string;
  subtle: string;
  line: string;
  brand: string;
  brandSoft: string;
  accent: string;
  gain: string;
  loss: string;
  gainWash: string;
  lossWash: string;
  warning: string;
  ring: string;
}

export const themeTokens: Record<ThemeMode, SemanticTokens> = {
  light: {
    bg: '#F4F7FB',
    surface: '#FFFFFF',
    surface2: '#EEF3F9',
    ink: '#0F172A',
    subtle: '#64748B',
    line: '#D8E2F0',
    brand: '#0F766E',
    brandSoft: '#CCFBF1',
    accent: '#0369A1',
    gain: '#DC2626',
    loss: '#059669',
    gainWash: '#FEF2F2',
    lossWash: '#ECFDF5',
    warning: '#D97706',
    ring: '#0F766E',
  },
  dark: {
    bg: '#020617',
    surface: '#0B1220',
    surface2: '#111827',
    ink: '#F1F5F9',
    subtle: '#94A3B8',
    line: '#1E293B',
    brand: '#2DD4BF',
    brandSoft: '#134E4A',
    accent: '#38BDF8',
    gain: '#F87171',
    loss: '#34D399',
    gainWash: '#3F1515',
    lossWash: '#0F2E24',
    warning: '#FBBF24',
    ring: '#2DD4BF',
  },
};

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark';
}
```

- [ ] **Step 2: 创建 `antdTheme.ts`**

```ts
import { theme, type ThemeConfig } from 'antd';
import { themeTokens, type ThemeMode } from './tokens';

export function getAntdTheme(mode: ThemeMode): ThemeConfig {
  const t = themeTokens[mode];
  return {
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: t.brand,
      colorInfo: t.accent,
      colorSuccess: t.loss, // A股：绿=跌/亏损侧成功态慎用；仅作 Ant success 槽位，业务涨跌仍用 CSS .gain/.loss
      colorError: t.gain,
      colorWarning: t.warning,
      colorBgLayout: t.bg,
      colorBgContainer: t.surface,
      colorText: t.ink,
      colorTextSecondary: t.subtle,
      colorBorder: t.line,
      colorBorderSecondary: t.line,
      borderRadius: 8,
      fontFamily:
        '"Fira Sans", "PingFang SC", "Microsoft YaHei", sans-serif',
    },
    components: {
      Layout: {
        headerBg: t.surface,
        bodyBg: t.bg,
      },
      Menu: {
        itemSelectedColor: t.brand,
        horizontalItemSelectedColor: t.brand,
      },
    },
  };
}
```

注意：业务涨跌展示继续用 `.gain` / `.loss` CSS 类，不要把 `Tag color="success"` 当成「上涨」。

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --pretty false`  
Expected: 无新增错误（若项目尚无测试框架，以 tsc 为准）。

---

### Task 2: uiStore 主题状态 + ThemeProvider

**Files:**
- Modify: `frontend/src/stores/uiStore.ts`
- Create: `frontend/src/theme/ThemeProvider.tsx`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `ThemeMode`, `THEME_STORAGE_KEY`, `isThemeMode`, `getAntdTheme`
- Produces:
  - `useUiStore`: `theme`, `setTheme(mode)`, `toggleTheme()`
  - `ThemeProvider({ children })`：同步 `document.documentElement.dataset.theme` 与 Ant `ConfigProvider`

- [ ] **Step 1: 扩展 `uiStore.ts`**

```ts
import { create } from 'zustand';
import {
  THEME_STORAGE_KEY,
  isThemeMode,
  type ThemeMode,
} from '@/theme/tokens';

function readStoredTheme(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeMode(raw)) return raw;
  } catch {
    /* ignore */
  }
  return 'light';
}

interface UiState {
  notice: string;
  liveMessage: string;
  theme: ThemeMode;
  setNotice: (message: string) => void;
  announce: (message: string) => void;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  notice: '',
  liveMessage: '',
  theme: readStoredTheme(),
  setNotice: (notice) => set({ notice }),
  announce: (liveMessage) => set({ liveMessage }),
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
    set({ theme });
  },
  toggleTheme: () => {
    const next: ThemeMode = get().theme === 'light' ? 'dark' : 'light';
    get().setTheme(next);
  },
}));
```

- [ ] **Step 2: 创建 `ThemeProvider.tsx`**

```tsx
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useEffect, type ReactNode } from 'react';
import { useUiStore } from '@/stores/uiStore';
import { getAntdTheme } from '@/theme/antdTheme';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const themeMode = useUiStore((s) => s.theme);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
  }, [themeMode]);

  return (
    <ConfigProvider locale={zhCN} theme={getAntdTheme(themeMode)}>
      {children}
    </ConfigProvider>
  );
}
```

- [ ] **Step 3: 改 `main.tsx`**

移除外层单独的 `ConfigProvider locale={zhCN}`，改为：

```tsx
<QueryClientProvider client={queryClient}>
  <ThemeProvider>
    <App />
  </ThemeProvider>
</QueryClientProvider>
```

确保 `zhCN` 与 dayjs locale 初始化仍保留在 `main.tsx` 或 `ThemeProvider` 之一，不要丢中文 locale。

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --pretty false`  
Expected: PASS。

---

### Task 3: ThemeToggle + AppShell 接入

**Files:**
- Create: `frontend/src/components/theme/ThemeToggle.tsx`
- Modify: `frontend/src/layouts/AppShell.tsx`

**Interfaces:**
- Consumes: `useUiStore().theme / toggleTheme`
- Produces: Header 右侧可访问的主题切换按钮

- [ ] **Step 1: 创建 `ThemeToggle.tsx`**

```tsx
import { Button, Tooltip } from 'antd';
import { BulbOutlined, BulbFilled } from '@ant-design/icons';
import { useUiStore } from '@/stores/uiStore';

export function ThemeToggle() {
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const nextLabel = theme === 'light' ? '切换到暗色主题' : '切换到亮色主题';

  return (
    <Tooltip title={nextLabel}>
      <Button
        type="text"
        aria-label={nextLabel}
        onClick={toggleTheme}
        icon={theme === 'light' ? <BulbOutlined /> : <BulbFilled />}
      />
    </Tooltip>
  );
}
```

- [ ] **Step 2: 修改 `AppShell.tsx`**

- Header 去掉 `background: '#fff'`（交给 Ant Layout token）。
- 在 `Menu` 与右侧操作区之间或 Header 末尾插入 `<ThemeToggle />`。
- Header 布局保持 `display: flex; alignItems: center; gap: 16`。

- [ ] **Step 3: 手动验证**

Run: `cd frontend && npm run dev`  
操作：点击切换 → 页面主色/背景变化；刷新 → 主题保留。  
Expected: `localStorage.stockai-theme` 为 `light` 或 `dark`；`document.documentElement.dataset.theme` 同步。

---

### Task 4: global.css 双主题变量 + 去掉硬编码亮色（P0 范围）

**Files:**
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: `data-theme` on `html`
- Produces: `:root` / `[data-theme='dark']` 下完整语义变量；业务类改用 `var(...)`

- [ ] **Step 1: 在文件顶部重写变量块**

```css
:root,
[data-theme='light'] {
  --bg: #f4f7fb;
  --surface: #ffffff;
  --surface-2: #eef3f9;
  --ink: #0f172a;
  --subtle: #64748b;
  --line: #d8e2f0;
  --brand: #0f766e;
  --brand-soft: #ccfbf1;
  --accent: #0369a1;
  --gain: #dc2626;
  --loss: #059669;
  --gain-wash: #fef2f2;
  --loss-wash: #ecfdf5;
  --warning: #d97706;
  --ring: #0f766e;
  --blue-dark: var(--brand);
  --quiet: #98a2b3;
}

[data-theme='dark'] {
  --bg: #020617;
  --surface: #0b1220;
  --surface-2: #111827;
  --ink: #f1f5f9;
  --subtle: #94a3b8;
  --line: #1e293b;
  --brand: #2dd4bf;
  --brand-soft: #134e4a;
  --accent: #38bdf8;
  --gain: #f87171;
  --loss: #34d399;
  --gain-wash: #3f1515;
  --loss-wash: #0f2e24;
  --warning: #fbbf24;
  --ring: #2dd4bf;
  --blue-dark: var(--brand);
  --quiet: #64748b;
}

body {
  margin: 0;
  min-width: 320px;
  color: var(--ink);
  background: var(--bg);
  font-family: "Fira Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
  transition: background-color 160ms ease, color 160ms ease;
}

@media (prefers-reduced-motion: reduce) {
  body {
    transition: none;
  }
}
```

保留现有 `.gain` / `.loss` / `.kicker` / `.tabular` / `.sr-only`。

- [ ] **Step 2: 替换本文件内硬编码色**

按下列映射批量替换（仅 `global.css` 内字面量）：

| 旧值（示例） | 新值 |
|--------------|------|
| `#fff` / `#ffffff` / `background: #fff` | `var(--surface)` |
| `#fbfdff` / `#f8fafc` / `#fcfdff` | `var(--surface-2)` 或 `var(--surface)`（按层级选） |
| `#edf1f6` / `#e8eef6` / `#dce5f2` | `var(--line)` |
| `#f8fbff` / `#f5f9ff` | `var(--brand-soft)`（选中/强调底）或 `var(--surface-2)` |
| `#b9cde9` / `#a9c8f7` / `#d5e2f4` / `#c8d7ec` | `var(--line)` 或 `var(--brand)`（边框选中用 brand） |
| `#fff0ee` / `#ebf8f2` | 已由 `--gain-wash` / `--loss-wash` 覆盖处改为变量 |
| tooltip `rgba(255,255,255,0.98)` | `color-mix(in srgb, var(--surface) 98%, transparent)` 或直接 `var(--surface)` |

选中态（`.legend-toggle[aria-pressed="true"]`、`.instrument-period-tabs button.active`）改为：

```css
border-color: var(--brand);
background: var(--brand-soft);
color: var(--brand);
```

- [ ] **Step 3: Focus 与可点反馈**

```css
:focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}

.legend-toggle,
.instrument-period-tabs button,
.value-toggle {
  transition: background-color 150ms ease, border-color 150ms ease, color 150ms ease,
    opacity 150ms ease;
}

@media (prefers-reduced-motion: reduce) {
  .legend-toggle,
  .instrument-period-tabs button,
  .value-toggle {
    transition: none;
  }
}
```

- [ ] **Step 4: 手动扫暗色漏白**

Run: `npm run dev`，切到暗色，打开看板 / 标的详情。  
Expected: 图例、日历、图表工具条无大片刺眼白底；文字对比可读。

---

### Task 5: 看板微交互（P1）

**Files:**
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/pages/DashboardPage.tsx`（仅加 className，不改数据逻辑）

**Interfaces:**
- Consumes: `prefers-reduced-motion`
- Produces: 看板区块入场 stagger class；可选 Card hover 类

- [ ] **Step 1: 增加 CSS**

```css
@keyframes dash-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.dash-enter > * {
  animation: dash-enter 360ms ease both;
}

.dash-enter > *:nth-child(1) { animation-delay: 0ms; }
.dash-enter > *:nth-child(2) { animation-delay: 50ms; }
.dash-enter > *:nth-child(3) { animation-delay: 100ms; }
.dash-enter > *:nth-child(4) { animation-delay: 150ms; }
.dash-enter > *:nth-child(5) { animation-delay: 200ms; }
.dash-enter > *:nth-child(6) { animation-delay: 250ms; }

@media (prefers-reduced-motion: reduce) {
  .dash-enter > * {
    animation: none;
  }
}
```

- [ ] **Step 2: Dashboard 根网格加 `dash-enter`**

在 `DashboardPage` 主内容 `Row`/`div` 上增加 `className="dash-enter"`（保持现有 gutter / Col 结构不变）。

- [ ] **Step 3: 手动验证**

亮/暗主题下刷新看板：有短暂错落入场；系统「减少动态效果」开启时无动画。

---

### Task 6: 图表与日历跟主题（P1）

**Files:**
- Modify: `frontend/src/components/performance/lineChart.ts`（或实际绘制文件）
- Modify: `frontend/src/components/instrument/instrumentChart.ts`（若存在硬编码色）
- Modify: 相关 tooltip / 网格色读取处

**Interfaces:**
- Consumes: `getComputedStyle(document.documentElement).getPropertyValue('--line'| '--ink'| '--gain'| '--loss'| '--surface')`
- Produces: 主题切换后重绘或下次绘制使用新色

- [ ] **Step 1: 抽取读 CSS 变量助手**（可放在 `frontend/src/theme/cssVars.ts`）

```ts
export function cssVar(name: string, fallback = ''): string {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}
```

- [ ] **Step 2: 图表绘制时用变量**

- 网格 / 轴：`cssVar('--line')`、`cssVar('--subtle')`
- 涨跌序列：`cssVar('--gain')`、`cssVar('--loss')`
- tooltip 背景：`cssVar('--surface')`，文字：`cssVar('--ink')`

- [ ] **Step 3: 主题切换后触发重绘**

在使用 canvas 的 React 组件里订阅 `useUiStore(s => s.theme)`，`theme` 变化时调用现有 resize/redraw。  
不要在 store 里塞 canvas 引用。

- [ ] **Step 4: 手动验证**

切换主题后绩效图与标的图网格/tooltip 立即跟随；涨跌色仍为红/绿。

---

### Task 7: 验收清单与文档回写

**Files:**
- Modify: `docs/specs/2026-08-26-dual-theme-ux-design.md`（勾选 Acceptance）
- Modify: `docs/design/2026-08-25-frontend-parity-checklist.md`（若存在前端检查项，追加主题两项）

- [ ] **Step 1: 按规格 Acceptance Criteria 逐项勾选**

- Header 切换 + 刷新保留  
- 主路径无大片未适配白块  
- Ant 主色与 `--brand` 一致；涨跌红绿  
- Focus 环两主题可见  
- reduced-motion 无强制入场  
- `/api/*` 无行为变化  

- [ ] **Step 2: 在 parity checklist 增加**

```markdown
- [ ] 主题：亮/暗切换、刷新后保留
- [ ] 暗色：看板 / 标的详情 / 策略中心无未适配白底
```

- [ ] **Step 3: 最终 typecheck + build**

Run:

```bash
cd frontend
npx tsc -b --pretty false
npm run build
```

Expected: 成功产出到现有 SPA outDir（按仓库既有 vite 配置）。

---

## Spec coverage (self-review)

| Spec 要求 | Task |
|-----------|------|
| 双主题 Token 表 | Task 1 + Task 4 |
| Ant ConfigProvider / darkAlgorithm | Task 1–2 |
| uiStore + localStorage | Task 2 |
| Header ThemeToggle | Task 3 |
| 消除硬编码亮色 | Task 4 |
| 入场 stagger / reduced-motion | Task 5 |
| 图表跟主题 | Task 6 |
| Acceptance / checklist | Task 7 |
| 不引入 Tailwind/GSAP/改 API | Global Constraints |

## Placeholder scan

无 TBD /「类似 Task N」占位；色值与关键代码块已内联。

## Type consistency

- `ThemeMode`、`THEME_STORAGE_KEY`、`getAntdTheme`、`setTheme` / `toggleTheme` 命名在 Task 1–3 一致。
- CSS 变量名使用 kebab（`--surface-2`），TS 对象用 camel（`surface2`），映射仅在 CSS 与 Ant token 层转换。
