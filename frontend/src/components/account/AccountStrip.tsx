import { Col, Row, Statistic, Typography } from 'antd';
import type { OverviewPayload } from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';

interface AccountStripProps {
  data: OverviewPayload;
  dataUpdatedAt?: number;
}

export function AccountStrip({ data, dataUpdatedAt }: AccountStripProps) {
  const portfolio = data.portfolio ?? {};
  const asset = Number(portfolio.total_asset ?? 0);
  const market = Number(portfolio.total_market_value ?? 0);
  const daily =
    data.daily_return ??
    (data.period_returns as { daily?: { return_rate?: unknown }[] } | undefined)?.daily?.at(-1)
      ?.return_rate ??
    0;
  const pending = Number(
    data.pending_backtest_count ??
      (data.backtest_runs as { status?: string }[] | undefined)?.filter(
        (item) => !['已确认', '已应用', '已拒绝'].includes(item.status ?? ''),
      ).length ??
      0,
  );
  const actionCount = (data.today_decisions ?? []).filter(
    (item) => !['观望', '持有'].includes(item.direction),
  ).length;
  const fillCount = (data.recent_fills ?? []).length;
  const positionCount = (portfolio.positions ?? []).length;
  const updated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    : '--:--:--';

  return (
    <div
      style={{
        border: '1px solid #e6edf6',
        borderRadius: 8,
        overflow: 'hidden',
        background: '#fff',
      }}
    >
      <Row wrap={false}>
        <Col flex="1 1 310px" style={{ background: 'linear-gradient(105deg,#fff 0%,#f5f9ff 100%)' }}>
          <div style={{ padding: '18px 16px', borderRight: '1px solid #e6edf6' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
              模拟盘总资产
            </Typography.Text>
            <div className="tabular" style={{ marginTop: 3, fontSize: 32, fontWeight: 720, lineHeight: 1 }}>
              {fmtMoney(asset)}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', marginTop: 10, fontSize: 13 }}>
              <Typography.Text type="secondary">现金 {fmtMoney(portfolio.cash)} 元</Typography.Text>
              <Typography.Text type="secondary">仓位 {fmtPct(asset ? market / asset : 0)}</Typography.Text>
              <Typography.Text type="secondary">持仓 {positionCount} 个</Typography.Text>
            </div>
          </div>
        </Col>
        <Col flex="0 0 auto">
          <Row wrap={false}>
            <Col>
              <div style={{ padding: '18px 16px', borderRight: '1px solid #e6edf6', minWidth: 118 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  今日收益率
                </Typography.Text>
                <div className={`tabular ${toneClass(daily)}`} style={{ marginTop: 7, fontSize: 19, fontWeight: 700 }}>
                  {fmtPct(daily)}
                </div>
              </div>
            </Col>
            <Col>
              <div style={{ padding: '18px 16px', borderRight: '1px solid #e6edf6', minWidth: 118 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  今日决策
                </Typography.Text>
                <div className="tabular" style={{ marginTop: 7, fontSize: 19, fontWeight: 700 }}>
                  {actionCount ? `${actionCount} 条` : '观望中'}
                </div>
              </div>
            </Col>
            <Col>
              <div style={{ padding: '18px 16px', borderRight: '1px solid #e6edf6', minWidth: 118 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  最近成交
                </Typography.Text>
                <Statistic value={fillCount} suffix="笔" valueStyle={{ fontSize: 19, fontWeight: 700 }} />
              </div>
            </Col>
            <Col>
              <div style={{ padding: '18px 16px', borderRight: '1px solid #e6edf6', minWidth: 118 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  待确认回测
                </Typography.Text>
                <Statistic value={pending} suffix="组" valueStyle={{ fontSize: 19, fontWeight: 700 }} />
              </div>
            </Col>
            <Col>
              <div style={{ padding: '18px 16px', minWidth: 118 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  最后刷新
                </Typography.Text>
                <div className="tabular" style={{ marginTop: 7, fontSize: 19, fontWeight: 700 }}>
                  {updated}
                </div>
              </div>
            </Col>
          </Row>
        </Col>
      </Row>
    </div>
  );
}
