import { Typography } from 'antd';

import { BacktestPanel } from '@/components/backtest/BacktestPanel';

export default function BacktestPage() {
  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        回测记录
      </Typography.Title>
      <BacktestPanel />
    </>
  );
}
