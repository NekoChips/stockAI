import { Card, List, Tag, Typography } from 'antd';
import type { OverviewPayload } from '@/types/dashboard';
import { fmtMoney } from '@/utils/format';

interface RecentActivityProps {
  data: OverviewPayload;
}

export function RecentActivity({ data }: RecentActivityProps) {
  const fills = (data.recent_fills ?? []).slice(-3).reverse();

  return (
    <Card title="最近模拟成交">
      <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 16, fontSize: 13 }}>
        成交记录仅用于模拟盘复盘
      </Typography.Paragraph>
      {fills.length ? (
        <List
          dataSource={fills}
          renderItem={(item) => {
            const isSell = item.direction === '卖出' || item.direction === '减仓';
            return (
              <List.Item>
                <List.Item.Meta
                  title={
                    <>
                      <Tag color={isSell ? 'green' : 'default'}>{item.direction}</Tag>
                      <Typography.Text strong>
                        {item.symbol} · {item.quantity} 份
                      </Typography.Text>
                    </>
                  }
                  description={`成交价 ${fmtMoney(item.price)} · 手续费 ${fmtMoney(item.fee)}`}
                />
              </List.Item>
            );
          }}
        />
      ) : (
        <div>
          <Tag>暂无成交</Tag>
          <Typography.Text strong style={{ display: 'block', marginTop: 8 }}>
            今天还没有模拟成交
          </Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            策略将继续观察数据、信号与风险条件。
          </Typography.Paragraph>
        </div>
      )}
    </Card>
  );
}
