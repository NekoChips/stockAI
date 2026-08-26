import { useQuery } from '@tanstack/react-query';
import { Typography } from 'antd';

import { fetchOverview } from '@/api/dashboard';
import { RiskConfigPanel } from '@/components/risk/RiskConfigPanel';
import { StrategyWorkspace } from '@/components/strategy/StrategyWorkspace';
import type { OverviewPayload } from '@/types/dashboard';

export default function StrategyPage() {
  const { data: overview } = useQuery<OverviewPayload>({
    queryKey: ['overview'],
    queryFn: ({ signal }) => fetchOverview(signal),
  });

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        策略中心
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        先切换组合，再调整成员和参数；确认后下一轮 monitor 生效
      </Typography.Paragraph>
      <StrategyWorkspace />
      {overview?.risk_config ? (
        <div style={{ marginTop: 16 }}>
          <RiskConfigPanel risk={overview.risk_config} />
        </div>
      ) : null}
    </>
  );
}
