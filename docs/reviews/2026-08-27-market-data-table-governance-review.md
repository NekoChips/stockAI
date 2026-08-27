# 行情数据表治理实施复核

**状态：** implemented  
**负责人：** platform-and-operations  
**创建日期：** 2026-08-27  
**更新日期：** 2026-08-27  
**关联：** [行情数据表治理与 `bars` 淘汰实施方案](../plans/2026-08-27-market-data-table-governance.md)、[数据库数据字典](../architecture/2026-08-27-database-data-dictionary.md)、[行情表拆分迁移操作手册](../operations/2026-08-27-market-data-bars-migration.md)

## 1. 复核范围

本次复核覆盖行情表职责拆分、存储适配器接口切换、应用读写路径、历史同步、指数数据、分钟线详情页路径、测试夹具和生产迁移文档。

## 2. 实施结论

代码侧已完成以下切换：

- 观察池日 K 统一读写 `bar_price_tracks`，保留 raw、qfq 和原始复权因子；
- 指数 K 统一读写 `index_price_tracks`；
- 分钟线统一读写 `intraday_bars`；
- 实时行情历史归档不再写入 `bars`，而是转换后写入 `intraday_bars`；
- MySQL 初始化不再创建 `bars`，生产业务代码不再从 `bars` 回退读取；
- `MarketDataStore` 已移除通用 `save_bars`、`load_bars` 和 `load_bars_batch` 契约，改为按领域区分的存储接口；
- 观察池历史同步和指数历史同步已使用各自的目标表；
- 代码、页面接口、回测和测试夹具均已完成调用路径切换。

生产库侧暂未自动删除 `bars`，这是有意保留的安全边界。已有生产库必须先执行备份、创建目标表、重新同步观察池和指数历史、迁移旧分钟线，并完成验收和至少一个完整交易日观察，之后由运维人员手工执行 `DROP TABLE bars`。

## 3. 验证结果

在项目根目录执行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

结果：`Ran 194 tests ... OK`。

另外完成以下检查：

- `PYTHONPYCACHEPREFIX=/tmp/stockai-pycache PYTHONPATH=src python3 -m compileall -q src`：通过；
- `save_bars`、`load_bars`、`load_bars_batch`、`save_price_tracks`：在 `src` 和 `tests` 中无旧接口引用；
- `git diff --check`：通过。

## 4. 生产验收前置条件

以下事项不由应用启动自动完成，必须按运维手册执行并留存结果：

1. 使用 `mysqldump` 或数据库快照完成迁移前备份，并验证备份可恢复；
2. 执行 `migrations/009_split_market_bar_tables.sql`；
3. 通过 AlphaFeed 重新补齐观察池和指数历史，不能用旧 `bars` 数据伪装 raw/qfq 或指数历史；
4. 执行 `migrations/010_migrate_legacy_intraday_bars.sql`，对账分钟线数量和时间范围；
5. 运行新版应用至少一个完整交易日，确认详情页、盈亏分析、回测、策略和日报无缺失数据；
6. 全部通过后，才可手工删除 `bars`。

## 5. 残余风险

- 新部署的 MySQL 会创建目标表，但不会替已有数据库自动执行历史补数；
- 旧迁移文件和运维文档仍会提到 `bars`，这些是迁移来源和历史追溯内容，不属于运行时回退依赖；
- 生产删除旧表前若未完成备份恢复验证，出现数据缺失时只能依赖外部数据库备份恢复；
- `MockMarketDataStore` 保留 `seed_watchlist_bars` 作为无数据库本地测试夹具，不代表生产保留旧 `bars` 表。

## 6. 复核结论

代码实现达到治理方案要求，未发现阻塞性问题。当前剩余工作属于生产数据迁移、补数、对账和旧表删除，按[迁移操作手册](../operations/2026-08-27-market-data-bars-migration.md)执行即可。
