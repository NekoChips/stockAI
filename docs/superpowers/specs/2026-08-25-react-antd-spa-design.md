# React + Ant Design SPA Dual-Entry Design

**Date:** 2026-08-25  
**Status:** Consensus locked (grill session)  
**Product:** StockAI 策略执行台

## Problem

Frontend is a single `src/stock_ai_agent/dashboard.html` (~1300+ lines of HTML/CSS/JS). Backend JSON APIs are already split (`web_http` → `web_dashboard` / `web_actions`). Maintainability, component boundaries, and Ant Design adoption require a real React SPA—not CDN UMD patches.

## Goals

1. Split the monolith into a maintainable React + Ant Design codebase.
2. Keep all existing REST API contracts unchanged.
3. Ship dual entry until full feature parity is manually verified, then cut `/` over.

## Non-Goals (this effort)

- Token/session auth redesign (keep browser Basic Auth popup).
- Visual redesign / dark theme (Ant Design defaults OK; only keep A-share gain/loss colors).
- Replacing Canvas charts with ECharts in the first pass.
- Committing production `dist/` to git.
- Automated E2E as a cutover gate (manual checklist only).

## Architecture

```
Browser
  GET /          → legacy dashboard.html (unchanged until cutover)
  GET /app/*     → Vite SPA (base `/app/`)
  /api/*         → existing Python JSON handlers
  /healthz|/readyz → unchanged

Dev:  Vite :5173 proxies /api → Python :8765
Prod: Multi-stage Docker (Node 22 build → copy into Python package → runtime image)
```

## Decisions (locked)

| ID | Decision |
|----|----------|
| Q1–Q2 | Full Vite + React + Ant Design SPA |
| Q3/Q7 | Docker multi-stage Node build; dist not committed |
| Q4 | Ant Design default look acceptable |
| Q5/Q11 | Full manual parity before switching `/` |
| Q6/Q12 | Dual entry: legacy `/`, SPA `/app` |
| Q8 | React Router browser history + Python SPA fallback |
| Q9 | TanStack Query + light zustand for UI state |
| Q10 | Port existing Canvas chart code first |
| Q13 | TypeScript everywhere |
| Q14 | Basic Auth browser popup; `fetch` with credentials |
| Q15 | Keep legacy HTML string tests until cutover; add SPA serving tests in parallel |
| Q16 | npm + `package-lock.json` |
| Q17 | Repo root `frontend/` |
| Q18 | antd + small global CSS (no Tailwind) |
| Q19 | Full feature parity required (all tabs, drawers, writes) |
| Q20 | Node 22 LTS in Docker frontend builder |

## Feature Parity Checklist (cutover gate)

Manual verification on `/app` must cover:

- [ ] 交易看板: account strip, risk config save/confirm, performance chart + range, decision timeline, positions, profit calendar, leaderboard, recent fills
- [ ] 观察池: search/add drawer, remove, trading toggle
- [ ] 回测记录: list, run, multi-select confirm
- [ ] 策略中心: profile list/edit/save/confirm/discard draft
- [ ] 日报归档: paginated list + detail
- [ ] 标的详情: periods, canvas chart, markers
- [ ] Header refresh + error notice + Basic Auth still works

## Packaging

- Source: `frontend/`
- Vite `base: '/app/'`, `outDir` → `src/stock_ai_agent/spa/`
- `pyproject.toml` package-data includes `spa/**/*` and `dashboard.html`
- `spa/` build outputs gitignored (keep `.gitkeep` only)
- Tests monkeypatch SPA root with a tiny fixture HTML when full build is absent

## Cutover (after checklist)

1. Serve SPA at `/` (and keep `/app` redirect or alias).
2. Move or delete legacy `dashboard.html` serving.
3. Rewrite/remove `test_dashboard_html_references_local_api` HTML string assertions.
4. Remove dual-entry docs from README.
