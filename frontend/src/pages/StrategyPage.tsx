import { Typography } from 'antd';

import { StrategyWorkspace } from '@/components/strategy/StrategyWorkspace';

export default function StrategyPage() {
  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        策略中心
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        先切换组合，再调整成员和参数；确认后下一轮 monitor 生效
      </Typography.Paragraph>
      <StrategyWorkspace />
    </>
  );
}
