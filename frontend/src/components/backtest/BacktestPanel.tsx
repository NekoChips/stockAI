import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Row,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import { CheckOutlined, PlayCircleOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { confirmBacktests, fetchBacktests, runBacktest } from '@/api/backtests';
import { useUiStore } from '@/stores/uiStore';
import type { BacktestRun } from '@/types/dashboard';
import { fmtPct, toneClass } from '@/utils/format';

const TERMINAL_STATUSES = ['已确认', '已应用', '已拒绝'] as const;

const STRATEGY_NAMES: Record<string, string> = {
  momentum_grid: '动量网格策略',
  mean_reversion_grid: '均值回归策略',
  relative_strength: '相对强弱轮动',
  learning_review: '学习复盘',
};

function isTerminal(status: string): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

function strategyName(id: string): string {
  return STRATEGY_NAMES[id] ?? id;
}

function metricNumber(run: BacktestRun, key: keyof BacktestRun['metrics']): number | null {
  const value = Number(run.metrics?.[key]);
  return Number.isFinite(value) ? value : null;
}

function signedPct(value: number | null): string {
  return value === null ? '--' : `${value > 0 ? '+' : ''}${fmtPct(value)}`;
}

function drawdownPct(value: number | null): string {
  return value === null ? '--' : `${value > 0 ? '-' : ''}${fmtPct(value)}`;
}

function ratioValue(value: number | null): string {
  return value === null ? '--' : `${value.toFixed(2)}x`;
}

function backtestScore(run: BacktestRun): number | null {
  const total = metricNumber(run, 'total_return');
  const drawdown = metricNumber(run, 'max_drawdown');
  return total === null ? null : total - (drawdown ?? 0);
}

function BacktestMetrics({ run }: { run: BacktestRun }) {
  const total = metricNumber(run, 'total_return');
  const drawdown = metricNumber(run, 'max_drawdown');
  const winRate = metricNumber(run, 'win_rate');
  const ratio = metricNumber(run, 'profit_loss_ratio');
  const turnover = metricNumber(run, 'turnover');
  const losses = metricNumber(run, 'max_consecutive_losses');

  const items = [
    { label: '收益率', value: signedPct(total), className: toneClass(total) },
    { label: '最大回撤', value: drawdownPct(drawdown), className: 'risk' },
    { label: '胜率', value: winRate === null ? '--' : fmtPct(winRate), className: '' },
    { label: '盈亏比', value: ratioValue(ratio), className: '' },
    { label: '换手率', value: turnover === null ? '--' : fmtPct(turnover), className: '' },
    {
      label: '连续亏损',
      value: losses === null ? '--' : `${losses} 次`,
      className: 'risk',
    },
  ];

  return (
    <div>
      <div className="backtest-metric-grid">
        {items.map((item) => (
          <div key={item.label} className="backtest-metric">
            <span className="backtest-metric-label">{item.label}</span>
            <strong className={`backtest-metric-value ${item.className}`}>{item.value}</strong>
          </div>
        ))}
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 11, marginTop: 8, display: 'block' }}>
        口径：前复权日线 · 已计入手续费与滑点
      </Typography.Text>
    </div>
  );
}

function BacktestLearning({ run }: { run: BacktestRun }) {
  const summary = String(run.metrics?.summary || '已完成学习复盘，等待人工确认。')
    .replace(/^# 策略学习总结\s*/, '')
    .split('\n')
    .filter(Boolean)
    .slice(0, 2)
    .join(' · ');
  const proposals = Array.isArray(run.metrics?.proposals) ? run.metrics.proposals.length : 0;

  return (
    <div className="backtest-learning">
      <strong>策略学习复盘 · {proposals} 条建议</strong>
      <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 11 }}>
        {summary || '已完成学习复盘，等待人工确认。'}
      </Typography.Paragraph>
    </div>
  );
}

function BacktestSummary({ runs }: { runs: BacktestRun[] }) {
  const candidates = runs.filter(
    (item) => item.strategy_id !== 'learning_review' && metricNumber(item, 'total_return') !== null,
  );
  const pending = runs.filter((item) => !isTerminal(item.status));
  const best = [...candidates].sort(
    (a, b) => (backtestScore(b) ?? -Infinity) - (backtestScore(a) ?? -Infinity),
  )[0];
  const safest = [...candidates].sort(
    (a, b) =>
      (metricNumber(a, 'max_drawdown') ?? Infinity) - (metricNumber(b, 'max_drawdown') ?? Infinity),
  )[0];

  const items = [
    {
      label: '本轮候选',
      value: `${candidates.length} 组`,
      note: '含可比较数值结果',
      highlight: false,
    },
    {
      label: '待人工确认',
      value: `${pending.length} 组`,
      note: '确认后下一轮 monitor 生效',
      highlight: false,
    },
    {
      label: '收益 / 回撤优选',
      value: best ? signedPct(metricNumber(best, 'total_return')) : '--',
      note: best ? strategyName(best.strategy_id) : '等待回测结果',
      highlight: true,
      valueClass: best ? toneClass(metricNumber(best, 'total_return')) : '',
    },
    {
      label: '最低最大回撤',
      value: safest ? drawdownPct(metricNumber(safest, 'max_drawdown')) : '--',
      note: safest ? strategyName(safest.strategy_id) : '等待回测结果',
      highlight: false,
      valueClass: 'risk',
    },
  ];

  return (
    <Row gutter={[1, 1]} className="backtest-summary">
      {items.map((item) => (
        <Col xs={12} sm={6} key={item.label}>
          <div className={`backtest-summary-item${item.highlight ? ' best' : ''}`}>
            <span className="backtest-summary-label">{item.label}</span>
            <strong className={`backtest-summary-value ${item.valueClass ?? ''}`}>{item.value}</strong>
            <span className="backtest-summary-note">{item.note}</span>
          </div>
        </Col>
      ))}
    </Row>
  );
}

export function BacktestPanel() {
  const queryClient = useQueryClient();
  const announce = useUiStore((s) => s.announce);
  const [selectedRowKeys, setSelectedRowKeys] = useState<number[]>([]);

  const { data, isLoading } = useQuery({
    queryKey: ['backtests'],
    queryFn: ({ signal }) => fetchBacktests(signal),
  });

  const runs = data?.backtest_runs ?? [];

  const pendingIds = useMemo(
    () => runs.filter((run) => !isTerminal(run.status)).map((run) => run.id),
    [runs],
  );

  const allPendingSelected =
    pendingIds.length > 0 && pendingIds.every((id) => selectedRowKeys.includes(id));
  const someSelected = selectedRowKeys.length > 0 && !allPendingSelected;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['backtests'] });
    void queryClient.invalidateQueries({ queryKey: ['overview'] });
  };

  const runMutation = useMutation({
    mutationFn: () => runBacktest(),
    onSuccess: () => {
      invalidate();
      announce('回测已完成，候选参数等待人工确认。');
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '立即回测失败。');
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (ids: number[]) => confirmBacktests(ids),
    onSuccess: (result) => {
      invalidate();
      setSelectedRowKeys([]);
      const rejected = result.rejected
        ? ` 同组合其余 ${result.rejected} 条候选已淘汰。`
        : '';
      announce(
        `已排队 ${result.queued ?? 0} 条回测，${result.reviewed ?? 0} 条学习复盘已确认。${rejected}`,
      );
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '回测确认失败，请重试。');
    },
  });

  const handleConfirmSelected = () => {
    if (!selectedRowKeys.length) {
      announce('请先选择需要确认的回测记录。');
      return;
    }
    confirmMutation.mutate(selectedRowKeys);
  };

  const columns: ColumnsType<BacktestRun> = [
    {
      title: '策略',
      key: 'strategy',
      width: 180,
      render: (_, run) => (
        <div>
          <div style={{ fontWeight: 600 }}>{strategyName(run.strategy_id)}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {run.strategy_id} · {String(run.created_at || '').slice(0, 16)}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '参数',
      key: 'parameters',
      width: 220,
      render: (_, run) => (
        <Space size={[4, 4]} wrap>
          {Object.entries(run.parameters || {}).map(([key, value]) => (
            <Tag key={key} className="param-pill">
              {key}：{value}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '回测结果',
      key: 'metrics',
      render: (_, run) =>
        run.strategy_id === 'learning_review' ? (
          <BacktestLearning run={run} />
        ) : (
          <BacktestMetrics run={run} />
        ),
    },
    {
      title: '状态',
      key: 'status',
      width: 110,
      render: (_, run) => (
        <div>
          <span className="kicker">状态</span>
          <div style={{ fontWeight: 650, color: 'var(--blue-dark)', fontSize: 12 }}>
            {run.status || '待人工确认'}
          </div>
        </div>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      align: 'right',
      render: (_, run) => {
        const terminal = isTerminal(run.status);
        const label =
          terminal && run.status === '已拒绝'
            ? '已淘汰'
            : terminal
              ? run.status
              : '确认';
        return (
          <Button
            size="small"
            disabled={terminal || confirmMutation.isPending}
            loading={confirmMutation.isPending}
            onClick={() => confirmMutation.mutate([run.id])}
          >
            {label}
          </Button>
        );
      },
    },
  ];

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <Card
      title="回测记录"
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          每日收盘自动生成候选；参数只在人工确认后才可进入下一轮评估
        </Typography.Text>
      }
    >
      <div className="backtest-toolbar">
        <Space wrap align="center">
          <Checkbox
            checked={allPendingSelected}
            indeterminate={someSelected}
            disabled={!pendingIds.length}
            onChange={(event) => setSelectedRowKeys(event.target.checked ? pendingIds : [])}
          >
            全选待确认
          </Checkbox>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            收益率、回撤等指标来自已保存的回测结果。
          </Typography.Text>
        </Space>
        <Space wrap>
          <Button
            icon={<PlayCircleOutlined />}
            loading={runMutation.isPending}
            disabled={runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            立即回测
          </Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            loading={confirmMutation.isPending}
            disabled={confirmMutation.isPending}
            onClick={handleConfirmSelected}
          >
            确认所选
          </Button>
        </Space>
      </div>

      <BacktestSummary runs={runs} />

      {!runs.length ? (
        <Empty
          description="暂无回测记录。运行参数优化后，候选策略会在这里等待人工确认。"
          style={{ padding: '32px 0' }}
        />
      ) : (
        <Table<BacktestRun>
          rowKey="id"
          columns={columns}
          dataSource={runs}
          pagination={false}
          style={{ marginTop: 16 }}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys as number[]),
            getCheckboxProps: (record) => ({ disabled: isTerminal(record.status) }),
          }}
        />
      )}
    </Card>
  );
}
