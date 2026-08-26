import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, DatePicker, Segmented, Spin, Typography } from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

import { fetchCalendar } from '@/api/dashboard';
import type { CalendarPayload, ProfitCalendarCell } from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';
import { useUiStore } from '@/stores/uiStore';

dayjs.locale('zh-cn');

type CalendarMode = 'monthly' | 'yearly';
type CalendarValueMode = 'amount' | 'rate';

function calendarOptions(data: CalendarPayload, mode: CalendarMode): string[] {
  const rows = data.profit_calendar?.daily ?? [];
  const first = rows[0]?.period ?? '2026-01-01';
  const last = rows.at(-1)?.period ?? first;
  const startYear = Number(first.slice(0, 4));
  const endYear = Number(last.slice(0, 4));
  if (mode === 'yearly') {
    return Array.from({ length: endYear - startYear + 1 }, (_, index) => String(startYear + index));
  }
  const [startY, startM] = first.slice(0, 7).split('-').map(Number);
  const [endY, endM] = last.slice(0, 7).split('-').map(Number);
  const result: string[] = [];
  for (let year = startY; year <= endY; year++) {
    for (
      let month = year === startY ? startM : 1;
      month <= (year === endY ? endM : 12);
      month++
    ) {
      result.push(`${year}-${String(month).padStart(2, '0')}`);
    }
  }
  return result;
}

function formatCellValue(item: ProfitCalendarCell, valueMode: CalendarValueMode): string {
  return valueMode === 'amount' ? fmtMoney(item.pnl) : fmtPct(item.return_rate);
}

function MonthGrid({
  data,
  period,
  valueMode,
  onToggleValue,
}: {
  data: CalendarPayload;
  period: string;
  valueMode: CalendarValueMode;
  onToggleValue: () => void;
}) {
  const rows = data.profit_calendar?.daily ?? [];
  const monthly =
    (data.profit_calendar?.monthly ?? []).find((item) => item.period === period) ??
    ({ pnl: 0, return_rate: 0 } as ProfitCalendarCell);
  const [year, month] = period.split('-').map(Number);
  const byDay = Object.fromEntries(
    rows
      .filter((item) => item.period.startsWith(period))
      .map((item) => [Number(item.period.slice(8, 10)), item]),
  );
  const first = new Date(year, month - 1, 1);
  const days = new Date(year, month, 0).getDate();
  const leading = Array.from({ length: first.getDay() }, (_, index) => (
    <div key={`blank-lead-${index}`} className="calendar-cell blank" aria-hidden="true" />
  ));
  const cells = Array.from({ length: days }, (_, index) => {
    const day = index + 1;
    const item = byDay[day] ?? ({ pnl: 0, return_rate: 0 } as ProfitCalendarCell);
    const value = formatCellValue(item, valueMode);
    const state = Number(item.pnl) > 0 ? 'win' : Number(item.pnl) < 0 ? 'loss' : '';
    return (
      <div key={day} className={`calendar-cell ${state}`}>
        <div className="calendar-day">{String(day).padStart(2, '0')}</div>
        <div className={`calendar-pnl ${toneClass(item.pnl)}`}>{value}</div>
      </div>
    );
  });
  const trailingCount = (7 - ((first.getDay() + days) % 7)) % 7;
  const trailing = Array.from({ length: trailingCount }, (_, index) => (
    <div key={`blank-trail-${index}`} className="calendar-cell blank" aria-hidden="true" />
  ));

  return (
    <>
      <div className="calendar-total">
        <div>
          <span className="kicker">
            {month}月{valueMode === 'amount' ? '总收益' : '收益率'}
          </span>
          <strong className={toneClass(monthly.pnl)}>
            {formatCellValue(monthly, valueMode)}
          </strong>
        </div>
        <Button type="link" className="value-toggle" onClick={onToggleValue}>
          {valueMode === 'amount' ? '看收益率' : '看收益额'}
        </Button>
      </div>
      <div className="weekdays">
        {['日', '一', '二', '三', '四', '五', '六'].map((label) => (
          <div key={label}>{label}</div>
        ))}
      </div>
      <div className="calendar">
        {leading}
        {cells}
        {trailing}
      </div>
    </>
  );
}

function YearGrid({
  data,
  period,
  valueMode,
  onToggleValue,
}: {
  data: CalendarPayload;
  period: string;
  valueMode: CalendarValueMode;
  onToggleValue: () => void;
}) {
  const rows = data.profit_calendar?.monthly ?? [];
  const byMonth = Object.fromEntries(
    rows
      .filter((item) => item.period.startsWith(`${period}-`))
      .map((item) => [Number(item.period.slice(5, 7)), item]),
  );
  const total =
    (data.profit_calendar?.yearly ?? []).find((item) => item.period === period) ??
    ({ pnl: 0, return_rate: 0 } as ProfitCalendarCell);

  return (
    <>
      <div className="calendar-total">
        <div>
          <span className="kicker">
            {period}年{valueMode === 'amount' ? '总收益' : '收益率'}
          </span>
          <strong className={toneClass(total.pnl)}>{formatCellValue(total, valueMode)}</strong>
        </div>
        <Button type="link" className="value-toggle" onClick={onToggleValue}>
          {valueMode === 'amount' ? '看收益率' : '看收益额'}
        </Button>
      </div>
      <div className="year-grid">
        {Array.from({ length: 12 }, (_, index) => {
          const month = index + 1;
          const item = byMonth[month] ?? ({ pnl: 0, return_rate: 0 } as ProfitCalendarCell);
          const state = Number(item.pnl) > 0 ? 'win' : Number(item.pnl) < 0 ? 'loss' : '';
          const value = formatCellValue(item, valueMode);
          return (
            <div key={month} className={`year-cell ${state}`}>
              <span className="kicker">{month}月</span>
              <strong className={toneClass(item.pnl)}>{value}</strong>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function ProfitCalendar() {
  const setNotice = useUiStore((s) => s.setNotice);
  const [calendarMode, setCalendarMode] = useState<CalendarMode>('monthly');
  const [valueMode, setValueMode] = useState<CalendarValueMode>('amount');
  const [calendarPeriod, setCalendarPeriod] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['calendar'],
    queryFn: ({ signal }) => fetchCalendar(signal),
  });

  useEffect(() => {
    if (isError) {
      setNotice(
        error instanceof Error && error.message
          ? error.message
          : '盈亏日历读取失败，请稍后重试。',
      );
    }
  }, [isError, error, setNotice]);

  const options = useMemo(
    () => (data ? calendarOptions(data, calendarMode) : []),
    [data, calendarMode],
  );

  const period = useMemo(() => {
    if (!options.length) return calendarPeriod ?? '2026-01';
    if (!calendarPeriod || !options.includes(calendarPeriod)) return options.at(-1)!;
    return calendarPeriod;
  }, [options, calendarPeriod]);

  useEffect(() => {
    if (period !== calendarPeriod) setCalendarPeriod(period);
  }, [period, calendarPeriod]);

  const disabledDate = (current: Dayjs) => {
    if (!current || !options.length) return false;
    const key = calendarMode === 'yearly' ? current.format('YYYY') : current.format('YYYY-MM');
    return key < options[0] || key > options.at(-1)!;
  };

  const handlePeriodChange = (value: Dayjs | null) => {
    if (!value) return;
    setCalendarPeriod(
      calendarMode === 'yearly' ? value.format('YYYY') : value.format('YYYY-MM'),
    );
  };

  return (
    <Card title="盈亏日历" className="calendar-panel" styles={{ body: { paddingTop: 0 } }}>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 13 }}>
        无操作日期按 0 收益纳入统计
      </Typography.Paragraph>

      {isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : data ? (
        <div className="calendar-body">
          <div className="calendar-tools">
            <Segmented
              options={[
                { label: '年', value: 'yearly' as const },
                { label: '月', value: 'monthly' as const },
              ]}
              value={calendarMode}
              onChange={(value) => {
                setCalendarMode(value as CalendarMode);
                setCalendarPeriod(null);
              }}
            />
            <DatePicker
              picker={calendarMode === 'yearly' ? 'year' : 'month'}
              value={dayjs(`${period}${calendarMode === 'yearly' ? '-01-01' : '-01'}`)}
              allowClear={false}
              inputReadOnly
              format={calendarMode === 'yearly' ? 'YYYY年' : 'YYYY-MM'}
              disabledDate={disabledDate}
              onChange={handlePeriodChange}
            />
          </div>

          {calendarMode === 'yearly' ? (
            <YearGrid
              data={data}
              period={period}
              valueMode={valueMode}
              onToggleValue={() => setValueMode((m) => (m === 'amount' ? 'rate' : 'amount'))}
            />
          ) : (
            <MonthGrid
              data={data}
              period={period}
              valueMode={valueMode}
              onToggleValue={() => setValueMode((m) => (m === 'amount' ? 'rate' : 'amount'))}
            />
          )}
        </div>
      ) : (
        <Typography.Paragraph type="secondary">暂无日历数据。</Typography.Paragraph>
      )}
    </Card>
  );
}
