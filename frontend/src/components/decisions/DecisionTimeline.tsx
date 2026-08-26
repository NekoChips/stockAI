import { Card, Timeline, Typography } from 'antd';
import type { OverviewPayload } from '@/types/dashboard';
import { fmtMoney } from '@/utils/format';

interface DecisionTimelineProps {
  data: OverviewPayload;
}

interface TimelineRecord {
  kind: 'approved' | 'rejected' | '';
  title: string;
  detail: string;
  time: string;
}

function buildRecords(data: OverviewPayload): TimelineRecord[] {
  const decisions = data.today_decisions ?? [];
  const fills = data.recent_fills ?? [];
  const actionable = decisions.filter((item) => !['观望', '持有'].includes(item.direction));
  const watching = decisions.filter((item) => ['观望', '持有'].includes(item.direction));

  const actual: TimelineRecord[] = actionable.map((item, index) => ({
    kind: item.approved ? 'approved' : 'rejected',
    title: `${item.direction || '观望'} · ${item.symbol}`,
    detail:
      (item.reasons ?? []).join('；') ||
      (item.approved ? '风控通过，等待模拟执行。' : '风控未批准本次建议。'),
    time: `策略 ${index + 1}`,
  }));

  if (watching.length) {
    const symbols = [...new Set(watching.map((item) => item.symbol))];
    actual.push({
      kind: '',
      title: `持续观望 · ${symbols.join('、')}`,
      detail: '当前未形成满足风控条件的交易信号，监控将继续跟踪。',
      time: '本日状态',
    });
  }

  [...fills].reverse().forEach((fill) => {
    actual.push({
      kind: 'approved',
      title: `模拟成交 · ${fill.symbol}`,
      detail: `${fill.direction || '成交'} ${fill.quantity} 份，成交价 ${fmtMoney(fill.price)}`,
      time: '最近成交',
    });
  });

  const watchSymbols =
    (data.watchlist ?? [])
      .map((item) => item.symbol)
      .slice(0, 3)
      .join('、') || '当前观察池';

  const readiness: TimelineRecord[] = [
    {
      kind: 'approved',
      title: '行情订阅已就绪',
      detail: '已连接当前模拟盘数据流，等待下一次轮询结果。',
      time: '实时监控',
    },
    {
      kind: '',
      title: '策略扫描待命',
      detail: `观察 ${watchSymbols} 的技术指标和量化信号。`,
      time: '信号层',
    },
    {
      kind: '',
      title: '风险复核待命',
      detail: '仓位上限、T+1 与人工确认规则已加载。',
      time: '风控层',
    },
    {
      kind: '',
      title: '模拟订单待命',
      detail: '仅在策略与风控同时满足时创建模拟订单。',
      time: '执行层',
    },
  ];

  return actual.length
    ? actual.concat(readiness.slice(0, Math.max(0, 4 - actual.length)))
    : readiness;
}

function nodeColor(kind: TimelineRecord['kind']): 'green' | 'red' | 'blue' | 'gray' {
  if (kind === 'approved') return 'green';
  if (kind === 'rejected') return 'red';
  return 'gray';
}

export function DecisionTimeline({ data }: DecisionTimelineProps) {
  const decisions = data.today_decisions ?? [];
  const actionable = decisions.filter((item) => !['观望', '持有'].includes(item.direction));
  const watching = decisions.filter((item) => ['观望', '持有'].includes(item.direction));
  const meta = actionable.length
    ? `${actionable.length} 条有效决策`
    : watching.length
      ? '持续观望'
      : '待命流程';

  const records = buildRecords(data);

  return (
    <Card
      title="决策轨道"
      extra={<Typography.Text type="secondary">{meta}</Typography.Text>}
      styles={{ body: { maxHeight: 480, overflow: 'auto' } }}
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 16, fontSize: 13 }}>
        信号、风控与模拟执行的当日记录
      </Typography.Paragraph>
      <Timeline
        items={records.map((item) => ({
          color: nodeColor(item.kind),
          children: (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <Typography.Text strong>{item.title}</Typography.Text>
                <Typography.Text type="secondary" className="tabular" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                  {item.time}
                </Typography.Text>
              </div>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 4, fontSize: 12 }}>
                {item.detail}
              </Typography.Paragraph>
            </div>
          ),
        }))}
      />
    </Card>
  );
}
