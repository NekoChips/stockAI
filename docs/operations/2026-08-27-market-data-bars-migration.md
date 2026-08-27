# 行情表拆分迁移操作手册

**状态：** active
**负责人：** platform-and-operations
**创建日期：** 2026-08-27
**更新日期：** 2026-08-27
**关联：** [行情数据表治理与 `bars` 淘汰实施方案](../plans/2026-08-27-market-data-table-governance.md)、[数据库数据字典](../architecture/2026-08-27-database-data-dictionary.md)

## 1. 适用范围

本手册用于生产 MySQL 的行情表拆分。应用代码已不再创建、读取或写入 `bars`；已有生产库中的 `bars` 只作为迁移前备份和旧分钟线来源。

本手册不会自动执行 `DROP TABLE bars`。删表必须由运维人员在完成全部验收后单独执行。

## 2. 执行顺序

### 2.1 备份并记录基线

在数据库主机或安装有 MySQL Client 的运维机执行，以下命令在 Shell 中执行，不是在 MySQL 提示符中执行：

```bash
mysqldump -h <db_ip> -P <db_port> -u <db_user> -p \
  --single-transaction --routines --events stock_ai \
  > stock_ai_before_market_table_split.sql
```

如果提示 `mysqldump: command not found`，先安装对应版本的 MySQL Client，再执行备份；不要把 `mysqldump` 粘贴到 `mysql>` 提示符中。

记录迁移前数量：

```sql
SELECT interval_name, COUNT(*) AS row_count,
       MIN(timestamp_value) AS first_time,
       MAX(timestamp_value) AS last_time
FROM bars
GROUP BY interval_name;

SELECT COUNT(*) AS market_quote_count FROM market_quotes;
SELECT COUNT(*) AS market_quote_event_count FROM market_quote_events;
```

### 2.2 创建目标表

在 `stock_ai` 数据库中执行：

```bash
mysql -h <db_ip> -P <db_port> -u <db_user> -p stock_ai \
  < migrations/009_split_market_bar_tables.sql
```

确认目标表和索引存在：

```sql
SHOW CREATE TABLE index_price_tracks;
SHOW CREATE TABLE intraday_bars;
SHOW INDEX FROM index_price_tracks;
SHOW INDEX FROM intraday_bars;
```

### 2.3 重新同步观察池和指数历史

升级应用后，由 monitor 的日 K 同步任务使用 AlphaFeed 重新获取：

- 观察池日 K写入 `bar_price_tracks`，同时保存 raw、qfq 和复权因子；
- 指数日 K 写入 `index_price_tracks`；
- 不从旧 `bars` 推断 raw/qfq，也不把旧指数 K 伪装成新指数数据。

观察池和指数历史同步完成后，执行：

```sql
SELECT symbol, COUNT(*) AS row_count,
       MIN(DATE(timestamp_value)) AS first_date,
       MAX(DATE(timestamp_value)) AS last_date,
       COUNT(DISTINCT source) AS source_count
FROM bar_price_tracks
WHERE interval_name = 'daily'
GROUP BY symbol
ORDER BY symbol;

SELECT symbol, COUNT(*) AS row_count,
       MIN(DATE(timestamp_value)) AS first_date,
       MAX(DATE(timestamp_value)) AS last_date
FROM index_price_tracks
WHERE interval_name = 'daily'
GROUP BY symbol
ORDER BY symbol;
```

### 2.4 迁移旧分钟线

仅将 `bars.interval_name` 为 `minute` 或 `1m` 的数据迁移到 `intraday_bars`：

```bash
mysql -h <db_ip> -P <db_port> -u <db_user> -p stock_ai \
  < migrations/010_migrate_legacy_intraday_bars.sql
```

执行后对比迁移前后每个标的的数量和时间范围：

```sql
SELECT symbol, interval_name, COUNT(*) AS row_count,
       MIN(timestamp_value) AS first_time,
       MAX(timestamp_value) AS last_time
FROM intraday_bars
GROUP BY symbol, interval_name
ORDER BY symbol, interval_name;
```

### 2.5 发布并观察

先发布只包含新存储路径的应用版本，确认：

- Web 详情页的分时、五日和分钟 K 正常；
- 盈亏分析的指数曲线正常；
- 回测、策略运行和日报未出现 `bars` 缺表或查询错误；
- `data_sync_status` 中观察池和指数同步任务无失败积压；
- 至少完成一个交易日运行观察。

## 3. 删除 `bars` 前检查

以下检查全部通过后，才可删除旧表：

```text
rg -n "FROM bars|INTO bars|UPDATE bars|DELETE FROM bars|save_bars\(|load_bars\(" src tests migrations
```

允许出现的结果仅限迁移说明、历史文档和本手册；正式应用路径不得出现旧表依赖。

同时确认：

- `bar_price_tracks` 的所有有效观察池标的已达到配置的历史长度；
- `index_price_tracks` 的所有配置指数已有可用历史数据；
- `intraday_bars` 的分钟线迁移行数、时间范围和价格范围已对账；
- 备份文件存在且可以在隔离库恢复；
- 发布版本已稳定运行至少一个完整交易日。

## 4. 最终删除与回滚

确认人完成审批后，在 MySQL 提示符中执行：

```sql
DROP TABLE bars;
```

删除后立即执行：

```sql
SHOW TABLES LIKE 'bars';
```

结果为空才表示旧表已删除。若新表查询或应用运行异常，先回滚应用镜像；不要重新让应用写入 `bars`。数据恢复通过迁移前备份或数据库快照执行。

