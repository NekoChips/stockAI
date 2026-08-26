import { useMemo, useState } from 'react';
import { Button, Card, Space, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { OverviewPayload, ProfitLeaderboardRow } from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';

interface LeaderboardProps {
  data: OverviewPayload;
}

type SortKey = 'profit_amount' | 'return_rate' | 'holding_days';

const SORT_CONTROLS: [SortKey, string][] = [
  ['profit_amount', '按盈亏金额'],
  ['return_rate', '按收益率'],
  ['holding_days', '按持仓天数'],
];

export function Leaderboard({ data }: LeaderboardProps) {
  const [sortKey, setSortKey] = useState<SortKey>('profit_amount');
  const [sortAsc, setSortAsc] = useState(false);

  const rows = useMemo(() => {
    const source = [...(data.profit_leaderboard ?? [])];
    return source.sort((left, right) => {
      const a = left[sortKey];
      const b = right[sortKey];
      const result =
        typeof a === 'string'
          ? String(a).localeCompare(String(b), 'zh-CN')
          : Number(a) - Number(b);
      return sortAsc ? result : -result;
    });
  }, [data.profit_leaderboard, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc((prev) => !prev);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const columns: ColumnsType<ProfitLeaderboardRow> = [
    {
      title: '证券',
      render: (_, row) => (
        <div>
          <Typography.Text strong>{row.name}</Typography.Text>
          <Typography.Text type="secondary" className="tabular" style={{ display: 'block', fontSize: 11 }}>
            {row.symbol}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '盈利金额',
      dataIndex: 'profit_amount',
      align: 'right',
      className: 'tabular',
      render: (value) => <span className={toneClass(value)}>{fmtMoney(value)}</span>,
    },
    {
      title: '持仓天数',
      dataIndex: 'holding_days',
      align: 'right',
      className: 'tabular',
      render: (value) => `${value} 天`,
    },
    {
      title: '收益率',
      dataIndex: 'return_rate',
      align: 'right',
      className: 'tabular',
      render: (value) => <span className={toneClass(value)}>{fmtPct(value)}</span>,
    },
  ];

  return (
    <Card title="盈亏排行榜" styles={{ body: { paddingTop: 0 } }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 13 }}>
        按证券维度排序，正数为盈利、负数为亏损
      </Typography.Paragraph>
      <Space wrap style={{ marginBottom: 12, paddingBottom: 12, borderBottom: '1px solid #edf1f6' }}>
        {SORT_CONTROLS.map(([key, label]) => (
          <Button
            key={key}
            size="small"
            type={sortKey === key ? 'primary' : 'default'}
            onClick={() => handleSort(key)}
          >
            {label}
            {sortKey === key ? (sortAsc ? ' ↑' : ' ↓') : ''}
          </Button>
        ))}
      </Space>
      <Table<ProfitLeaderboardRow>
        size="small"
        rowKey="symbol"
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '暂无可排名的盈亏记录。' }}
      />
    </Card>
  );
}
