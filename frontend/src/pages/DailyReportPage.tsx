import { Typography } from 'antd';

import { ReportArchive } from '@/components/reports/ReportArchive';

export default function DailyReportPage() {
  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        日报归档
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        按交易日回看策略执行
      </Typography.Paragraph>
      <ReportArchive />
    </>
  );
}
