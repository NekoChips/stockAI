import { useMemo } from 'react';
import { Alert, Badge, Card, Col, Empty, Row, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { StrategyReadinessPayload, StrategyReadinessRow, WatchlistItem } from '@/types/dashboard';

const STATUS_META: Record<string, { label: string; status: 'success' | 'warning' | 'error' | 'default' }> = {
  READY: { label: '可交易', status: 'success' },
  NEUTRAL: { label: '可交易', status: 'success' },
  DEGRADED: { label: '降级', status: 'warning' },
  UNAVAILABLE: { label: '禁止交易', status: 'error' },
  INVALID: { label: '禁止交易', status: 'error' },
};

function statusMeta(value?: string) {
  return STATUS_META[value ?? ''] ?? { label: '待检查', status: 'default' as const };
}

function StatusBadge({ value }: { value?: string }) {
  const meta = statusMeta(value);
  return <Badge status={meta.status} text={meta.label} />;
}

function DependencyCard({
  title,
  detail,
  status,
}: {
  title: string;
  detail: string;
  status?: string;
}) {
  return (
    <Card size="small" styles={{ body: { padding: '12px 14px' } }}>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Typography.Text strong>{title}</Typography.Text>
          <StatusBadge value={status} />
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {detail}
        </Typography.Text>
      </Space>
    </Card>
  );
}

export function StrategyReadinessPanel({
  watchlist,
  selectedSymbol,
  onSymbolChange,
  data,
  loading,
  error,
}: {
  watchlist: WatchlistItem[];
  selectedSymbol?: string;
  onSymbolChange: (symbol: string) => void;
  data?: StrategyReadinessPayload;
  loading: boolean;
  error?: Error | null;
}) {
  const columns: ColumnsType<StrategyReadinessRow> = useMemo(
    () => [
      {
        title: '策略',
        key: 'strategy',
        render: (_, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{row.name_zh}</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {row.name_en} · {row.strategy_id}
            </Typography.Text>
          </Space>
        ),
      },
      { title: '状态', dataIndex: 'status', key: 'status', render: (value) => <StatusBadge value={value} /> },
      {
        title: '权重',
        key: 'weight',
        render: (_, row) => `${row.configured_weight ?? 0} → ${row.normalized_weight ?? 0}`,
      },
      { title: '数据源', dataIndex: 'source', key: 'source', render: (value) => value || '--' },
      {
        title: '最近成功',
        dataIndex: 'last_success_at',
        key: 'last_success_at',
        render: (value) => (value ? String(value).slice(0, 16).replace('T', ' ') : '--'),
      },
      {
        title: '说明',
        dataIndex: 'reason',
        key: 'reason',
        render: (value) => <Typography.Text type="secondary">{value || '数据已满足策略依赖。'}</Typography.Text>,
      },
    ],
    [],
  );

  if (!watchlist.length) {
    return <Card size="small" title="数据就绪度"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="观察池为空，暂无可检查的策略数据。" /></Card>;
  }

  return (
    <Card
      size="small"
      title={
        <Space wrap>
          <span>数据就绪度</span>
          <Tag color="blue">策略输入审计</Tag>
        </Space>
      }
      extra={
        <Select
          aria-label="选择要检查的观察标的"
          value={selectedSymbol}
          onChange={onSymbolChange}
          loading={loading}
          style={{ minWidth: 220 }}
          options={watchlist.map((item) => ({ label: `${item.name} · ${item.symbol}`, value: item.symbol }))}
        />
      }
      styles={{ body: { padding: 16 } }}
    >
      {error ? <Alert type="error" showIcon message="策略就绪度读取失败" description="请刷新页面重试，当前不会据此放行交易。" style={{ marginBottom: 14 }} /> : null}
      {data ? (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
            <Space direction="vertical" size={0}>
              <Typography.Title level={5} style={{ margin: 0 }}>{data.name || data.symbol}</Typography.Title>
              <Typography.Text type="secondary">{data.symbol} · 数据来自数据库快照</Typography.Text>
            </Space>
            <Space wrap>
              <Tag color={data.trading_enabled ? 'green' : 'orange'}>{data.trading_enabled ? '交易已启用' : '仅观察'}</Tag>
              <Tag>{(data.strategies ?? []).filter((item) => item.trade_allowed).length} 项允许参与</Tag>
            </Space>
          </div>
          <Row gutter={[10, 10]}>
            <Col xs={24} md={8}><DependencyCard title="实时行情" detail={data.quote?.reason || '--'} status={data.quote?.status} /></Col>
            <Col xs={24} md={8}><DependencyCard title="日 K 历史" detail={`${data.daily_bars?.points ?? 0} 条已入库`} status={data.daily_bars?.status} /></Col>
            <Col xs={24} md={8}><DependencyCard title="板块映射" detail={`${data.sector?.value || '综合'}${data.sector?.defaulted ? ' · 默认板块' : ''}`} status={data.sector?.status} /></Col>
          </Row>
          <Table
            style={{ marginTop: 16 }}
            size="small"
            rowKey="strategy_id"
            loading={loading}
            columns={columns}
            dataSource={data.strategies ?? []}
            pagination={{ pageSize: 8, hideOnSinglePage: true, showSizeChanger: false }}
            scroll={{ x: 860 }}
          />
          {data.tasks?.length ? (
            <Space wrap size={[8, 8]} style={{ marginTop: 12 }}>
              {data.tasks.map((task) => (
                <Tag key={`${task.task_name}-${task.trade_date}`} color={task.failure_count ? 'orange' : 'green'}>
                  {task.task_name} · {task.status}
                </Tag>
              ))}
            </Space>
          ) : null}
        </>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={loading ? '正在读取数据状态…' : '请选择观察标的。'} />
      )}
    </Card>
  );
}
