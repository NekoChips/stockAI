import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, Card, Popconfirm, Space, Switch, Table, Typography } from 'antd';
import { DeleteOutlined, PauseOutlined, PlayCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import { removeWatchlistItem, setWatchlistTrading } from '@/api/watchlist';
import { useUiStore } from '@/stores/uiStore';
import type { MarketQuote, OverviewPayload, PortfolioPosition, WatchlistItem } from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';

interface PositionsTableProps {
  data: OverviewPayload;
  onAddInstrument?: () => void;
}

interface PositionRow {
  key: string;
  symbol: string;
  name: string;
  sublabel: string;
  quantity: string;
  available: string;
  averageCost: string;
  latest: string;
  changeHtml: ReactNode;
  marketValue: string;
  floating: number;
  floatingLabel: string;
  status: string;
  isWatch: boolean;
  tradingEnabled?: boolean;
}

function quotePrice(quote: MarketQuote | undefined, fallback = '--'): string {
  return quote?.latest_price == null ? fallback : fmtMoney(quote.latest_price);
}

function quoteChangeNode(quote: MarketQuote | undefined): ReactNode {
  if (quote?.change_percent == null) return '--';
  const pct = Number(quote.change_percent) / 100;
  return <span className={toneClass(pct)}>{fmtPct(pct)}</span>;
}

export function PositionsTable({ data, onAddInstrument }: PositionsTableProps) {
  const queryClient = useQueryClient();
  const announce = useUiStore((s) => s.announce);

  const portfolio = data.portfolio ?? {};
  const watchlist = Array.isArray(data.watchlist) ? data.watchlist : [];
  const names = Object.fromEntries(watchlist.map((item) => [item.symbol, item.name]));
  const quotes = data.market_quotes ?? {};
  const asset = Number(portfolio.total_asset ?? 0);
  const market = Number(portfolio.total_market_value ?? 0);

  const patchOverview = (dashboard: OverviewPayload) => {
    queryClient.setQueryData(['overview'], dashboard);
  };

  const toggleMutation = useMutation({
    mutationFn: ({ symbol, enabled }: { symbol: string; enabled: boolean }) =>
      setWatchlistTrading(symbol, enabled),
    onSuccess: (payload, { symbol, enabled }) => {
      patchOverview(payload.dashboard);
      announce(`${symbol}${enabled ? ' 已启用交易。' : ' 已停用交易。'}`);
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '交易权限更新失败。');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => removeWatchlistItem(symbol),
    onSuccess: (payload, symbol) => {
      patchOverview(payload.dashboard);
      announce(`${symbol} 已移出观察池。`);
    },
    onError: (error) => {
      announce(
        error instanceof Error && error.message
          ? error.message
          : '移除失败：持仓中的标的不能移除。',
      );
    },
  });

  const positionRows = useMemo(() => {
    const rows = [...(portfolio.positions ?? [])].sort(
      (a, b) => Number(b.market_value ?? 0) - Number(a.market_value ?? 0),
    );

    return rows.map((item: PortfolioPosition): PositionRow => {
      const quote = quotes[item.symbol];
      const name = names[item.symbol] || quote?.name || item.symbol;
      const latest = Number(quote?.latest_price ?? item.last_price ?? 0);
      const qty = Number(item.quantity ?? 0);
      const marketValue = latest * qty;
      const floating = marketValue - Number(item.average_cost ?? 0) * qty;

      return {
        key: item.symbol,
        symbol: item.symbol,
        name,
        sublabel: `${item.symbol} · 沪深模拟盘`,
        quantity: String(item.quantity ?? '--'),
        available: String(item.available_quantity ?? '--'),
        averageCost: fmtMoney(item.average_cost),
        latest: fmtMoney(latest),
        changeHtml: quoteChangeNode(quote),
        marketValue: fmtMoney(marketValue),
        floating,
        floatingLabel: fmtMoney(floating),
        status: '持仓中',
        isWatch: false,
      };
    });
  }, [portfolio.positions, names, quotes]);

  const watchRows = useMemo(() => {
    const held = new Set((portfolio.positions ?? []).map((p) => p.symbol));
    return watchlist
      .filter((item: WatchlistItem) => !held.has(item.symbol))
      .map((item: WatchlistItem): PositionRow => {
        const quote = quotes[item.symbol];
        const name = item.name || quote?.name || item.symbol;
        const enabled = Boolean(item.trading_enabled);

        return {
          key: `watch-${item.symbol}`,
          symbol: item.symbol,
          name,
          sublabel: `${item.symbol} · ${enabled ? '交易已启用' : '观察池'}`,
          quantity: '--',
          available: '--',
          averageCost: '--',
          latest: quotePrice(quote),
          changeHtml: quoteChangeNode(quote),
          marketValue: '--',
          floating: 0,
          floatingLabel: enabled ? '等待信号' : '等待人工启用',
          status: '--',
          isWatch: true,
          tradingEnabled: enabled,
        };
      });
  }, [watchlist, portfolio.positions, quotes]);

  const allRows = [...positionRows, ...watchRows];
  const meta = positionRows.length
    ? `${positionRows.length} 个持仓`
    : `观察池 ${watchlist.length} 只`;

  const columns: ColumnsType<PositionRow> = [
    {
      title: '证券',
      dataIndex: 'name',
      fixed: 'left',
      render: (_, row) => (
        <div>
          <Link to={`/instruments/${row.symbol}`}>{row.name}</Link>
          <Typography.Text type="secondary" className="tabular" style={{ display: 'block', fontSize: 11 }}>
            {row.sublabel}
          </Typography.Text>
        </div>
      ),
    },
    { title: '持仓', dataIndex: 'quantity', align: 'right', className: 'tabular' },
    { title: '可卖', dataIndex: 'available', align: 'right', className: 'tabular' },
    { title: '成本', dataIndex: 'averageCost', align: 'right', className: 'tabular' },
    { title: '现价', dataIndex: 'latest', align: 'right', className: 'tabular' },
    { title: '今日涨跌', dataIndex: 'changeHtml', align: 'right' },
    { title: '市值', dataIndex: 'marketValue', align: 'right', className: 'tabular' },
    {
      title: '浮动盈亏',
      dataIndex: 'floatingLabel',
      align: 'right',
      className: 'tabular',
      render: (value, row) =>
        row.isWatch ? (
          <Typography.Text type="secondary" style={{ fontWeight: 700, fontSize: 12 }}>
            {value}
          </Typography.Text>
        ) : (
          <span className={toneClass(row.floating)}>{value}</span>
        ),
    },
    {
      title: '操作',
      dataIndex: 'status',
      align: 'right',
      render: (_, row) =>
        row.isWatch ? (
          <Space size={4}>
            <Switch
              size="small"
              checked={row.tradingEnabled}
              loading={toggleMutation.isPending && toggleMutation.variables?.symbol === row.symbol}
              checkedChildren={<PlayCircleOutlined />}
              unCheckedChildren={<PauseOutlined />}
              aria-label={`${row.tradingEnabled ? '停用' : '启用'} ${row.name} 的交易`}
              onChange={(enabled) => toggleMutation.mutate({ symbol: row.symbol, enabled })}
            />
            <Popconfirm
              title={`确认将 ${row.symbol} 移出观察池吗？`}
              okText="确认"
              cancelText="取消"
              onConfirm={() => removeMutation.mutate(row.symbol)}
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={removeMutation.isPending && removeMutation.variables === row.symbol}
                aria-label={`移除 ${row.name}`}
              />
            </Popconfirm>
          </Space>
        ) : (
          <Typography.Text type="secondary">{row.status}</Typography.Text>
        ),
    },
  ];

  return (
    <Card
      title="实时持仓"
      extra={
        <Space>
          <Typography.Text type="secondary">{meta}</Typography.Text>
          {onAddInstrument ? (
            <Button type="primary" size="small" icon={<PlusOutlined />} onClick={onAddInstrument}>
              添加标的
            </Button>
          ) : null}
        </Space>
      }
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ padding: '0 20px 14px' }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13 }}>
          按当前市值与浮动盈亏审视敞口
        </Typography.Paragraph>
      </div>
      <Table<PositionRow>
        size="small"
        columns={columns}
        dataSource={allRows}
        pagination={false}
        scroll={{ x: 960, y: 360 }}
        rowClassName={(row) => (row.isWatch ? 'watch-row' : '')}
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          borderTop: '1px solid #edf1f6',
          background: '#fbfdff',
        }}
      >
        <div style={{ padding: '11px 14px', borderRight: '1px solid #edf1f6' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
            当前仓位
          </Typography.Text>
          <div className="tabular" style={{ marginTop: 2, fontWeight: 650, fontSize: 13 }}>
            {fmtPct(asset ? market / asset : 0)}
          </div>
        </div>
        <div style={{ padding: '11px 14px', borderRight: '1px solid #edf1f6' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
            可用资金
          </Typography.Text>
          <div className="tabular" style={{ marginTop: 2, fontWeight: 650, fontSize: 13 }}>
            {fmtMoney(portfolio.cash)} 元
          </div>
        </div>
        <div style={{ padding: '11px 14px' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
            执行状态
          </Typography.Text>
          <div className="tabular" style={{ marginTop: 2, fontWeight: 650, fontSize: 13 }}>
            {positionRows.length ? '持仓跟踪中' : '等待建仓信号'}
          </div>
        </div>
      </div>
    </Card>
  );
}
