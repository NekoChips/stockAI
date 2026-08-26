import type { PerformancePayload } from '@/types/dashboard';
import { chartPalette, cssVar } from '@/theme/cssVars';
import { fmtMoney, fmtPct } from '@/utils/format';

export type ChartMode = 'pnl' | 'return' | 'asset';

export interface ChartPoint {
  series: string;
  day: string;
  value: number;
}

export interface SeriesStyle {
  color: string;
  dash: number[];
  label: string;
}

export interface ChartState {
  points: ChartPoint[];
  days: string[];
  names: string[];
}

export const SERIES_STYLE: SeriesStyle[] = [
  { color: '#0F766E', dash: [], label: 'AI-Agent' },
  { color: '#a9640f', dash: [7, 4], label: 'AI-Agent' },
  { color: '#7b61a8', dash: [3, 3], label: 'AI-Agent' },
  { color: '#187a65', dash: [10, 4], label: 'AI-Agent' },
  { color: '#536b91', dash: [2, 4], label: 'AI-Agent' },
  { color: '#b5474d', dash: [8, 3, 2, 3], label: 'AI-Agent' },
];

export function chartLabel(value: number, chartMode: ChartMode): string {
  return chartMode === 'return' ? fmtPct(value) : fmtMoney(value);
}

export function seriesMeta(name: string, index: number): SeriesStyle & { label: string } {
  const base = { ...SERIES_STYLE[index % SERIES_STYLE.length], label: name };
  if (name === 'AI-Agent') {
    return { ...base, color: cssVar('--brand', base.color) };
  }
  return base;
}

export function buildChartPoints(data: PerformancePayload, chartMode: ChartMode): ChartPoint[] {
  if (chartMode === 'return') {
    return (data.benchmark_comparison ?? []).map((item) => ({
      series: item.series,
      day: item.day,
      value: Number(item.return_rate || 0),
    }));
  }
  const curve = data.equity_curve ?? [];
  const base = Number(curve[0]?.total_asset || 0);
  return curve.map((item) => ({
    series: chartMode === 'asset' ? 'AI-Agent 资产' : 'AI-Agent 收益',
    day: item.day,
    value:
      chartMode === 'asset'
        ? Number(item.total_asset || 0)
        : Number(item.total_asset || 0) - base,
  }));
}

export function buildChartState(points: ChartPoint[], visibleSeries: Set<string>): ChartState {
  const filtered = points.filter((item) => visibleSeries.has(item.series));
  const days = [...new Set(filtered.map((item) => item.day))];
  const names = [...new Set(points.map((item) => item.series))].filter((name) =>
    visibleSeries.has(name),
  );
  return { points: filtered, days, names };
}

export function syncVisibleSeries(
  names: string[],
  visibleSeries: Set<string>,
  knownSeries: Set<string>,
): { visible: Set<string>; known: Set<string> } {
  const nextKnown = new Set(knownSeries);
  const nextVisible = new Set(visibleSeries);
  names.forEach((name) => {
    if (!nextKnown.has(name)) {
      nextKnown.add(name);
      nextVisible.add(name);
    }
  });
  if (!nextVisible.size) names.forEach((name) => nextVisible.add(name));
  return {
    visible: new Set([...nextVisible].filter((name) => names.includes(name))),
    known: new Set([...nextKnown].filter((name) => names.includes(name))),
  };
}

const CHART_LAYOUT = { left: 52, right: 18, top: 20, bottom: 35 };

export function pointerToDayIndex(
  clientX: number,
  canvas: HTMLCanvasElement,
  dayCount: number,
): number {
  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const ratio = (x - CHART_LAYOUT.left) / Math.max(1, rect.width - 70);
  return Math.round(ratio * Math.max(dayCount - 1, 0));
}

export function drawLineChart(
  canvas: HTMLCanvasElement,
  state: ChartState | null,
  chartMode: ChartMode,
  focusIndex: number,
  allSeriesNames: string[],
): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(280, Math.floor(rect.width));
  const height = Math.max(240, Math.floor(rect.height));
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const palette = chartPalette();
  const points = state?.points ?? [];
  const days = state?.days ?? [];
  if (!points.length || !days.length) {
    ctx.fillStyle = palette.subtle;
    ctx.font = '14px Fira Sans, sans-serif';
    ctx.fillText('暂无收益数据', 24, 38);
    return;
  }

  const values = points.map((item) => item.value);
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (chartMode === 'return') {
    min = Math.min(min, -0.01);
    max = Math.max(max, 0.01);
  }
  if (min === max) {
    const pad = chartMode === 'return' ? 0.01 : Math.max(1, Math.abs(min) * 0.04);
    min -= pad;
    max += pad;
  }

  const { left, right, top, bottom } = CHART_LAYOUT;
  const graphW = width - left - right;
  const graphH = height - top - bottom;

  ctx.font = '11px Fira Sans, sans-serif';
  ctx.lineWidth = 1;
  ctx.strokeStyle = palette.line;
  ctx.fillStyle = palette.subtle;

  for (let index = 0; index < 5; index++) {
    const y = top + (graphH * index) / 4;
    const value = max - ((max - min) * index) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    ctx.fillText(chartLabel(value, chartMode), 3, y + 4);
  }

  ctx.fillText(days[0], left, height - 11);
  ctx.fillText(days.at(-1) ?? '', Math.max(left, width - right - 76), height - 11);

  const activeState = state!;
  activeState.names.forEach((name) => {
    const meta = seriesMeta(name, allSeriesNames.indexOf(name));
    const rows = points.filter((item) => item.series === name);
    ctx.beginPath();
    ctx.strokeStyle = name === 'AI-Agent' ? palette.brand : meta.color;
    ctx.lineWidth = name === 'AI-Agent' ? 3 : 1.7;
    ctx.setLineDash(meta.dash);
    rows.forEach((item, rowIndex) => {
      const dayIndex = days.indexOf(item.day);
      const x = left + (days.length === 1 ? 0 : (dayIndex * graphW) / (days.length - 1));
      const y = top + graphH - ((item.value - min) * graphH) / (max - min);
      if (rowIndex) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  });

  if (focusIndex >= 0 && days.length) {
    const x = left + (days.length === 1 ? 0 : (focusIndex * graphW) / (days.length - 1));
    ctx.strokeStyle = palette.crosshair;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + graphH);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

export function tooltipRowsForDay(state: ChartState | null, dayIndex: number): ChartPoint[] {
  if (!state?.days.length) return [];
  const day = state.days[Math.max(0, Math.min(dayIndex, state.days.length - 1))];
  return state.points.filter((item) => item.day === day);
}
