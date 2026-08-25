import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Col, Row, Spin, Typography } from 'antd';
import { fetchOverview } from '@/api/dashboard';
import { AccountStrip } from '@/components/account/AccountStrip';
import { RecentActivity } from '@/components/activity/RecentActivity';
import { DecisionTimeline } from '@/components/decisions/DecisionTimeline';
import { Leaderboard } from '@/components/leaderboard/Leaderboard';
import { PositionsTable } from '@/components/positions/PositionsTable';
import { useUiStore } from '@/stores/uiStore';

export default function DashboardPage() {
  const setNotice = useUiStore((s) => s.setNotice);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['overview'],
    queryFn: ({ signal }) => fetchOverview(signal),
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

  if (isLoading || !data) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        交易看板
      </Typography.Title>
      <AccountStrip data={data} />
      <Row gutter={[20, 20]} style={{ marginTop: 20 }}>
        <Col xs={24} lg={16}>
          <PositionsTable data={data} />
        </Col>
        <Col xs={24} lg={8}>
          <DecisionTimeline data={data} />
        </Col>
        <Col xs={24} lg={16}>
          <Leaderboard data={data} />
        </Col>
        <Col xs={24} lg={8}>
          <RecentActivity data={data} />
        </Col>
      </Row>
    </>
  );
}
