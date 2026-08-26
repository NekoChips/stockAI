# React + Ant Design SPA Dual-Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic `dashboard.html` UI with a TypeScript React + Ant Design SPA at `/app`, served by the existing Python HTTP server, while keeping legacy `/` until manual feature parity, then cut over.

**Architecture:** Vite SPA (`base: '/app/'`) talks to unchanged `/api/*` JSON endpoints. Python gains static + SPA fallback under `/app`. Docker adds a Node 22 builder stage that writes assets into `src/stock_ai_agent/spa/` before the Python package install. Data layer uses TanStack Query + a small zustand store; charts port existing Canvas logic first.

**Tech Stack:** React 18, TypeScript, Vite 6, Ant Design 5, TanStack Query 5, zustand, React Router 6, dayjs, npm, Python 3.12 stdlib HTTP server, Node 22 Docker stage.

**Spec:** `docs/specs/2026-08-25-react-antd-spa-design.md`

## Global Constraints

- Dual entry until cutover: legacy `GET /` → `dashboard.html`; SPA `GET /app` and `GET /app/*`.
- Do not change `/api/*` request/response contracts.
- Keep browser Basic Auth; use `credentials: 'same-origin'` on `fetch`.
- TypeScript strict; no `any` in `frontend/src/api` or `frontend/src/types`.
- npm only (`package-lock.json`); no pnpm/yarn.
- Ant Design defaults OK; global CSS only for gain/loss colors and chart layout.
- Canvas charts: port from `dashboard.html`, do not swap to ECharts in this plan.
- Do not commit built SPA bundles; gitignore `src/stock_ai_agent/spa/**` except `.gitkeep`.
- Cutover is a separate final task after the manual parity checklist in the spec.
- Legacy `tests/test_web.py::test_dashboard_html_references_local_api` stays until cutover.
- Prefer small focused files; do not grow `dashboard.html`.
- Commits: one logical commit per task after tests pass.

---

## File Structure (target)

```
frontend/
  package.json
  package-lock.json
  tsconfig.json
  tsconfig.app.json
  tsconfig.node.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    vite-env.d.ts
    styles/global.css
    api/client.ts
    api/dashboard.ts
    api/watchlist.ts
    api/strategies.ts
    api/backtests.ts
    api/reports.ts
    api/instruments.ts
    api/risk.ts
    types/dashboard.ts
    stores/uiStore.ts
    layouts/AppShell.tsx
    pages/DashboardPage.tsx
    pages/BacktestPage.tsx
    pages/StrategyPage.tsx
    pages/DailyReportPage.tsx
    pages/InstrumentDetailPage.tsx
    components/account/AccountStrip.tsx
    components/risk/RiskConfigPanel.tsx
    components/performance/PerformancePanel.tsx
    components/performance/lineChart.ts
    components/calendar/ProfitCalendar.tsx
    components/positions/PositionsTable.tsx
    components/decisions/DecisionTimeline.tsx
    components/leaderboard/Leaderboard.tsx
    components/activity/RecentActivity.tsx
    components/watchlist/AddInstrumentDrawer.tsx
    components/backtest/BacktestPanel.tsx
    components/strategy/StrategyWorkspace.tsx
    components/reports/ReportArchive.tsx
    components/instrument/InstrumentDetail.tsx
    components/instrument/instrumentChart.ts
    utils/format.ts
src/stock_ai_agent/
  spa/.gitkeep
  web_assets.py          # legacy HTML + SPA index/static helpers
  web_http.py            # /app routes + fallback
  dashboard.html         # unchanged until cutover
Dockerfile               # Node 22 frontend stage
pyproject.toml           # package-data spa
.gitignore
    docs/design/2026-08-25-frontend-parity-checklist.md
```

---

### Task 1: SPA asset helpers + HTTP dual-entry routes

**Files:**
- Create: `src/stock_ai_agent/spa/.gitkeep`
- Modify: `src/stock_ai_agent/web_assets.py`
- Modify: `src/stock_ai_agent/web_http.py`
- Modify: `src/stock_ai_agent/web.py` (re-export if needed)
- Modify: `src/stock_ai_agent/web_server.py` (re-export if needed)
- Modify: `.gitignore`
- Test: `tests/test_web_spa.py`

**Interfaces:**
- Consumes: existing `_send`, `_require_authorization`, `render_dashboard_html`, `serve_dashboard` handler body
- Produces:
  - `spa_root() -> Path`
  - `render_spa_index() -> str` (raises `FileNotFoundError` if missing)
  - `resolve_spa_file(url_path: str) -> Path | None` (only files under spa root; rejects `..`)
  - `create_dashboard_server(config, store, host="127.0.0.1", port=0) -> BoundedThreadingHTTPServer`
  - HTTP: `GET /app`, `GET /app/`, `GET /app/assets/...`, unknown `/app/*` → index.html when SPA present
  - `serve_dashboard` becomes `create_dashboard_server(...); server.serve_forever()`

- [ ] **Step 1: Write the failing tests**

Note: `tests/test_web.py` does **not** boot HTTPServer; it unit-tests payload builders and `render_dashboard_html()`. Follow that style for asset helpers, and add one threaded HTTP smoke test by extracting a non-blocking bind helper.

First, add to `web_http.py` (will implement in Step 4, but write the test against this API now):

```python
def create_dashboard_server(config: AppConfig, store, host: str = "127.0.0.1", port: int = 0) -> BoundedThreadingHTTPServer:
    """Bind a dashboard server without calling serve_forever (for tests)."""
    ...
```

Create `tests/test_web_spa.py`:

```python
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from stock_ai_agent.config import load_config
from stock_ai_agent.storage.mock import MockMarketDataStore as SQLiteMarketDataStore
from stock_ai_agent import web_assets
from stock_ai_agent.web_http import create_dashboard_server


class SpaAssetTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.spa_dir = Path(self._tmpdir.name)
        (self.spa_dir / "index.html").write_text(
            "<!doctype html><title>StockAI SPA</title><div id='root'></div>",
            encoding="utf-8",
        )
        assets = self.spa_dir / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
        self._old = web_assets.spa_root
        web_assets.spa_root = lambda: self.spa_dir  # type: ignore[method-assign]

    def tearDown(self):
        web_assets.spa_root = self._old  # type: ignore[method-assign]
        self._tmpdir.cleanup()

    def test_render_spa_index_reads_file(self):
        html = web_assets.render_spa_index()
        self.assertIn("StockAI SPA", html)
        self.assertIn("id='root'", html)

    def test_resolve_spa_file_allows_assets(self):
        path = web_assets.resolve_spa_file("/app/assets/app.js")
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.read_text(encoding="utf-8"), "console.log('ok')")

    def test_resolve_spa_file_blocks_traversal(self):
        self.assertIsNone(web_assets.resolve_spa_file("/app/../web_http.py"))
        self.assertIsNone(web_assets.resolve_spa_file("/app/assets/../../web_http.py"))

    def test_http_app_index_asset_fallback_and_legacy_root(self):
        config = load_config()
        store = SQLiteMarketDataStore()
        server = create_dashboard_server(config, store, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)

            conn.request("GET", "/app")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertIn("StockAI SPA", body)

            conn.request("GET", "/app/unknown-client-route")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertIn("id='root'", body)

            conn.request("GET", "/app/assets/app.js")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertEqual(body, "console.log('ok')")

            conn.request("GET", "/")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            self.assertEqual(res.status, 200)
            self.assertIn("StockAI · 策略执行台", body)
        finally:
            server.shutdown()
            server.server_close()
```

If `load_config()` requires files, use the same config construction pattern as other tests in `tests/test_web.py` (`load_config()` is already used there successfully).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_web_spa -v`  
Expected: FAIL (`spa_root` / `render_spa_index` / `create_dashboard_server` missing)

- [ ] **Step 3: Implement `web_assets` SPA helpers**

Replace/extend `src/stock_ai_agent/web_assets.py`:

```python
"""Web static assets and HTML rendering."""

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def spa_root() -> Path:
    return _PACKAGE_DIR / "spa"


def render_dashboard_html() -> str:
    return (_PACKAGE_DIR / "dashboard.html").read_text(encoding="utf-8")


def render_spa_index() -> str:
    index = spa_root() / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"SPA index missing: {index}")
    return index.read_text(encoding="utf-8")


def resolve_spa_file(url_path: str) -> Path | None:
    """Map /app/... URL path to a file under spa_root. Reject path traversal."""
    raw = url_path.split("?", 1)[0]
    if raw in {"/app", "/app/"}:
        return None
    prefix = "/app/"
    if not raw.startswith(prefix):
        return None
    relative = raw[len(prefix) :]
    if not relative or relative.endswith("/"):
        return None
    root = spa_root().resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
```

- [ ] **Step 4: Wire `web_http.py` routes + `create_dashboard_server`**

Refactor `serve_dashboard` so handler construction is shared:

```python
def _build_dashboard_handler(config: AppConfig, store):
    class DashboardHandler(BaseHTTPRequestHandler):
        # existing methods unchanged ...
        # INSERT /app handling in do_GET (see below)
    return DashboardHandler


def create_dashboard_server(
    config: AppConfig,
    store,
    host: str = "127.0.0.1",
    port: int = 0,
) -> BoundedThreadingHTTPServer:
    handler = _build_dashboard_handler(config, store)
    return BoundedThreadingHTTPServer((host, port), handler)


def serve_dashboard(config: AppConfig, store, host: str = "127.0.0.1", port: int = 8765) -> BoundedThreadingHTTPServer:
    server = create_dashboard_server(config, store, host=host, port=port)
    server.serve_forever()
    return server
```

Inside `do_GET`, after auth succeeds and **before** or **after** the legacy `GET /` branch (order does not matter as long as both work), add:

```python
            if request.path == "/app" or request.path.startswith("/app/"):
                asset = resolve_spa_file(request.path)
                if asset is not None:
                    content_type = "application/octet-stream"
                    suffix = asset.suffix.lower()
                    if suffix == ".html":
                        content_type = "text/html; charset=utf-8"
                    elif suffix == ".js":
                        content_type = "application/javascript; charset=utf-8"
                    elif suffix == ".css":
                        content_type = "text/css; charset=utf-8"
                    elif suffix == ".svg":
                        content_type = "image/svg+xml"
                    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                        content_type = f"image/{suffix.lstrip('.')}"
                    elif suffix == ".json":
                        content_type = "application/json; charset=utf-8"
                    elif suffix == ".woff2":
                        content_type = "font/woff2"
                    _send(self, content_type, asset.read_bytes())
                    return
                try:
                    html = render_spa_index()
                except FileNotFoundError:
                    _send_error(self, 503, "SPA 尚未构建。请在 frontend/ 执行 npm run build，或使用包含前端构建阶段的 Docker 镜像。")
                    return
                _send(self, "text/html; charset=utf-8", html.encode("utf-8"))
                return
```

Import `render_spa_index`, `resolve_spa_file` from `web_assets`. Keep `GET /` → `render_dashboard_html()` unchanged. Export `create_dashboard_server` from `web_server.py` / `web.py` `__all__` if those facades list public symbols.

- [ ] **Step 5: Update `.gitignore`**

Add:

```
src/stock_ai_agent/spa/**
!src/stock_ai_agent/spa/.gitkeep
frontend/node_modules/
frontend/dist/
```

Create empty `src/stock_ai_agent/spa/.gitkeep`.

- [ ] **Step 6: Run tests**

Run: `python -m unittest tests.test_web_spa tests.test_web -v`  
Expected: PASS for new SPA tests; existing web tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add src/stock_ai_agent/web_assets.py src/stock_ai_agent/web_http.py src/stock_ai_agent/spa/.gitkeep .gitignore tests/test_web_spa.py
git commit -m "$(cat <<'EOF'
feat(web): serve Vite SPA under /app with legacy / unchanged

EOF
)"
```

---

### Task 2: Frontend scaffold (Vite + React + TS + antd)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/vite-env.d.ts`
- Create: `frontend/src/styles/global.css`
- Test: `frontend` build (`npm run build`)

**Interfaces:**
- Consumes: Task 1 `/app` serving (build output path)
- Produces: Vite app with `base: '/app/'`, `outDir` → `../src/stock_ai_agent/spa`, proxy `/api` → `http://127.0.0.1:8765`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "stockai-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@ant-design/icons": "^5.6.1",
    "@tanstack/react-query": "^5.66.0",
    "antd": "^5.29.3",
    "dayjs": "^1.11.22",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.29.0",
    "zustand": "^5.0.3"
  },
  "devDependencies": {
    "@types/react": "^18.3.18",
    "@types/react-dom": "^18.3.5",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "~5.7.3",
    "vite": "^6.1.0"
  }
}
```

- [ ] **Step 2: Create Vite + TS config**

`frontend/vite.config.ts`:

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  base: '/app/',
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/healthz': 'http://127.0.0.1:8765',
      '/readyz': 'http://127.0.0.1:8765',
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../src/stock_ai_agent/spa'),
    emptyOutDir: true,
  },
});
```

`frontend/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

`frontend/tsconfig.app.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"]
}
```

`frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 3: Create entry files**

`frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>StockAI · 策略执行台</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/main.tsx`:

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import App from './App';
import './styles/global.css';

dayjs.locale('zh-cn');

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <App />
      </ConfigProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

`frontend/src/App.tsx` (temporary shell):

```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Typography } from 'antd';

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/" element={<Typography.Title level={3}>StockAI SPA</Typography.Title>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
```

`frontend/src/styles/global.css`:

```css
:root {
  --gain: #d92d20;
  --loss: #07875b;
  --ink: #172033;
}
body {
  margin: 0;
  min-width: 320px;
  color: var(--ink);
  font-family: "Fira Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.gain { color: var(--gain); }
.loss { color: var(--loss); }
.tabular { font-variant-numeric: tabular-nums; font-family: "Fira Code", ui-monospace, monospace; }
```

`frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 4: Install and build**

Run:

```bash
cd frontend
npm install
npm run build
```

Expected: `src/stock_ai_agent/spa/index.html` exists and references `/app/assets/...`.

- [ ] **Step 5: Smoke Python serve of built SPA**

With backend running locally (existing CLI serve), open `http://127.0.0.1:8765/app/` — should show “StockAI SPA”. `http://127.0.0.1:8765/` still legacy.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig*.json frontend/index.html frontend/src
git commit -m "$(cat <<'EOF'
chore(frontend): scaffold Vite React TypeScript Ant Design app

EOF
)"
```

Do **not** add `src/stock_ai_agent/spa/*` build artifacts.

---

### Task 3: API client, types, format utils

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/dashboard.ts`
- Create: `frontend/src/api/watchlist.ts`
- Create: `frontend/src/api/risk.ts`
- Create: `frontend/src/api/backtests.ts`
- Create: `frontend/src/api/strategies.ts`
- Create: `frontend/src/api/reports.ts`
- Create: `frontend/src/api/instruments.ts`
- Create: `frontend/src/types/dashboard.ts`
- Create: `frontend/src/utils/format.ts`
- Create: `frontend/src/stores/uiStore.ts`

**Interfaces:**
- Consumes: existing REST paths from `web_http.py`
- Produces: typed `apiGet` / `apiSend`; section loaders; `fmtMoney`, `fmtPct`, `toneClass`; `useUiStore` for announcements / notices

- [ ] **Step 1: Define shared types**

Create `frontend/src/types/dashboard.ts` with interfaces matching JSON keys used by the legacy UI (string decimals as returned by `_to_jsonable`):

```ts
export interface PortfolioPosition {
  symbol: string;
  name?: string;
  quantity?: string | number;
  market_value?: string | number;
  unrealized_pnl?: string | number;
  weight?: string | number;
  trading_enabled?: boolean;
}

export interface Portfolio {
  cash?: string | number;
  total_asset?: string | number;
  total_market_value?: string | number;
  positions?: PortfolioPosition[];
}

export interface RiskConfig {
  max_symbol_weight?: string | number;
  max_etf_weight?: string | number;
  max_stock_weight?: string | number;
  max_etf_total_weight?: string | number;
  max_stock_total_weight?: string | number;
  max_total_exposure?: string | number;
  min_cash_ratio?: string | number;
  max_drawdown?: string | number;
  single_position_loss?: string | number;
  trailing_drawdown?: string | number;
  portfolio_daily_loss?: string | number;
  high_atr_ratio?: string | number;
  max_operations_per_symbol?: string | number;
  pending_confirmation?: boolean;
}

export interface OverviewPayload {
  portfolio?: Portfolio;
  risk_config?: RiskConfig;
  daily_return?: string | number;
  pending_backtest_count?: number;
  decisions?: unknown[];
  recent_fills?: unknown[];
  watchlist?: unknown[];
  leaderboard?: unknown[];
  updated_at?: string;
  [key: string]: unknown;
}

export interface PerformanceQuery {
  performance_start: string;
  performance_end: string;
}
```

Expand remaining fields (`BacktestRun`, `StrategyCenter`, `DailyReport`, `InstrumentDetail`) by reading one live `/api/...` payload or the builders in `web_dashboard.py` / `instrument_detail.py` while implementing—keep every API module fully typed (no `any`).

- [ ] **Step 2: Implement HTTP client**

`frontend/src/api/client.ts`:

```ts
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', signal });
  if (!response.ok) {
    let message = `服务返回 ${response.status}`;
    try {
      const body = (await response.json()) as { message?: string };
      if (body.message) message = body.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export async function apiSend<T>(
  path: string,
  method: 'POST' | 'DELETE',
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    signal,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `服务返回 ${response.status}`;
    try {
      const payload = (await response.json()) as { message?: string };
      if (payload.message) message = payload.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
```

- [ ] **Step 3: Section API modules**

`frontend/src/api/dashboard.ts`:

```ts
import { apiGet } from './client';
import type { OverviewPayload, PerformanceQuery } from '@/types/dashboard';

export function fetchOverview(signal?: AbortSignal) {
  return apiGet<OverviewPayload>('/api/dashboard/overview', signal);
}

export function fetchPerformance(query: PerformanceQuery, signal?: AbortSignal) {
  const qs = new URLSearchParams(query).toString();
  return apiGet<OverviewPayload>(`/api/dashboard/performance?${qs}`, signal);
}

export function fetchCalendar(signal?: AbortSignal) {
  return apiGet<OverviewPayload>('/api/dashboard/calendar', signal);
}
```

`frontend/src/api/risk.ts`:

```ts
import { apiSend } from './client';
import type { RiskConfig } from '@/types/dashboard';

export function saveRiskConfig(payload: Record<string, string | number>) {
  return apiSend<{ risk_config: RiskConfig }>('/api/risk-config', 'POST', payload);
}

export function confirmRiskConfig() {
  return apiSend<{ risk_config: RiskConfig }>('/api/risk-config/confirm', 'POST');
}
```

`frontend/src/api/watchlist.ts`:

```ts
import { apiGet, apiSend } from './client';
import type { OverviewPayload } from '@/types/dashboard';

export function searchInstruments(q: string) {
  return apiGet<{ items: Array<{ symbol: string; name: string; asset_type: string }>; catalog?: { count?: number } }>(
    `/api/watchlist/search?q=${encodeURIComponent(q)}`,
  );
}

export function addWatchlistItem(item: { symbol: string; name: string; asset_type: string }) {
  return apiSend<{ dashboard: OverviewPayload }>('/api/watchlist', 'POST', item);
}

export function removeWatchlistItem(symbol: string) {
  return apiSend<{ dashboard: OverviewPayload }>(`/api/watchlist/${encodeURIComponent(symbol)}`, 'DELETE');
}

export function setWatchlistTrading(symbol: string, enabled: boolean) {
  return apiSend<{ dashboard: OverviewPayload }>(
    `/api/watchlist/${encodeURIComponent(symbol)}/trading`,
    'POST',
    { enabled },
  );
}
```

Add `backtests.ts`, `strategies.ts`, `reports.ts`, `instruments.ts` mirroring paths in `web_http.py` (`/api/dashboard/backtests`, `/api/backtests/run`, `/api/backtests/confirm`, `/api/dashboard/strategies`, `/api/strategies/profiles`, confirm/draft, `/api/dashboard/reports`, `/api/instruments/{symbol}/detail`).

- [ ] **Step 4: Format helpers + UI store**

`frontend/src/utils/format.ts`:

```ts
export function fmtMoney(value: unknown): string {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function fmtPct(value: unknown): string {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

export function toneClass(value: unknown): 'gain' | 'loss' | '' {
  const n = Number(value);
  if (n > 0) return 'gain';
  if (n < 0) return 'loss';
  return '';
}
```

`frontend/src/stores/uiStore.ts`:

```ts
import { create } from 'zustand';

interface UiState {
  notice: string;
  liveMessage: string;
  setNotice: (message: string) => void;
  announce: (message: string) => void;
}

export const useUiStore = create<UiState>((set) => ({
  notice: '',
  liveMessage: '',
  setNotice: (notice) => set({ notice }),
  announce: (liveMessage) => set({ liveMessage }),
}));
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b --pretty false`  
Expected: exit 0

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/types frontend/src/utils frontend/src/stores
git commit -m "$(cat <<'EOF'
feat(frontend): add typed API client and shared format helpers

EOF
)"
```

---

### Task 4: AppShell + routed lazy pages

**Files:**
- Create: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/App.tsx`
- Create: stub pages under `frontend/src/pages/*.tsx`

**Interfaces:**
- Consumes: React Router `basename="/app"`; antd `Layout`, `Menu`/`Tabs`, `Button`, `Alert`
- Produces: routes `/`, `/backtests`, `/strategies`, `/reports`, `/instruments/:symbol`

- [ ] **Step 1: Implement AppShell**

`frontend/src/layouts/AppShell.tsx`:

```tsx
import { Layout, Menu, Button, Alert, Typography, Space } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ReloadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { useUiStore } from '@/stores/uiStore';

const { Header, Content } = Layout;

const items = [
  { key: '/', label: '交易看板' },
  { key: '/backtests', label: '回测记录' },
  { key: '/strategies', label: '策略中心' },
  { key: '/reports', label: '日报归档' },
];

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const notice = useUiStore((s) => s.notice);
  const liveMessage = useUiStore((s) => s.liveMessage);
  const setNotice = useUiStore((s) => s.setNotice);
  const selected = items.find((item) =>
    item.key === '/' ? location.pathname === '/' : location.pathname.startsWith(item.key),
  )?.key ?? '/';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', gap: 16, background: '#fff', paddingInline: 24 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>StockAI</Typography.Title>
        <Menu
          mode="horizontal"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              setNotice('');
              void queryClient.invalidateQueries();
            }}
          >
            刷新数据
          </Button>
        </Space>
      </Header>
      <Content style={{ padding: 24 }}>
        {notice ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={notice}
            action={<Button size="small" onClick={() => void queryClient.invalidateQueries()}>重试</Button>}
          />
        ) : null}
        <Outlet />
        <div className="sr-only" aria-live="polite">{liveMessage}</div>
      </Content>
    </Layout>
  );
}
```

Add `.sr-only` to `global.css` (visually hidden but available to AT).

- [ ] **Step 2: Wire routes with lazy page stubs**

Update `App.tsx` to nest routes under `AppShell`. Each page stub exports a default component showing the page title (antd `Typography`). Instrument route: `/instruments/:symbol`.

- [ ] **Step 3: Manual check**

`npm run dev` → navigate menu items; URLs under `/app/...`; refresh keeps route (history mode).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/layouts frontend/src/pages frontend/src/App.tsx frontend/src/styles/global.css
git commit -m "$(cat <<'EOF'
feat(frontend): add AppShell navigation and route stubs

EOF
)"
```

---

### Task 5: Dashboard overview panels (account, positions, decisions, activity, leaderboard)

**Files:**
- Create: `frontend/src/components/account/AccountStrip.tsx`
- Create: `frontend/src/components/positions/PositionsTable.tsx`
- Create: `frontend/src/components/decisions/DecisionTimeline.tsx`
- Create: `frontend/src/components/activity/RecentActivity.tsx`
- Create: `frontend/src/components/leaderboard/Leaderboard.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`

**Interfaces:**
- Consumes: `fetchOverview` via `useQuery({ queryKey: ['overview'], queryFn })`
- Produces: Dashboard page rendering overview-driven panels; errors call `setNotice`

- [ ] **Step 1: Port field mapping from legacy `renderAccount` / `renderPositions` / etc.**

Open `src/stock_ai_agent/dashboard.html` functions `renderAccount`, `renderPositions`, `renderDecisionTimeline`, `renderActivity`, `renderLeaderboard` and reimplement with antd `Statistic`, `Table`, `List`, `Timeline`. Preserve A-share gain/loss class names via `toneClass`.

- [ ] **Step 2: Compose `DashboardPage`**

```tsx
import { useQuery } from '@tanstack/react-query';
import { Spin } from 'antd';
import { fetchOverview } from '@/api/dashboard';
import { useUiStore } from '@/stores/uiStore';
import { AccountStrip } from '@/components/account/AccountStrip';
// ...other imports

export default function DashboardPage() {
  const setNotice = useUiStore((s) => s.setNotice);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['overview'],
    queryFn: ({ signal }) => fetchOverview(signal),
  });

  if (isError) {
    setNotice('无法读取交易数据，请检查本地服务后重试。');
  }

  if (isLoading || !data) return <Spin />;

  return (
    <>
      <AccountStrip data={data} />
      {/* grid: decisions + positions; leaderboard + activity */}
    </>
  );
}
```

Use React Query only for fetch; do not call `setNotice` during render (use `useEffect` when `isError` flips).

- [ ] **Step 3: Manual verify against legacy `/`**

Side-by-side: same portfolio numbers, position rows, decision count.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/account frontend/src/components/positions frontend/src/components/decisions frontend/src/components/activity frontend/src/components/leaderboard frontend/src/pages/DashboardPage.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): port dashboard overview panels to React

EOF
)"
```

---

### Task 6: Risk config + watchlist drawer/mutations

**Files:**
- Create: `frontend/src/components/risk/RiskConfigPanel.tsx`
- Create: `frontend/src/components/watchlist/AddInstrumentDrawer.tsx`
- Modify: `PositionsTable.tsx` (trading switch, remove, open drawer, link to instrument)
- Modify: `DashboardPage.tsx`

**Interfaces:**
- Consumes: `saveRiskConfig`, `confirmRiskConfig`, watchlist APIs
- Produces: mutations that `queryClient.setQueryData(['overview'], ...)` or `invalidateQueries(['overview'])`

- [ ] **Step 1: Risk panel with antd `Form` + `Collapse`**

Mirror legacy fields in `renderRiskConfig` / `saveRiskConfig` / `confirmRiskConfig`. On success: update overview cache + `announce(...)`.

- [ ] **Step 2: AddInstrumentDrawer**

antd `Drawer` + debounced `searchInstruments` (`AutoComplete` or result `List`). Add calls `addWatchlistItem` then invalidate overview.

- [ ] **Step 3: Position row actions**

Port `toggleWatchlistTrading`, `removeWatchlistItem` (antd `Popconfirm`), navigate to `/instruments/:symbol`.

- [ ] **Step 4: Manual verify write paths**

Add/remove symbol, toggle trading, save+confirm risk; confirm legacy `/` still works independently.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk frontend/src/components/watchlist frontend/src/components/positions frontend/src/pages/DashboardPage.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): port risk config and watchlist mutations

EOF
)"
```

---

### Task 7: Performance chart + profit calendar (Canvas port)

**Files:**
- Create: `frontend/src/components/performance/lineChart.ts`
- Create: `frontend/src/components/performance/PerformancePanel.tsx`
- Create: `frontend/src/components/calendar/ProfitCalendar.tsx`
- Modify: `DashboardPage.tsx`

**Interfaces:**
- Consumes: `fetchPerformance`, `fetchCalendar`; antd `Segmented`, `DatePicker.RangePicker`
- Produces: canvas drawing parity with legacy `renderPerformance` / calendar renderers

- [ ] **Step 1: Extract Canvas helpers**

Copy drawing logic from `dashboard.html` (`renderPerformance`, tooltip, legend toggles, keyboard handlers) into `lineChart.ts` as pure functions operating on `HTMLCanvasElement` + series data. Keep colors/dash patterns from `seriesStyle`.

- [ ] **Step 2: PerformancePanel**

`useQuery` key `['performance', start, end]`. Segmented modes: yearly/monthly/custom + pnl/return/asset. RangePicker sets custom dates. Abort/ignore stale responses via query keys (React Query handles this).

- [ ] **Step 3: ProfitCalendar**

Port monthly/yearly grids + amount/rate toggle from `renderCalendar` / `renderMonthCalendar` / `renderYearCalendar`. Load via `['calendar']` query (lazy with dashboard mount `Promise.all` equivalent: both queries enabled on DashboardPage).

- [ ] **Step 4: Manual compare**

Same date range on `/` vs `/app` — series values and calendar totals match.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/performance frontend/src/components/calendar frontend/src/pages/DashboardPage.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): port performance canvas and profit calendar

EOF
)"
```

---

### Task 8: Backtests page

**Files:**
- Create: `frontend/src/components/backtest/BacktestPanel.tsx`
- Modify: `frontend/src/pages/BacktestPage.tsx`
- Modify: `frontend/src/api/backtests.ts` (if not complete)

**Interfaces:**
- Consumes: `GET /api/dashboard/backtests`, `POST /api/backtests/run`, `POST /api/backtests/confirm`
- Produces: lazy load on route enter (`useQuery` enabled when page mounted)

- [ ] **Step 1: Table with row selection**

antd `Table` rowSelection; disable rows already `已确认`/`已应用`/`已拒绝`. Columns/metrics from legacy `renderBacktests` / `renderBacktestMetrics`.

- [ ] **Step 2: Actions**

“立即回测” → `runBacktest` mutation; “确认所选” → `confirmBacktests({ ids })`; invalidate `['backtests']` and `['overview']` (pending count).

- [ ] **Step 3: Manual verify**

Run/confirm paths against a store that has pending runs.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/backtest frontend/src/pages/BacktestPage.tsx frontend/src/api/backtests.ts
git commit -m "$(cat <<'EOF'
feat(frontend): port backtest list run and confirm flows

EOF
)"
```

---

### Task 9: Strategy center page

**Files:**
- Create: `frontend/src/components/strategy/StrategyWorkspace.tsx`
- Modify: `frontend/src/pages/StrategyPage.tsx`

**Interfaces:**
- Consumes: strategies GET + save/confirm/discard endpoints
- Produces: sidebar profile list + editor form (enabled weights, technical/quant/external/aggregator JSON fields)

- [ ] **Step 1: Port `renderStrategies` / `renderStrategyEditor` / save/confirm/discard**

Use antd `List` + `Form` + `Input.TextArea` for JSON blobs. Validate JSON parse before POST; surface API errors via `announce`.

- [ ] **Step 2: Lazy query on route**

`queryKey: ['strategies']`.

- [ ] **Step 3: Manual verify**

Edit draft → save pending → confirm → discard path.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/strategy frontend/src/pages/StrategyPage.tsx frontend/src/api/strategies.ts
git commit -m "$(cat <<'EOF'
feat(frontend): port strategy center workspace

EOF
)"
```

---

### Task 10: Daily reports page

**Files:**
- Create: `frontend/src/components/reports/ReportArchive.tsx`
- Modify: `frontend/src/pages/DailyReportPage.tsx`

**Interfaces:**
- Consumes: `/api/dashboard/reports?limit&offset`, `/api/dashboard/reports/{date}`
- Produces: paginated list (page size 30 like `DAILY_REPORT_PAGE_SIZE`) + detail panel

- [ ] **Step 1: Implement infinite/load-more list**

Match legacy `loadDailyReports` / `loadMoreDailyReports` / `loadDailyReport` behavior with React Query (`useInfiniteQuery` or manual offset state).

- [ ] **Step 2: Detail renderer**

Port `renderDailyReportDetail` sections (account, positions, fills, decisions).

- [ ] **Step 3: Manual verify**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/reports frontend/src/pages/DailyReportPage.tsx frontend/src/api/reports.ts
git commit -m "$(cat <<'EOF'
feat(frontend): port daily report archive and detail

EOF
)"
```

---

### Task 11: Instrument detail page + chart port

**Files:**
- Create: `frontend/src/components/instrument/instrumentChart.ts`
- Create: `frontend/src/components/instrument/InstrumentDetail.tsx`
- Modify: `frontend/src/pages/InstrumentDetailPage.tsx`

**Interfaces:**
- Consumes: `GET /api/instruments/{symbol}/detail`
- Produces: period tabs + canvas + marker list; back navigation to dashboard

- [ ] **Step 1: Port `openInstrumentDetail` / `renderInstrumentDetail` / `renderInstrumentChart`**

Keep keyboard/tooltip behavior where practical.

- [ ] **Step 2: Route param wiring**

`useParams().symbol`; queryKey `['instrument', symbol]`.

- [ ] **Step 3: Manual verify from positions click**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/instrument frontend/src/pages/InstrumentDetailPage.tsx frontend/src/api/instruments.ts
git commit -m "$(cat <<'EOF'
feat(frontend): port instrument detail canvas view

EOF
)"
```

---

### Task 12: Docker multi-stage + package-data

**Files:**
- Modify: `Dockerfile`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/publish-image.yml` (only if CI must build frontend before unittest that requires spa—prefer tests that monkeypatch fixtures so workflow test job stays Python-only)
- Test: `docker build` locally (or at least `npm run build` + `python -m unittest`)

**Interfaces:**
- Consumes: `frontend/` sources + Task 1 spa path
- Produces: image containing built `/app` assets inside the installed package

- [ ] **Step 1: Update `pyproject.toml` package-data**

```toml
[tool.setuptools.package-data]
stock_ai_agent = ["dashboard.html", "spa/**/*"]
```

- [ ] **Step 2: Rewrite Dockerfile stages**

```dockerfile
FROM node:22-bookworm AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS builder
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ARG PIP_INDEX_URL
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=frontend /frontend/../src/stock_ai_agent/spa ./src/stock_ai_agent/spa
# NOTE: vite outDir writes into ../src/stock_ai_agent/spa relative to frontend WORKDIR.
# If COPY path is awkward, set vite outDir to /frontend/dist and:
#   COPY --from=frontend /frontend/dist ./src/stock_ai_agent/spa
RUN if [ -n "$PIP_INDEX_URL" ]; then \
      python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" .; \
    else \
      python -m pip install --no-cache-dir .; \
    fi

FROM python:3.12-slim
# ... keep existing runtime setup ...
COPY --from=builder /opt/venv /opt/venv
# ... rest unchanged ...
```

**Prefer adjusting Task 2 `outDir` to `dist` inside `frontend/` and copying `dist` → `src/stock_ai_agent/spa` in Docker** if path clarity is better—then local `npm run build` should still emit into package `spa/` via vite config for non-Docker dev, OR document `npm run build` as writing to package spa (current Task 2). Pick one path and keep Dockerfile COPY consistent; do not leave broken COPY.

Recommended final vite build target for both local and Docker:

```ts
build: {
  outDir: path.resolve(__dirname, '../src/stock_ai_agent/spa'),
  emptyOutDir: true,
}
```

Docker frontend stage:

```dockerfile
FROM node:22-bookworm AS frontend
WORKDIR /src
COPY frontend ./frontend
COPY src/stock_ai_agent/spa/.gitkeep ./src/stock_ai_agent/spa/.gitkeep
WORKDIR /src/frontend
RUN npm ci && npm run build
```

Python builder:

```dockerfile
COPY --from=frontend /src/src/stock_ai_agent/spa ./src/stock_ai_agent/spa
```

- [ ] **Step 3: Build image smoke**

Run: `docker build -t stockai:local .`  
Run container web serve; `curl -f http://127.0.0.1:8765/app/` returns SPA; `/` legacy.

- [ ] **Step 4: Run unit tests**

Run: `python -m unittest discover -s tests -p 'test_*.py'`  
Expected: PASS (SPA tests use fixtures; legacy HTML test unchanged).

- [ ] **Step 5: Commit**

```bash
git add Dockerfile pyproject.toml frontend/vite.config.ts
git commit -m "$(cat <<'EOF'
build: compile React SPA in Docker Node 22 stage

EOF
)"
```

---

### Task 13: Parity checklist doc + README dual-entry note

**Files:**
- Create: `docs/design/2026-08-25-frontend-parity-checklist.md` (copy checklist from spec; add “how to run Vite + Python”)
- Modify: `README.md` (short “Web UI” note: `/` legacy, `/app` SPA, `cd frontend && npm run dev`)

**Interfaces:**
- Consumes: spec checklist
- Produces: operator-facing dual-entry instructions

- [ ] **Step 1: Write checklist file** with every item from the spec as `- [ ]` and a “how to compare” section.

- [ ] **Step 2: README blurb** (≤15 lines) pointing to `/app` and frontend dev commands.

- [ ] **Step 3: Commit**

```bash
git add docs/design/2026-08-25-frontend-parity-checklist.md README.md
git commit -m "$(cat <<'EOF'
docs: add SPA dual-entry notes and manual parity checklist

EOF
)"
```

---

### Task 14: Cutover (`/` → SPA) — ONLY after manual checklist signed off

**Files:**
- Modify: `src/stock_ai_agent/web_http.py` (`GET /` serves SPA index; optional redirect `/app` → `/` or keep `/app` working with `base` change)
- Modify: `frontend/vite.config.ts` (`base: '/'` if SPA becomes root)
- Modify: `frontend/src/App.tsx` (`basename` `''` or `/`)
- Modify: `tests/test_web.py` (replace/remove `test_dashboard_html_references_local_api`)
- Modify: `tests/test_web_spa.py` (root serves SPA)
- Modify: `pyproject.toml` (drop `dashboard.html` from package-data when deleted)
- Delete or archive: `src/stock_ai_agent/dashboard.html`
- Modify: README + parity checklist (mark cut over)

**Interfaces:**
- Consumes: completed manual checklist
- Produces: single SPA entry at `/`

- [ ] **Step 1: Confirm checklist**

Do not start this task until `docs/design/2026-08-25-frontend-parity-checklist.md` is fully checked by a human.

- [ ] **Step 2: Switch base path to `/`**

Set Vite `base: '/'`, Router `basename` to `""`, rebuild, update Python: `GET /` → `render_spa_index()`; keep `/app` as HTTP 302 to `/` **or** continue serving the same SPA under both (document choice in commit message). Preferred: redirect `/app` → `/` and `/app/*` → `/*`.

- [ ] **Step 3: Replace legacy HTML tests**

Remove assertions that scan `dashboard.html` for API strings. Keep API route tests. Assert `GET /` returns SPA shell (`<div id="root">`).

- [ ] **Step 4: Remove `dashboard.html` and package-data entry**

- [ ] **Step 5: Full unittest + Docker build + manual smoke**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(web): cut over default UI from legacy HTML to React SPA

EOF
)"
```

---

## Self-Review

**1. Spec coverage**

| Spec item | Task |
|-----------|------|
| Dual entry `/` + `/app` | 1, 13 |
| Unchanged `/api/*` | 3–11 (clients only) |
| Vite + React + antd + TS | 2 |
| TanStack Query + zustand | 3, 4, 5+ |
| Browser history + fallback | 1, 4 |
| Canvas port first | 7, 11 |
| npm + `frontend/` | 2 |
| Node 22 Docker multi-stage | 12 |
| Manual parity gate | 13, 14 |
| Legacy tests until cutover | 1, 14 |
| Full feature parity | 5–11 |
| Basic Auth unchanged | 3 (`credentials`) |
| No dist in git | 1 gitignore, 2 commit note |

**2. Placeholder scan:** Removed vague “copy from test_web server helper” guidance (that helper does not exist). Task 1 now specifies `create_dashboard_server` + threaded HTTP smoke tests. Task 3 still requires expanding TS interfaces from live `/api` payloads or `web_dashboard.py` while implementing—those field lists are discoverable in-repo, not TBD logic. Dockerfile COPY paths include a recommended coherent layout.

**3. Type consistency:** `OverviewPayload`, `apiGet`/`apiSend`, `spa_root`/`render_spa_index`/`resolve_spa_file`, query keys `overview` | `performance` | `calendar` | `backtests` | `strategies` | `instrument` used consistently across tasks.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-08-25-react-antd-spa.md`. Spec at `docs/specs/2026-08-25-react-antd-spa-design.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

**Which approach?**
