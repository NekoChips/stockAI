import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Collapse, Empty, Select, Space, Spin, Timeline, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';

import { fetchDecisionEvents } from '@/api/dashboard';
import { OVERVIEW_POLL_MS } from '@/components/dashboard/DashboardRefreshControls';
import type { DecisionEvent, DecisionEventType } from '@/types/dashboard';
import { fmtMoney } from '@/utils/format';

interface DecisionTimelineProps {
  watchlistCount?: number;
  statusHint?: string;
  onAddInstrument?: () => void;
}

type TypeFilter = 'all' | DecisionEventType;

const TYPE_OPTIONS: { label: string; value: TypeFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '决策', value: 'decision' },
  { label: '订单', value: 'order' },
  { label: '成交', value: 'fill' },
];

function typeLabel(type: DecisionEventType): string {
  if (type === 'decision') return '决策';
  if (type === 'order') return '订单';
  return '成交';
}

function formatEventAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '—';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function nodeColor(event: DecisionEvent): 'green' | 'red' | 'blue' | 'gray' {
  if (event.type === 'fill') return 'blue';
  if (event.approved === true) return 'green';
  if (event.approved === false) return 'red';
  return 'gray';
}

function eventHeadline(event: DecisionEvent): { prefix: string; suffix: string } {
  const action = event.direction || (event.type === 'fill' ? '成交' : typeLabel(event.type));
  if (event.type === 'decision') {
    const verdict = event.approved === true ? '通过' : event.approved === false ? '拒绝' : '待定';
    return { prefix: `${action} · `, suffix: ` · ${verdict}` };
  }
  if (event.type === 'order') {
    const status = event.status ? ` · ${event.status}` : '';
    return { prefix: `${action} · `, suffix: status };
  }
  return { prefix: '模拟成交 · ', suffix: '' };
}

function eventDetail(event: DecisionEvent): string {
  if (event.type === 'fill') {
    const qty = event.quantity ?? '—';
    const price = event.price != null ? fmtMoney(event.price) : '—';
    return `${event.direction || '成交'} ${qty} 份，成交价 ${price}`;
  }
  const reasons = (event.reasons ?? []).filter(Boolean);
  if (reasons.length) return reasons.join('；');
  if (event.type === 'decision') {
    if (event.approved === true) return '风控通过，等待模拟执行。';
    if (event.approved === false) return '风控未批准本次建议。';
    return '决策已记录。';
  }
  if (event.status) return `订单状态：${event.status}`;
  return '订单事件已记录。';
}

function EventHeadline({ event }: { event: DecisionEvent }) {
  const { prefix, suffix } = eventHeadline(event);
  return (
    <Typography.Text strong>
      {prefix}
      {event.symbol ? (
        <Link to={`/instruments/${encodeURIComponent(event.symbol)}`}>{event.symbol}</Link>
      ) : (
        '—'
      )}
      {suffix}
    </Typography.Text>
  );
}

function FillDetails({ event }: { event: DecisionEvent }) {
  const rows: { label: string; value: string }[] = [
    { label: '数量', value: event.quantity != null ? String(event.quantity) : '—' },
    { label: '成交价', value: event.price != null ? fmtMoney(event.price) : '—' },
    { label: '手续费', value: event.fee != null ? fmtMoney(event.fee) : '—' },
    { label: '滑点', value: event.slippage != null ? fmtMoney(event.slippage) : '—' },
    { label: '订单号', value: event.order_id || '—' },
  ];

  return (
    <Collapse
      size="small"
      ghost
      style={{ marginTop: 4 }}
      items={[
        {
          key: 'fill-detail',
          label: <Typography.Text type="secondary" style={{ fontSize: 12 }}>成交详情</Typography.Text>,
          children: (
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              {rows.map((row) => (
                <div
                  key={row.label}
                  style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}
                >
                  <Typography.Text type="secondary">{row.label}</Typography.Text>
                  <Typography.Text className="tabular">{row.value}</Typography.Text>
                </div>
              ))}
            </Space>
          ),
        },
      ]}
    />
  );
}

export function DecisionTimeline({
  watchlistCount = 0,
  statusHint,
  onAddInstrument,
}: DecisionTimelineProps) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [symbolFilter, setSymbolFilter] = useState<string>('all');
  const [directionFilter, setDirectionFilter] = useState<string>('all');

  const { data, isLoading, isError } = useQuery({
    queryKey: ['decision-events'],
    queryFn: ({ signal }) => fetchDecisionEvents(undefined, signal),
    refetchInterval: OVERVIEW_POLL_MS,
  });

  const events = data?.events ?? [];
  const fillCount = data?.fill_count ?? 0;

  const symbolOptions = useMemo(() => {
    const symbols = [...new Set(events.map((item) => item.symbol).filter(Boolean))].sort();
    return [
      { label: '全部标的', value: 'all' },
      ...symbols.map((symbol) => ({ label: symbol, value: symbol })),
    ];
  }, [events]);

  const directionOptions = useMemo(() => {
    const directions = [
      ...new Set(events.map((item) => item.direction).filter((item): item is string => Boolean(item))),
    ].sort();
    return [
      { label: '全部操作', value: 'all' },
      ...directions.map((direction) => ({ label: direction, value: direction })),
    ];
  }, [events]);

  const filtered = useMemo(() => {
    return events
      .filter((item) => (typeFilter === 'all' ? true : item.type === typeFilter))
      .filter((item) => (symbolFilter === 'all' ? true : item.symbol === symbolFilter))
      .filter((item) => (directionFilter === 'all' ? true : item.direction === directionFilter))
      .slice()
      .sort((a, b) => String(a.event_at || '').localeCompare(String(b.event_at || '')));
  }, [events, typeFilter, symbolFilter, directionFilter]);

  const hasActiveFilter =
    typeFilter !== 'all' || symbolFilter !== 'all' || directionFilter !== 'all';

  const emptyDescription = isError
    ? '无法加载决策流，请稍后重试。'
    : events.length === 0
      ? watchlistCount === 0
        ? '观察池为空。添加标的后，策略信号与成交会出现在这里。'
        : '今日暂无决策、订单或成交记录。监控将继续跟踪观察池。'
      : '没有符合当前筛选条件的事件。';

  return (
    <Card
      title="决策轨道"
      extra={
        <Typography.Text type="secondary">
          今日 {fillCount} 笔成交 · {events.length} 条事件
        </Typography.Text>
      }
      styles={{ body: { maxHeight: 520, overflow: 'auto' } }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
          marginBottom: 12,
          paddingBottom: 10,
          borderBottom: '1px solid var(--line)',
        }}
      >
        <Typography.Text style={{ fontSize: 13 }}>
          监控中 · 观察池 {watchlistCount} 只
        </Typography.Text>
        {statusHint ? (
          <Typography.Text type="secondary" className="tabular" style={{ fontSize: 12 }}>
            {statusHint}
          </Typography.Text>
        ) : null}
      </div>

      <Space wrap size={[8, 8]} style={{ marginBottom: 14, width: '100%' }}>
        <Select
          size="small"
          value={typeFilter}
          options={TYPE_OPTIONS}
          onChange={setTypeFilter}
          style={{ minWidth: 96 }}
          aria-label="按类型筛选"
        />
        <Select
          size="small"
          value={symbolFilter}
          options={symbolOptions}
          onChange={setSymbolFilter}
          style={{ minWidth: 120 }}
          showSearch
          optionFilterProp="label"
          aria-label="按标的筛选"
        />
        <Select
          size="small"
          value={directionFilter}
          options={directionOptions}
          onChange={setDirectionFilter}
          style={{ minWidth: 108 }}
          aria-label="按操作筛选"
        />
      </Space>

      {isLoading && !data ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
          <Spin />
        </div>
      ) : filtered.length === 0 ? (
        <Empty
          description={
            <div style={{ maxWidth: 280, margin: '0 auto' }}>
              <Typography.Paragraph style={{ marginBottom: 4 }}>{emptyDescription}</Typography.Paragraph>
            </div>
          }
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ padding: '16px 0 8px' }}
        >
          {hasActiveFilter && events.length > 0 ? (
            <Typography.Link
              onClick={() => {
                setTypeFilter('all');
                setSymbolFilter('all');
                setDirectionFilter('all');
              }}
            >
              清除筛选
            </Typography.Link>
          ) : null}
          {!hasActiveFilter && events.length === 0 && onAddInstrument && watchlistCount === 0 ? (
            <Button type="primary" size="small" icon={<PlusOutlined />} onClick={onAddInstrument}>
              添加标的
            </Button>
          ) : null}
        </Empty>
      ) : (
        <Timeline
          items={filtered.map((event, index) => ({
            color: nodeColor(event),
            children: (
              <div key={`${event.type}-${event.event_at}-${event.symbol}-${index}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <EventHeadline event={event} />
                  <Typography.Text
                    type="secondary"
                    className="tabular"
                    style={{ fontSize: 11, whiteSpace: 'nowrap' }}
                  >
                    {formatEventAt(event.event_at)}
                  </Typography.Text>
                </div>
                <Typography.Paragraph
                  type="secondary"
                  style={{ marginBottom: 0, marginTop: 4, fontSize: 12 }}
                >
                  {eventDetail(event)}
                </Typography.Paragraph>
                {event.type === 'fill' ? <FillDetails event={event} /> : null}
              </div>
            ),
          }))}
        />
      )}
    </Card>
  );
}
