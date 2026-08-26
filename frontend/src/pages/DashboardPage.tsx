import { lazy, Suspense, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Col, Empty, Row, Spin, Typography } from 'antd';

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
const RecentActivity = lazy(() =>
  import('@/components/activity/RecentActivity').then(({ RecentActivity: Component }) => ({
    default: Component,
  })),
);

export default function DashboardPage() {
  const setNotice = useUiStore((s) => s.setNotice);
  const [drawerOpen, setDrawerOpen] = useState(false);

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

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!data) {
    return (
      <>
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
          <Typography.Title level={3} style={{ margin: 0 }}>
            交易看板
          </Typography.Title>
          <DashboardRefreshControls
            isFetching={isFetching}
            isLoading={isLoading}
            dataUpdatedAt={dataUpdatedAt}
          />
        </div>
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
        <Typography.Title level={3} style={{ margin: 0 }}>
          交易看板
        </Typography.Title>
        <DashboardRefreshControls
          isFetching={isFetching}
          isLoading={isLoading}
          dataUpdatedAt={dataUpdatedAt}
        />
      </div>

      <AccountStrip data={data} dataUpdatedAt={dataUpdatedAt} />

      <div className="dash-enter">
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
                <DecisionTimeline data={data} />
              </Suspense>
            </DeferredDashboardSection>
          </Col>
          <Col xs={24} lg={16}>
            <DeferredDashboardSection title="盈亏排行榜" minHeight={420}>
              <Suspense fallback={<DeferredSectionFallback title="盈亏排行榜" minHeight={420} />}>
                <Leaderboard data={data} />
              </Suspense>
            </DeferredDashboardSection>
          </Col>
          <Col xs={24} lg={8}>
            <DeferredDashboardSection title="最近模拟成交" minHeight={360}>
              <Suspense fallback={<DeferredSectionFallback title="最近模拟成交" minHeight={360} />}>
                <RecentActivity data={data} />
              </Suspense>
            </DeferredDashboardSection>
          </Col>
        </Row>
      </div>

      <AddInstrumentDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  );
}
