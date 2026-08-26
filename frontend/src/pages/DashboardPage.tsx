import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Col, Empty, Row, Segmented, Spin, Typography } from 'antd';
import { createSearchParams, useNavigate, useSearchParams } from 'react-router-dom';

import { fetchOverview } from '@/api/dashboard';
import { AccountStrip } from '@/components/account/AccountStrip';
import { ProfitCalendar } from '@/components/calendar/ProfitCalendar';
import { AddInstrumentDrawer } from '@/components/watchlist/AddInstrumentDrawer';
import {
  DashboardRefreshControls,
  OVERVIEW_POLL_MS,
} from '@/components/dashboard/DashboardRefreshControls';
import {
  DeferredDashboardSection,
  DeferredSectionFallback,
} from '@/components/dashboard/DeferredDashboardSection';
import { useUiStore } from '@/stores/uiStore';

const PerformancePanel = lazy(() =>
  import('@/components/performance/PerformancePanel').then(({ PerformancePanel: Component }) => ({
    default: Component,
  })),
);
const PositionsTable = lazy(() =>
  import('@/components/positions/PositionsTable').then(({ PositionsTable: Component }) => ({
    default: Component,
  })),
);
const DecisionTimeline = lazy(() =>
  import('@/components/decisions/DecisionTimeline').then(({ DecisionTimeline: Component }) => ({
    default: Component,
  })),
);
const Leaderboard = lazy(() =>
  import('@/components/leaderboard/Leaderboard').then(({ Leaderboard: Component }) => ({
    default: Component,
  })),
);

type DashboardView = 'live' | 'review';

function DashboardHeader({
  view,
  onViewChange,
  isFetching,
  isLoading,
  dataUpdatedAt,
}: {
  view: DashboardView;
  onViewChange: (next: DashboardView) => void;
  isFetching: boolean;
  isLoading: boolean;
  dataUpdatedAt: number;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 12,
        marginBottom: 8,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          交易看板
        </Typography.Title>
        <Segmented
          className="dash-view-segmented"
          value={view}
          options={[
            { label: '实时', value: 'live' },
            { label: '复盘', value: 'review' },
          ]}
          onChange={(next) => onViewChange(String(next) === 'review' ? 'review' : 'live')}
        />
      </div>
      <DashboardRefreshControls
        isFetching={isFetching}
        isLoading={isLoading}
        dataUpdatedAt={dataUpdatedAt}
      />
    </div>
  );
}

function DashboardBodyShell({ children }: { children: ReactNode }) {
  return <div className="dash-enter">{children}</div>;
}

export default function DashboardPage() {
  const setNotice = useUiStore((s) => s.setNotice);
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchParams] = useSearchParams();
  const view: DashboardView = searchParams.get('view') === 'review' ? 'review' : 'live';

  const { data, isLoading, isFetching, isError, error, dataUpdatedAt } = useQuery({
    queryKey: ['overview'],
    queryFn: ({ signal }) => fetchOverview(signal),
    refetchInterval: OVERVIEW_POLL_MS,
  });

  useEffect(() => {
    if (isError) {
      const message =
        error instanceof Error && error.message
          ? error.message
          : '无法读取交易数据，请检查本地服务后重试。';
      setNotice(message);
    }
  }, [isError, error, setNotice]);

  const setView = (next: DashboardView) => {
    navigate(
      {
        pathname: '/',
        search: createSearchParams({ view: next }).toString(),
      },
      { replace: true },
    );
  };

  const header = (
    <DashboardHeader
      view={view}
      onViewChange={setView}
      isFetching={isFetching}
      isLoading={isLoading}
      dataUpdatedAt={dataUpdatedAt}
    />
  );

  if (isLoading) {
    return (
      <>
        {header}
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      </>
    );
  }

  if (!data) {
    return (
      <>
        {header}
        <Empty
          description={
            isError ? '无法加载看板数据，请使用顶部提示栏重试。' : '暂无看板数据。'
          }
          style={{ padding: '48px 0' }}
        />
      </>
    );
  }

  return (
    <>
      {header}

      <AccountStrip data={data} view={view} dataUpdatedAt={dataUpdatedAt} />

      <DashboardBodyShell>
        {view === 'live' ? (
          <Row gutter={[20, 20]} style={{ marginTop: 20 }}>
            <Col xs={24} lg={16}>
              <DeferredDashboardSection title="实时持仓" minHeight={520}>
                <Suspense fallback={<DeferredSectionFallback title="实时持仓" minHeight={520} />}>
                  <PositionsTable data={data} onAddInstrument={() => setDrawerOpen(true)} />
                </Suspense>
              </DeferredDashboardSection>
            </Col>
            <Col xs={24} lg={8}>
              <DeferredDashboardSection title="决策轨道" minHeight={520}>
                <Suspense fallback={<DeferredSectionFallback title="决策轨道" minHeight={520} />}>
                  <DecisionTimeline
                    watchlistCount={(data.watchlist ?? []).length}
                    onAddInstrument={() => setDrawerOpen(true)}
                    statusHint={
                      dataUpdatedAt
                        ? `更新于 ${new Date(dataUpdatedAt).toLocaleTimeString('zh-CN', {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                            hour12: false,
                          })}`
                        : undefined
                    }
                  />
                </Suspense>
              </DeferredDashboardSection>
            </Col>
          </Row>
        ) : (
          <>
            <Row gutter={[20, 20]} style={{ marginTop: 20 }}>
              <Col xs={24} lg={16}>
                <DeferredDashboardSection title="盈亏分析" minHeight={540} rootMargin="720px 0px">
                  <Suspense fallback={<DeferredSectionFallback title="盈亏分析" minHeight={540} />}>
                    <PerformancePanel />
                  </Suspense>
                </DeferredDashboardSection>
              </Col>
              <Col xs={24} lg={8}>
                <ProfitCalendar />
              </Col>
            </Row>

            <Row gutter={[20, 20]} style={{ marginTop: 20 }}>
              <Col xs={24}>
                <DeferredDashboardSection title="盈亏排行榜" minHeight={420}>
                  <Suspense fallback={<DeferredSectionFallback title="盈亏排行榜" minHeight={420} />}>
                    <Leaderboard data={data} />
                  </Suspense>
                </DeferredDashboardSection>
              </Col>
            </Row>
          </>
        )}
      </DashboardBodyShell>

      <AddInstrumentDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
