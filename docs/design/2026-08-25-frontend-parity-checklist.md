# SPA Feature Parity Checklist

Manual verification gate before cutover from legacy dashboard (`/`) to the React SPA (`/app`). See [2026-08-25-react-antd-spa-design.md](../specs/2026-08-25-react-antd-spa-design.md).

## How to run Vite + Python

**Backend (required for both modes):**

```bash
python -m stock_ai_agent.app web --config config/default.yaml --host 127.0.0.1 --port 8765
```

**Option A â€” Vite dev server (HMR):**

```bash
cd frontend && npm install && npm run dev
```

Open `http://127.0.0.1:5173/app/`. Vite proxies `/api`, `/healthz`, and `/readyz` to Python on port 8765.

**Option B â€” Built SPA served by Python:**

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

- [x] äº¤æ˜“çœ‹æ¿: account strip, risk config save/confirm, performance chart + range, decision timeline, positions, profit calendar, leaderboard, recent fills
- [x] è§‚å¯Ÿæ± : search/add drawer, remove, trading toggle
- [x] å›æµ‹è®°å½•: list, run, multi-select confirm
- [x] ç­–ç•¥ä¸­å¿ƒ: profile list/edit/save/confirm/discard draft
- [x] æ—¥æŠ¥å½’æ¡£: paginated list + detail
- [x] æ ‡çš„è¯¦æƒ…: periods, canvas chart, markers
- [x] Header refresh + error notice + Basic Auth still works- [ ] Ö÷Ìâ£ºÁÁ/°µÇĞ»»¡¢Ë¢ĞÂºó±£Áô
- [ ] °µÉ«£º¿´°å / ±êµÄÏêÇé / ²ßÂÔÖĞĞÄ / ÈÕ±¨¹éµµÎŞÎ´ÊÊÅä°×µ×
