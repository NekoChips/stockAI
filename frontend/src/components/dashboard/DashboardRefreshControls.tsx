import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Space, Tooltip, Typography } from 'antd';
import { CheckCircleOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons';

export const OVERVIEW_POLL_MS = 30_000;

export const DASHBOARD_QUERY_KEYS = [
  ['overview'],
  ['performance'],
  ['calendar'],
  ['decision-events'],
] as const;

export function invalidateDashboardQueries(queryClient: ReturnType<typeof useQueryClient>) {
  for (const queryKey of DASHBOARD_QUERY_KEYS) {
    void queryClient.invalidateQueries({ queryKey: [...queryKey] });
  }
}

type RefreshPhase = 'idle' | 'fetching' | 'justUpdated';

interface DashboardRefreshControlsProps {
  isFetching: boolean;
  isLoading: boolean;
  dataUpdatedAt: number;
  pollIntervalMs?: number;
}

function formatCountdown(seconds: number): string {
  return `${Math.max(0, seconds)}s`;
}

function formatClock(ts: number): string {
  if (!ts) return '--:--:--';
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function DashboardRefreshControls({
  isFetching,
  isLoading,
  dataUpdatedAt,
  pollIntervalMs = OVERVIEW_POLL_MS,
}: DashboardRefreshControlsProps) {
  const queryClient = useQueryClient();
  const [now, setNow] = useState(() => Date.now());
  const [phase, setPhase] = useState<RefreshPhase>('idle');
  const wasFetching = useRef(false);
  const backgroundFetching = isFetching && !isLoading;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (backgroundFetching) {
      wasFetching.current = true;
      setPhase('fetching');
      return;
    }
    if (wasFetching.current) {
      wasFetching.current = false;
      setPhase('justUpdated');
      const timer = window.setTimeout(() => setPhase('idle'), 1500);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [backgroundFetching]);

  const secondsLeft = dataUpdatedAt
    ? Math.ceil((dataUpdatedAt + pollIntervalMs - now) / 1000)
    : Math.ceil(pollIntervalMs / 1000);

  const busy = phase === 'fetching' || backgroundFetching;
  const statusIcon = busy ? (
    <SyncOutlined spin style={{ color: 'var(--brand)' }} />
  ) : phase === 'justUpdated' ? (
    <CheckCircleOutlined style={{ color: 'var(--loss)' }} />
  ) : (
    <SyncOutlined style={{ color: 'var(--subtle)' }} />
  );

  const tooltip = busy
    ? '正在更新看板…'
    : phase === 'justUpdated'
      ? `已更新 ${formatClock(dataUpdatedAt)}`
      : `自动刷新 · ${formatCountdown(secondsLeft)} 后`;

  return (
    <Space size={10}>
      <Tooltip title={tooltip}>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            minWidth: 64,
            fontVariantNumeric: 'tabular-nums',
            cursor: 'default',
          }}
          aria-live="polite"
        >
          {statusIcon}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {busy ? '更新中' : phase === 'justUpdated' ? '已更新' : formatCountdown(secondsLeft)}
          </Typography.Text>
        </span>
      </Tooltip>
      <Button
        size="small"
        icon={<ReloadOutlined />}
        loading={busy}
        onClick={() => invalidateDashboardQueries(queryClient)}
      >
        刷新数据
      </Button>
    </Space>
  );
}
