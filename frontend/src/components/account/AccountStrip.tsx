import { Statistic, Typography } from 'antd';
import type { OverviewPayload } from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';

export type AccountStripView = 'live' | 'review';

interface AccountStripProps {
  data: OverviewPayload;
  view: AccountStripView;
  dataUpdatedAt?: number;
}

export function AccountStrip({ data, view, dataUpdatedAt }: AccountStripProps) {
  const portfolio = data.portfolio ?? {};
  const asset = Number(portfolio.total_asset ?? 0);
  const market = Number(portfolio.total_market_value ?? 0);
  const daily =
    data.daily_return ??
    (data.period_returns as { daily?: { return_rate?: unknown }[] } | undefined)?.daily?.at(-1)
      ?.return_rate ??
    0;
  const actionCount = (data.today_decisions ?? []).filter(
    (item) => !['观望', '持有'].includes(item.direction),
  ).length;
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
    <div className="account-strip">
      <div className="account-strip-layout">
        <div className="account-strip-hero">
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
            模拟盘总资产
          </Typography.Text>
          <div className="tabular" style={{ marginTop: 3, fontSize: 32, fontWeight: 720, lineHeight: 1 }}>
            {fmtMoney(asset)}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px', marginTop: 10, fontSize: 13 }}>
            <Typography.Text type="secondary">现金 {fmtMoney(portfolio.cash)} 元</Typography.Text>
            <Typography.Text type="secondary">仓位 {fmtPct(asset ? market / asset : 0)}</Typography.Text>
            {view === 'review' ? (
              <Typography.Text type="secondary">持仓市值 {fmtMoney(market)} 元</Typography.Text>
            ) : null}
          </div>
        </div>

        <div className="account-strip-kpis">
          <div className="account-strip-kpi">
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
              日盈亏
            </Typography.Text>
            <div className={`tabular ${toneClass(daily)}`} style={{ marginTop: 7, fontSize: 19, fontWeight: 700 }}>
              {fmtPct(daily)}
            </div>
          </div>
          {view === 'live' ? (
            <>
              <div className="account-strip-kpi">
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  持仓数
                </Typography.Text>
                <Statistic
                  value={positionCount}
                  suffix="个"
                  valueStyle={{ fontSize: 19, fontWeight: 700 }}
                />
              </div>
              <div className="account-strip-kpi">
                <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
                  有效决策
                </Typography.Text>
                <div className="tabular" style={{ marginTop: 7, fontSize: 19, fontWeight: 700 }}>
                  {actionCount ? `${actionCount} 条` : '观望中'}
                </div>
              </div>
            </>
          ) : null}
          <div className="account-strip-kpi">
            <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 650 }}>
              更新时间
            </Typography.Text>
            <div className="tabular" style={{ marginTop: 7, fontSize: 19, fontWeight: 700 }}>
              {updated}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
