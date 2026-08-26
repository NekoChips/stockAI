import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, DatePicker, Segmented, Spin, Typography } from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

import { fetchPerformance } from '@/api/dashboard';
import type { PerformancePayload } from '@/types/dashboard';
import { fmtPct, toneClass } from '@/utils/format';
import { useUiStore } from '@/stores/uiStore';
import {
  buildChartPoints,
  buildChartState,
  chartLabel,
  drawLineChart,
  pointerToDayIndex,
  seriesMeta,
  tooltipRowsForDay,
  type ChartMode,
  type ChartState,
} from './lineChart';

dayjs.locale('zh-cn');

type RangeMode = 'yearly' | 'monthly' | 'custom';

function localDate(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function performanceRange(
  rangeMode: RangeMode,
  customStart: string | null,
  customEnd: string | null,
): { start: string; end: string } {
  const today = localDate();
  if (rangeMode === 'custom' && customStart && customEnd) {
    return { start: customStart, end: customEnd };
  }
  if (rangeMode === 'monthly') {
    return { start: `${today.slice(0, 8)}01`, end: today };
  }
  return { start: `${today.slice(0, 4)}-01-01`, end: today };
}

const RANGE_OPTIONS = [
  { label: '当年', value: 'yearly' as const },
  { label: '当月', value: 'monthly' as const },
  { label: '自定义', value: 'custom' as const },
];

const CHART_OPTIONS = [
  { label: '收益额', value: 'pnl' as const },
  { label: '收益率', value: 'return' as const },
  { label: '资产', value: 'asset' as const },
];

function BenchmarkOutperformance({ data }: { data: PerformancePayload }) {
  const rows = data.benchmark_outperformance ?? [];
  if (!rows.length) {
    return (
      <Typography.Paragraph type="secondary" className="outperformance-empty">
        暂无可比较的指数收益数据。
      </Typography.Paragraph>
    );
  }
  const maxDifference = Math.max(...rows.map((item) => Math.abs(Number(item.difference || 0))), 0.002);
  return (
    <div className="outperformance-grid" aria-label="相对大盘表现">
      {rows.map((item) => {
        const difference = Number(item.difference || 0);
        const state = difference > 0 ? '跑赢' : difference < 0 ? '跑输' : '持平';
        const stateTone = difference > 0 ? 'gain' : difference < 0 ? 'loss' : '';
        const width = Math.min(50, (Math.abs(difference) / maxDifference) * 50);
        const direction = difference >= 0 ? 'gain' : 'loss';
        return (
          <article key={item.series} className="outperformance-item">
            <div className="outperformance-top">
              <span className="kicker">{item.series}</span>
              <strong className={stateTone}>
                {state} {fmtPct(Math.abs(difference))}
              </strong>
            </div>
            <div className="outperformance-meta">
              <span>Agent {fmtPct(item.agent_return)}</span>
              <span>指数 {fmtPct(item.benchmark_return)}</span>
            </div>
            <div
              className="benchmark-progress"
              aria-label={`${item.series} ${state} ${fmtPct(Math.abs(difference))}`}
            >
              <span className={`benchmark-progress-fill ${direction}`} style={{ width: `${width}%` }} />
            </div>
          </article>
        );
      })}
    </div>
  );
}

export function PerformancePanel() {
  const announce = useUiStore((s) => s.announce);
  const setNotice = useUiStore((s) => s.setNotice);

  const [rangeMode, setRangeMode] = useState<RangeMode>('yearly');
  const [customStart, setCustomStart] = useState<string | null>(null);
  const [customEnd, setCustomEnd] = useState<string | null>(null);
  const [chartMode, setChartMode] = useState<ChartMode>('return');
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());
  const [focusIndex, setFocusIndex] = useState(-1);
  const [tooltip, setTooltip] = useState<{
    visible: boolean;
    left: number;
    top: number;
    day: string;
    rows: ReturnType<typeof tooltipRowsForDay>;
  }>({ visible: false, left: 0, top: 0, day: '', rows: [] });

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartStateRef = useRef<ChartState | null>(null);
  const allSeriesRef = useRef<string[]>([]);

  const range = useMemo(
    () => performanceRange(rangeMode, customStart, customEnd),
    [rangeMode, customStart, customEnd],
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['performance', range.start, range.end],
    queryFn: ({ signal }) =>
      fetchPerformance(
        { performance_start: range.start, performance_end: range.end },
        signal,
      ),
  });

  useEffect(() => {
    if (isError) {
      setNotice(
        error instanceof Error && error.message
          ? error.message
          : '盈亏分析读取失败，请稍后重试。',
      );
    }
  }, [isError, error, setNotice]);

  const allPoints = useMemo(
    () => (data ? buildChartPoints(data, chartMode) : []),
    [data, chartMode],
  );
  const legendNames = useMemo(
    () => [...new Set(allPoints.map((item) => item.series))],
    [allPoints],
  );

  useEffect(() => {
    setHiddenSeries((prev) => new Set([...prev].filter((name) => legendNames.includes(name))));
  }, [legendNames]);

  const visibleSeries = useMemo(() => {
    const visible = legendNames.filter((name) => !hiddenSeries.has(name));
    if (!visible.length) return new Set(legendNames);
    return new Set(visible);
  }, [legendNames, hiddenSeries]);

  const chartState = useMemo(() => {
    if (!allPoints.length) return null;
    allSeriesRef.current = legendNames;
    return buildChartState(allPoints, visibleSeries);
  }, [allPoints, visibleSeries, legendNames]);

  chartStateRef.current = chartState;

  useEffect(() => {
    if (chartState?.days.length) {
      setFocusIndex((prev) =>
        Math.min(Math.max(prev, 0), Math.max(chartState.days.length - 1, 0)),
      );
    }
  }, [chartState?.days.length]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawLineChart(canvas, chartStateRef.current, chartMode, focusIndex, allSeriesRef.current);
  }, [chartMode, focusIndex]);

  useEffect(() => {
    redraw();
  }, [redraw, chartState]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !window.ResizeObserver) return;
    const observer = new ResizeObserver(() => redraw());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [redraw]);

  const showChartPoint = useCallback(
    (index: number, pointerX: number | null = null, pointerY: number | null = null) => {
      const state = chartStateRef.current;
      if (!state?.days.length) return;
      const nextIndex = Math.max(0, Math.min(index, state.days.length - 1));
      setFocusIndex(nextIndex);
      const rows = tooltipRowsForDay(state, nextIndex);
      const day = state.days[nextIndex];
      const wrap = wrapRef.current;
      const width = wrap?.clientWidth ?? 0;
      const height = wrap?.clientHeight ?? 0;
      setTooltip({
        visible: true,
        left: Math.max(8, Math.min(pointerX ?? Math.round(width * 0.65), width - 188)),
        top: Math.max(8, Math.min(pointerY ?? 18, height - 110)),
        day,
        rows,
      });
      announce(`${day}，${rows.map((item) => `${item.series} ${chartLabel(item.value, chartMode)}`).join('；')}`);
    },
    [announce, chartMode],
  );

  const toggleSeries = (name: string) => {
    if (!hiddenSeries.has(name) && visibleSeries.size === 1) {
      announce('至少保留一条图表曲线。');
      return;
    }
    setHiddenSeries((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleRangeModeChange = (value: RangeMode) => {
    if (value === 'custom' && (!customStart || !customEnd)) {
      setCustomStart(range.start);
      setCustomEnd(range.end);
    }
    setRangeMode(value);
  };

  const handleRangePickerChange = (values: [Dayjs | null, Dayjs | null] | null) => {
    if (!values?.[0] || !values[1]) return;
    setCustomStart(values[0].format('YYYY-MM-DD'));
    setCustomEnd(values[1].format('YYYY-MM-DD'));
    setRangeMode('custom');
  };

  const rangeNote = data?.performance_range
    ? `${data.performance_range.start_date ?? '起始日'} 至 ${data.performance_range.end_date ?? '最新日'}，起始日收益率按 0 计算`
    : 'Agent 与主要指数同口径比较';

  const pending = (data?.benchmark_status ?? [])
    .filter((item) => item.state !== '可用')
    .map((item) => item.name);

  const lastDay = chartState?.days.at(-1) ?? '暂无数据';
  const summaryText = chartState?.points.length
    ? `已展示 ${chartState.names.join('、')}，最新日期 ${lastDay}。使用左右方向键读取每个交易日的精确数值。`
    : '暂无可展示的收益数据。';

  return (
    <Card
      title="盈亏分析"
      className="performance-panel"
      styles={{ body: { paddingTop: 0 } }}
      extra={
        <div className="performance-controls">
          <Segmented
            options={RANGE_OPTIONS}
            value={rangeMode}
            onChange={(value) => handleRangeModeChange(value as RangeMode)}
          />
          <DatePicker.RangePicker
            className="performance-range-picker"
            value={[dayjs(range.start), dayjs(range.end)]}
            allowClear={false}
            inputReadOnly
            format="YYYY-MM-DD"
            onChange={handleRangePickerChange}
          />
          <Segmented
            options={CHART_OPTIONS}
            value={chartMode}
            onChange={(value) => setChartMode(value as ChartMode)}
          />
        </div>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 13 }}>
        {rangeNote}
      </Typography.Paragraph>

      {isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : (
        <>
          <div className="chart-toolbar">
            <div className="chart-legend" aria-label="图表数据系列">
              {legendNames.map((name, index) => {
                const meta = seriesMeta(name, index);
                const active = !hiddenSeries.has(name);
                return (
                  <button
                    key={name}
                    type="button"
                    className="legend-toggle"
                    aria-pressed={active}
                    onClick={() => toggleSeries(name)}
                  >
                    <span
                      className={`series-swatch ${meta.dash.length ? 'dashed' : ''}`}
                      style={{ color: meta.color }}
                    />
                    {name}
                  </button>
                );
              })}
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {pending.length ? `待同步：${pending.join('、')}` : ''}
            </Typography.Text>
          </div>

          <div className="chart-wrap" ref={wrapRef}>
            <canvas
              ref={canvasRef}
              tabIndex={0}
              role="img"
              aria-label="收益趋势图。可使用左右方向键读取日期数据。"
              onPointerMove={(event) => {
                const canvas = canvasRef.current;
                if (!canvas || !chartStateRef.current?.days.length) return;
                const rect = canvas.getBoundingClientRect();
                const index = pointerToDayIndex(
                  event.clientX,
                  canvas,
                  chartStateRef.current.days.length,
                );
                showChartPoint(index, event.clientX - rect.left + 8, event.clientY - rect.top + 8);
              }}
              onPointerLeave={() => setTooltip((prev) => ({ ...prev, visible: false }))}
              onKeyDown={(event) => {
                const state = chartStateRef.current;
                if (!state?.days.length) return;
                if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                  event.preventDefault();
                  showChartPoint(focusIndex + (event.key === 'ArrowLeft' ? -1 : 1));
                }
                if (event.key === 'Home') {
                  event.preventDefault();
                  showChartPoint(0);
                }
                if (event.key === 'End') {
                  event.preventDefault();
                  showChartPoint(state.days.length - 1);
                }
              }}
            />
            <div
              className={`chart-tooltip${tooltip.visible ? ' visible' : ''}`}
              role="status"
              aria-live="polite"
              style={{ left: tooltip.left, top: tooltip.top }}
            >
              {tooltip.visible ? (
                <>
                  <strong>{tooltip.day}</strong>
                  {tooltip.rows.map((item) => (
                    <div key={item.series} className="chart-tooltip-row">
                      <span>{item.series}</span>
                      <b className={toneClass(item.value)}>{chartLabel(item.value, chartMode)}</b>
                    </div>
                  ))}
                </>
              ) : null}
            </div>
          </div>

          {data ? <BenchmarkOutperformance data={data} /> : null}

          <Typography.Paragraph type="secondary" className="chart-summary">
            {summaryText}
          </Typography.Paragraph>
        </>
      )}
    </Card>
  );
}
