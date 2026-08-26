import { useEffect, useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import {
  Button,
  Card,
  Col,
  Empty,
  Row,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DAILY_REPORT_PAGE_SIZE, fetchReport, fetchReports } from '@/api/reports';
import { useUiStore } from '@/stores/uiStore';
import type {
  DailyReport,
  DailyReportDecision,
  DailyReportFill,
  DailyReportPosition,
  DailyReportSummary,
  DailyReportTimelineEvent,
} from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';

function mergeReportRows(pages: { daily_reports?: DailyReportSummary[] }[]): DailyReportSummary[] {
  const seen = new Set<string>();
  const rows: DailyReportSummary[] = [];
  for (const page of pages) {
    for (const item of page.daily_reports ?? []) {
      if (seen.has(item.report_date)) continue;
      seen.add(item.report_date);
      rows.push(item);
    }
  }
  return rows;
}

function fillDirectionTone(direction: string): string {
  return ['卖出', '减仓', '清仓'].includes(direction) ? 'success' : 'default';
}

function decisionCopy(item: DailyReportDecision): string {
  if (item.explanation) return item.explanation;
  const reasons = item.risk_reasons ?? [];
  return reasons.length ? reasons.join('；') : '策略未提供补充说明。';
}

function ReportListItem({
  item,
  active,
  onSelect,
}: {
  item: DailyReportSummary;
  active: boolean;
  onSelect: (date: string) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onSelect(item.report_date)}
      style={{
        width: '100%',
        minHeight: 88,
        padding: '14px 16px',
        border: 0,
        borderBottom: '1px solid #edf1f6',
        background: active ? '#f0f7ff' : '#fff',
        boxShadow: active ? 'inset 4px 0 0 #1677ff' : 'none',
        textAlign: 'left',
        cursor: 'pointer',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
        <span className="tabular" style={{ fontWeight: 700, fontSize: 14 }}>
          {item.report_date}
        </span>
        <Tag color="blue">{item.status}</Tag>
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: 9,
          color: '#667085',
          fontSize: 12,
        }}
      >
        <span className={toneClass(item.daily_pnl)}>{fmtMoney(item.daily_pnl)} 元</span>
        <span>{fmtPct(item.daily_return)}</span>
      </div>
    </button>
  );
}

function ReportDetailPanel({ report, loading }: { report: DailyReport | null; loading: boolean }) {
  if (loading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: 320, padding: 32 }}>
        <Spin tip="正在读取日报..." />
      </div>
    );
  }

  if (!report) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: 320, padding: 32, color: '#667085' }}>
        暂无已归档日报。收盘后将自动生成结构化复盘。
      </div>
    );
  }

  const account = report.account ?? {};
  const positions = report.positions ?? [];
  const fills = report.fills ?? [];
  const decisions = report.decisions ?? [];
  const timeline = report.decision_timeline ?? [];
  const systemNotes = report.system_notes ?? [];
  const displayedDecisions = decisions.slice(-50).reverse();

  const positionColumns: ColumnsType<DailyReportPosition> = [
    { title: '证券', dataIndex: 'symbol', key: 'symbol' },
    { title: '数量', dataIndex: 'quantity', key: 'quantity' },
    {
      title: '成本',
      dataIndex: 'average_cost',
      key: 'average_cost',
      render: (v) => fmtMoney(v),
    },
    {
      title: '收盘价',
      dataIndex: 'last_price',
      key: 'last_price',
      render: (v) => fmtMoney(v),
    },
    {
      title: '市值',
      dataIndex: 'market_value',
      key: 'market_value',
      render: (v) => fmtMoney(v),
    },
    {
      title: '浮动盈亏',
      dataIndex: 'unrealized_pnl',
      key: 'unrealized_pnl',
      render: (v) => <span className={toneClass(v)}>{fmtMoney(v)}</span>,
    },
    {
      title: '仓位',
      dataIndex: 'position_weight',
      key: 'position_weight',
      render: (v) => fmtPct(v),
    },
  ];

  const fillColumns: ColumnsType<DailyReportFill> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      render: (v: string) => v.slice(11, 19),
    },
    { title: '证券', dataIndex: 'symbol', key: 'symbol' },
    {
      title: '操作',
      dataIndex: 'direction',
      key: 'direction',
      render: (v: string) => <Tag color={fillDirectionTone(v)}>{v}</Tag>,
    },
    { title: '数量', dataIndex: 'quantity', key: 'quantity' },
    { title: '成交价', dataIndex: 'price', key: 'price', render: (v) => fmtMoney(v) },
    { title: '手续费', dataIndex: 'fee', key: 'fee', render: (v) => fmtMoney(v) },
  ];

  const timelineColumns: ColumnsType<DailyReportTimelineEvent> = [
    {
      title: '时间',
      dataIndex: 'event_at',
      key: 'event_at',
      render: (v?: string) => (v ? v.slice(11, 19) : ''),
    },
    { title: '证券', dataIndex: 'symbol', key: 'symbol', render: (v) => v ?? '' },
    { title: '阶段', dataIndex: 'phase', key: 'phase', render: (v) => v ?? '' },
    {
      title: '状态',
      key: 'status',
      render: (_, row) => row.direction ?? row.status ?? '',
    },
    {
      title: '说明',
      dataIndex: 'reasons',
      key: 'reasons',
      render: (v?: string[]) => (v ?? []).join('；'),
    },
  ];

  return (
    <div>
      <Row
        gutter={[1, 1]}
        style={{ borderBottom: '1px solid #edf1f6', background: '#edf1f6' }}
      >
        <Col xs={24} md={12} lg={10}>
          <div style={{ padding: '18px 20px', background: '#fff', minHeight: 120 }}>
            <span className="kicker">交易日报</span>
            <div className="tabular" style={{ marginTop: 5, fontSize: 24, fontWeight: 720 }}>
              {report.report_date}
            </div>
            <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 13 }}>
              {report.summary}
            </Typography.Paragraph>
          </div>
        </Col>
        {[
          { label: '总资产', value: `${fmtMoney(account.total_asset)} 元`, tone: '' },
          { label: '当日收益', value: `${fmtMoney(account.daily_pnl)} 元`, tone: toneClass(account.daily_pnl) },
          { label: '当日收益率', value: fmtPct(account.daily_return), tone: toneClass(account.daily_return) },
        ].map((item) => (
          <Col xs={8} md={4} lg={5} key={item.label}>
            <div style={{ padding: '18px 20px', background: '#fff', minHeight: 120 }}>
              <span className="kicker">{item.label}</span>
              <strong className={`tabular ${item.tone}`} style={{ display: 'block', marginTop: 7, fontSize: 16 }}>
                {item.value}
              </strong>
            </div>
          </Col>
        ))}
      </Row>

      {systemNotes.length ? (
        <section style={{ padding: 20, borderBottom: '1px solid #edf1f6' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <Typography.Title level={5} style={{ margin: 0 }}>
              运行备注
            </Typography.Title>
            <Typography.Text type="secondary" className="tabular">
              {systemNotes.length} 条
            </Typography.Text>
          </div>
          {systemNotes.map((text, index) => (
            <Typography.Paragraph key={index} type="secondary" style={{ margin: '7px 0 0', fontSize: 13 }}>
              {text}
            </Typography.Paragraph>
          ))}
        </section>
      ) : null}

      <section style={{ padding: 20, borderBottom: '1px solid #edf1f6' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            收盘持仓
          </Typography.Title>
          <Typography.Text type="secondary" className="tabular">
            {positions.length} 个标的 · 仓位 {fmtPct(account.position_ratio)}
          </Typography.Text>
        </div>
        <Table
          size="small"
          rowKey="symbol"
          columns={positionColumns}
          dataSource={positions}
          pagination={false}
          locale={{ emptyText: '收盘时没有持仓。' }}
          scroll={{ x: true }}
        />
      </section>

      <section style={{ padding: 20, borderBottom: '1px solid #edf1f6' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            模拟成交
          </Typography.Title>
          <Typography.Text type="secondary" className="tabular">
            {fills.length} 笔
          </Typography.Text>
        </div>
        <Table
          size="small"
          rowKey={(row, index) => `${row.timestamp}-${row.symbol}-${index}`}
          columns={fillColumns}
          dataSource={fills}
          pagination={false}
          locale={{ emptyText: '当日没有模拟成交。' }}
          scroll={{ x: true }}
        />
      </section>

      <section style={{ padding: 20, borderBottom: '1px solid #edf1f6' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            决策逻辑
          </Typography.Title>
          <Typography.Text type="secondary" className="tabular">
            {decisions.length} 条
            {decisions.length > displayedDecisions.length ? ' · 展示最近 50 条' : ''}
          </Typography.Text>
        </div>
        {displayedDecisions.length ? (
          <div style={{ display: 'grid', gap: 10 }}>
            {displayedDecisions.map((item, index) => (
              <article
                key={`${item.symbol}-${item.direction}-${index}`}
                style={{ padding: '14px 0', borderTop: index ? '1px solid #edf1f6' : 0 }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <Typography.Text strong>
                    {item.direction} · {item.symbol}
                  </Typography.Text>
                  <Tag color={item.approved ? 'blue' : 'default'}>
                    {item.approved ? '风控通过' : '未执行'}
                  </Tag>
                </div>
                <Typography.Paragraph type="secondary" style={{ margin: '7px 0 0', fontSize: 13 }}>
                  {decisionCopy(item)}
                </Typography.Paragraph>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 9 }}>
                  {(item.evidence ?? []).map((text, i) => (
                    <Tag key={`e-${i}`} style={{ fontSize: 11 }}>
                      依据 · {text}
                    </Tag>
                  ))}
                  {(item.objections ?? []).map((text, i) => (
                    <Tag key={`o-${i}`} style={{ fontSize: 11 }}>
                      约束 · {text}
                    </Tag>
                  ))}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Typography.Text type="secondary">当日没有策略决策记录。</Typography.Text>
        )}
      </section>

      <section style={{ padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            决策与订单轨迹
          </Typography.Title>
          <Typography.Text type="secondary" className="tabular">
            {timeline.length} 条
          </Typography.Text>
        </div>
        <Table
          size="small"
          rowKey={(row, index) => `${row.event_at ?? ''}-${row.symbol ?? ''}-${index}`}
          columns={timelineColumns}
          dataSource={timeline}
          pagination={false}
          locale={{ emptyText: '本次归档没有额外订单状态变化。' }}
          scroll={{ x: true }}
        />
      </section>
    </div>
  );
}

export function ReportArchive() {
  const announce = useUiStore((s) => s.announce);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const listQuery = useInfiniteQuery({
    queryKey: ['reports'],
    queryFn: ({ pageParam = 0, signal }) =>
      fetchReports({ limit: DAILY_REPORT_PAGE_SIZE, offset: pageParam }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const incoming = lastPage.daily_reports ?? [];
      if (incoming.length < DAILY_REPORT_PAGE_SIZE) return undefined;
      return mergeReportRows(allPages).length;
    },
    refetchInterval: 30_000,
  });

  const rows = useMemo(
    () => mergeReportRows(listQuery.data?.pages ?? []),
    [listQuery.data?.pages],
  );

  useEffect(() => {
    if (listQuery.isError) {
      setSelectedDate(null);
    }
  }, [listQuery.isError]);

  useEffect(() => {
    if (!rows.length) {
      setSelectedDate(null);
      return;
    }
    if (!selectedDate || !rows.some((item) => item.report_date === selectedDate)) {
      setSelectedDate(rows[0].report_date);
    }
  }, [rows, selectedDate]);

  useEffect(() => {
    if (listQuery.isError) {
      announce('日报归档读取失败。');
    }
  }, [listQuery.isError, announce]);

  const detailQuery = useQuery({
    queryKey: ['report', selectedDate],
    queryFn: ({ signal }) => fetchReport(selectedDate!, signal),
    enabled: Boolean(selectedDate),
  });

  useEffect(() => {
    if (detailQuery.isError) {
      announce('日报详情读取失败。');
    }
  }, [detailQuery.isError, announce]);

  const detailReport = detailQuery.data?.daily_report ?? null;
  const detailLoading = detailQuery.isLoading;
  const detailMessage =
    listQuery.isError
      ? '日报归档读取失败，请稍后重试。'
      : !rows.length && !listQuery.isLoading
        ? undefined
        : detailQuery.isError
          ? '日报读取失败，请稍后重试。'
          : undefined;

  if (listQuery.isLoading) {
    return <Spin style={{ display: 'block', margin: '48px auto' }} />;
  }

  return (
    <Row gutter={[20, 20]} align="top">
      <Col xs={24} lg={7}>
        <Card
          size="small"
          title="日报归档"
          extra={<Tag>{rows.length} 份</Tag>}
          styles={{ body: { padding: 0 } }}
        >
          <Typography.Paragraph type="secondary" style={{ margin: '0 12px 12px', fontSize: 12 }}>
            按交易日回看策略执行
          </Typography.Paragraph>
          <div style={{ maxHeight: 'calc(100dvh - 280px)', overflowY: 'auto' }}>
            {rows.length ? (
              rows.map((item) => (
                <ReportListItem
                  key={item.report_date}
                  item={item}
                  active={item.report_date === selectedDate}
                  onSelect={setSelectedDate}
                />
              ))
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无日报。交易日收盘后，monitor 会自动归档。"
                style={{ padding: 24 }}
              />
            )}
            {listQuery.hasNextPage ? (
              <div style={{ padding: 12 }}>
                <Button
                  block
                  loading={listQuery.isFetchingNextPage}
                  onClick={() => void listQuery.fetchNextPage()}
                >
                  加载更早日报
                </Button>
              </div>
            ) : null}
          </div>
        </Card>
      </Col>
      <Col xs={24} lg={17}>
        <Card size="small" styles={{ body: { padding: 0 } }} aria-live="polite">
          {detailMessage ? (
            <div style={{ display: 'grid', placeItems: 'center', minHeight: 320, padding: 32, color: '#667085' }}>
              {detailMessage}
            </div>
          ) : (
            <ReportDetailPanel
              report={detailReport}
              loading={Boolean(selectedDate) && detailLoading}
            />
          )}
        </Card>
      </Col>
    </Row>
  );
}
