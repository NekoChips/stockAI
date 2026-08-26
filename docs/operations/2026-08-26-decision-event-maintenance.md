# 决策事件维护

**状态：** implemented
**负责人：** platform-and-operations
**创建日期：** 2026-08-26
**更新日期：** 2026-08-26
**关联：** [决策事件审计分离设计](../design/2026-08-26-decision-event-audit-separation.md)

## 1. 运行时行为

- 当前版本不保存每轮原始策略评估，不创建 `decision_audit_events`。
- 相同策略状态不会重复写入 `decision_events`。
- 每条策略业务事件记录事件发生前的空仓/持仓状态、数量和仓位比例。
- 服务启动后的首次 monitor 维护会压缩历史重复业务事件。
- 后续每个交易日只压缩当天事件，并按批次清理过期事件。
- 策略事件默认保留 30 天，订单状态事件默认保留 730 天；日报、订单主表和成交记录不受清理影响。

## 2. 已有 MySQL 数据库

应用启动时会自动补齐 `decision_events` 的幂等字段和索引。完成一次应用启动后，如需清理升级前已产生的大量重复事件，可在 MySQL 8.0 中执行：

```text
migrations/008_compact_decision_events.sql
```

执行前先在数据库所在主机使用数据库管理员提供的备份工具备份 `decision_events` 和 `daily_reports`。备份命令不要粘贴到 MySQL SQL 客户端中执行；该迁移文件只包含 SQL。

脚本会创建 `decision_events_backup_before_compaction` 备份表，按交易日、阶段、标的或订单状态流保留有意义的状态变化，再删除连续重复事件。它不会删除日报和订单主数据。

## 3. 验证

```sql
SELECT phase, COUNT(*) AS event_count
FROM decision_events
GROUP BY phase;

SELECT trade_date, symbol, COUNT(*) AS decision_count
FROM decision_events
WHERE phase = 'decision'
GROUP BY trade_date, symbol
ORDER BY trade_date DESC, decision_count DESC;

SELECT COUNT(*) AS reports_with_timeline
FROM daily_reports
WHERE JSON_CONTAINS_PATH(report_data, 'one', '$.decision_timeline');
```

页面刷新后，日报中的轨迹标题应为“策略与执行轨迹”，阶段显示“策略评估”或“订单状态”，不再直接显示 `decision`。

## 4. 回滚边界

如迁移验证失败，先停止重复写入，再使用 `decision_events_backup_before_compaction` 恢复事件表。恢复操作应由数据库管理员在备份确认后执行，不能通过页面直接删除订单或日报数据。
