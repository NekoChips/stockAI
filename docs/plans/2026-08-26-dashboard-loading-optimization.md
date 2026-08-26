# 交易看板第二阶段加载优化

**状态：** implemented  
**负责人：** frontend  
**创建日期：** 2026-08-26  
**更新日期：** 2026-08-26  
**关联：** [StockAI 文档规范](../README.md)

## 目标

降低交易看板打开后的首屏 JavaScript 下载和执行压力，同时保留账户摘要、日历和盈亏分析的连续视觉结构。排行榜、决策轨道、实时持仓、图表实现和最近成交记录不应因为等待网络或数据而造成页面跳动。

## 实施方案

- `DashboardPage` 保留轻量布局、账户摘要和首屏骨架，四个高成本区块通过动态 `import` 单独产出 chunk。
- `DeferredDashboardSection` 使用 `IntersectionObserver` 在区块进入视口前触发加载；浏览器不支持该 API 时回退为立即加载。
- 延迟区块使用固定的 `minHeight` 和骨架占位，避免异步内容替换导致布局位移。
- 盈亏分析使用较大的预加载边界，保证用户打开看板后快速进入图表；持仓、决策轨道、排行榜和最近成交按滚动位置渐进加载。
- 所有区块仍复用同一个 `overview` 查询结果，动态加载只拆分代码，不增加重复的看板接口请求。

## 构建体积预算

预算配置位于 `frontend/bundle-budget.json`，由 `scripts/check-frontend-bundle.mjs` 在 `frontend` 构建时执行。超出预算会使本地构建和发布流水线失败。

| 指标 | 上限 | 说明 |
| --- | ---: | --- |
| 入口 JS | 430 KB | Vite HTML 入口脚本 |
| 静态初始 JS | 680 KB | React、Query、dayjs 等静态入口依赖 |
| Dashboard 路由 JS | 940 KB | 打开交易看板实际需要的路由依赖 |
| 单个延迟 chunk | 360 KB | 持仓、图表、决策轨道和排行榜等区块 |
| 全部 JS | 2200 KB | 所有页面和功能 chunk 总和 |

GitHub Actions 增加独立前端构建门禁，Docker 前端构建阶段也执行同一脚本。预算只约束未压缩构建产物，便于稳定比较不同构建之间的体积变化。

## 验收结果

当前构建结果：入口 397.2 KB，静态初始 615.6 KB，Dashboard 路由 846.0 KB，最大延迟 chunk 180.7 KB，全部 JS 1320.5 KB，均在预算内。

验证命令：

```bash
pnpm --dir frontend run build
PYTHONPYCACHEPREFIX=/tmp/stockai-pycache PYTHONPATH=src \
  python3 -m unittest discover -s tests -p 'test_*.py' -q
```
