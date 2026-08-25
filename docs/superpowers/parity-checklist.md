# SPA Feature Parity Checklist

Manual verification gate before cutover from legacy dashboard (`/`) to the React SPA (`/app`). See [2026-08-25-react-antd-spa-design.md](./specs/2026-08-25-react-antd-spa-design.md).

## How to run Vite + Python

**Backend (required for both modes):**

```bash
python -m stock_ai_agent.app web --config config/default.yaml --host 127.0.0.1 --port 8765
```

**Option A — Vite dev server (HMR):**

```bash
cd frontend && npm install && npm run dev
```

Open `http://127.0.0.1:5173/app/`. Vite proxies `/api`, `/healthz`, and `/readyz` to Python on port 8765.

**Option B — Built SPA served by Python:**

```bash
cd frontend && npm install && npm run build
```

Then use the backend URL above. Open `http://127.0.0.1:8765/app/` (SPA) and `http://127.0.0.1:8765/` (legacy).

Basic Auth applies to both entries when configured.

## How to compare

1. Open legacy UI at `/` and SPA at `/app` (or `/app/` via Vite dev).
2. Walk each checklist area on both; SPA behavior and data must match legacy.
3. Confirm writes (save, confirm, run, toggle) persist and appear on refresh.
4. Check header refresh, error notices, and Basic Auth on the SPA.

## Checklist (cutover gate)

Manual verification on `/app` must cover:

- [ ] 交易看板: account strip, risk config save/confirm, performance chart + range, decision timeline, positions, profit calendar, leaderboard, recent fills
- [ ] 观察池: search/add drawer, remove, trading toggle
- [ ] 回测记录: list, run, multi-select confirm
- [ ] 策略中心: profile list/edit/save/confirm/discard draft
- [ ] 日报归档: paginated list + detail
- [ ] 标的详情: periods, canvas chart, markers
- [ ] Header refresh + error notice + Basic Auth still works
