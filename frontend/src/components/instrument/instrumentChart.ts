import type { InstrumentDetail, TradeMarker } from '@/types/dashboard';
import { chartPalette } from '@/theme/cssVars';
import { fmtMoney } from '@/utils/format';

export type InstrumentPeriod =
  | 'intraday'
  | 'five_day'
  | '1m'
  | '5m'
  | '15m'
  | '30m'
  | '60m'
  | 'daily'
  | 'weekly'
  | 'monthly';

export const INSTRUMENT_PERIODS: [InstrumentPeriod, string][] = [
  ['intraday', '分时'],
  ['five_day', '五日'],
  ['1m', '1分钟'],
  ['5m', '5分钟'],
  ['15m', '15分钟'],
  ['30m', '30分钟'],
  ['60m', '60分钟'],
  ['daily', '日K'],
  ['weekly', '周K'],
  ['monthly', '月K'],
];

export interface ChartPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface InstrumentChartState {
  points: ChartPoint[];
  candles: boolean;
  markers: TradeMarker[];
  min: number;
  max: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
  xFor: (index: number) => number;
  yFor: (value: number) => number;
  markerMap: Map<number, TradeMarker[]>;
}

const CHART_LAYOUT = { left: 56, right: 18, top: 20, bottom: 36 };

const SELL_DIRECTIONS = new Set(['卖出', '减仓', '清仓']);

export function quoteTimeLabel(value: string | undefined | null): string {
  if (!value) return '等待行情快照';
  const time = new Date(value);
  return Number.isNaN(time.getTime())
    ? String(value).replace('T', ' ').slice(0, 16)
    : time.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
}

export function instrumentTimeLabel(value: string | undefined, compact = false): string {
  const raw = String(value || '');
  if (!raw) return '--';
  const normalized = raw.replace('T', ' ');
  return compact
    ? normalized.includes(' ')
      ? normalized.slice(5, 16)
      : normalized.slice(5, 10)
    : normalized.slice(0, 16);
}

export function periodUsesCandles(period: InstrumentPeriod): boolean {
  return !['intraday', 'five_day'].includes(period);
}

export function instrumentPeriodPoints(
  data: InstrumentDetail,
  period: InstrumentPeriod,
): ChartPoint[] {
  if (period === 'intraday') {
    return (data.intraday?.ticks ?? []).map((item) => ({
      time: String(item.observed_at || item.quoted_at || ''),
      close: Number(item.latest_price),
      open: Number(item.latest_price),
      high: Number(item.latest_price),
      low: Number(item.latest_price),
    }));
  }
  const source =
    period === 'five_day'
      ? data.five_day
      : period.endsWith('m')
        ? data.minute_bars?.[period]
        : data[period as 'daily' | 'weekly' | 'monthly'];
  return (source ?? []).map((item) => ({
    time: item.time,
    open: Number(item.open),
    high: Number(item.high),
    low: Number(item.low),
    close: Number(item.close),
  }));
}

export function instrumentMarkerIndex(
  marker: TradeMarker,
  points: ChartPoint[],
  period: InstrumentPeriod,
): number {
  if (!points.length) return -1;
  const markerDate = String(marker.timestamp || '').slice(0, 10);
  const markerMonth = markerDate.slice(0, 7);
  const dayIndexes = points
    .map((point, index) => (String(point.time || '').slice(0, 10) === markerDate ? index : -1))
    .filter((index) => index >= 0);
  if (['intraday', '1m', '5m', '15m', '30m', '60m', 'five_day'].includes(period)) {
    if (!dayIndexes.length) return -1;
    const markerTime = new Date(marker.timestamp).getTime();
    return dayIndexes.reduce((best, index) =>
      Math.abs(new Date(points[index].time).getTime() - markerTime) <
      Math.abs(new Date(points[best].time).getTime() - markerTime)
        ? index
        : best,
    dayIndexes[0]);
  }
  if (period === 'daily') return dayIndexes[0] ?? -1;
  if (period === 'weekly') {
    if (!markerDate) return -1;
    const monday = new Date(`${markerDate}T00:00:00Z`);
    const offset = (monday.getUTCDay() + 6) % 7;
    monday.setUTCDate(monday.getUTCDate() - offset);
    return points.findIndex(
      (point) => String(point.time || '').slice(0, 10) === monday.toISOString().slice(0, 10),
    );
  }
  if (period === 'monthly') {
    return points.findIndex((point) => String(point.time || '').slice(0, 7) === markerMonth);
  }
  return -1;
}

export function buildInstrumentChartState(
  data: InstrumentDetail,
  period: InstrumentPeriod,
): Pick<InstrumentChartState, 'points' | 'candles' | 'markers'> {
  return {
    points: instrumentPeriodPoints(data, period),
    candles: periodUsesCandles(period),
    markers: data.trade_markers ?? [],
  };
}

export function periodLabel(period: InstrumentPeriod): string {
  return INSTRUMENT_PERIODS.find(([key]) => key === period)?.[1] ?? period;
}

export function chartNoteText(
  period: InstrumentPeriod,
  data: InstrumentDetail,
  pointCount: number,
): string {
  const label = periodLabel(period);
  const dayCount = period === 'five_day' ? Number(data.five_day_trading_days || 0) : 0;
  if (!pointCount) return `${label} · 暂无数据`;
  const dayPart = dayCount ? `${dayCount} 个交易日 / ` : '';
  return `${label} · ${dayPart}${pointCount} 个数据点`;
}

export function chartSummaryText(period: InstrumentPeriod, pointCount: number): string {
  const label = periodLabel(period);
  return pointCount
    ? `${label}共 ${pointCount} 个数据点，左右方向键可逐点查看；图中 B/S 标记为模拟交易。`
    : `${label}暂无本地数据。监控运行后会逐步沉淀。`;
}

export function pointerToPointIndex(
  clientX: number,
  canvas: HTMLCanvasElement,
  pointCount: number,
): number {
  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const ratio = (x - CHART_LAYOUT.left) / Math.max(1, rect.width - 74);
  return Math.round(ratio * Math.max(pointCount - 1, 0));
}

export function drawInstrumentChart(
  canvas: HTMLCanvasElement,
  base: Pick<InstrumentChartState, 'points' | 'candles' | 'markers'> | null,
  period: InstrumentPeriod,
  focusIndex: number,
): InstrumentChartState | null {
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(280, Math.floor(rect.width));
  const height = Math.max(240, Math.floor(rect.height));
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const palette = chartPalette();
  const points = base?.points ?? [];
  if (!points.length) {
    ctx.fillStyle = palette.subtle;
    ctx.font = '14px Fira Sans, sans-serif';
    ctx.fillText('暂无本地行情数据', 24, 38);
    return null;
  }

  const candles = base!.candles;
  const prices = points.flatMap((item) => (candles ? [item.high, item.low] : [item.close]));
  let min = Math.min(...prices);
  let max = Math.max(...prices);
  let padding = Math.max((max - min) * 0.08, max * 0.003, 0.01);
  if (min === max) padding = Math.max(max * 0.01, 0.01);
  min -= padding;
  max += padding;

  const { left, right, top, bottom } = CHART_LAYOUT;
  const graphW = width - left - right;
  const graphH = height - top - bottom;
  const yFor = (value: number) => top + graphH - ((value - min) * graphH) / (max - min);
  const xFor = (index: number) =>
    left + (points.length === 1 ? graphW / 2 : (index * graphW) / (points.length - 1));

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
    ctx.fillText(fmtMoney(value), 4, y + 4);
  }

  ctx.fillText(instrumentTimeLabel(points[0].time, true), left, height - 11);
  ctx.fillText(
    instrumentTimeLabel(points.at(-1)?.time, true),
    Math.max(left, width - right - 90),
    height - 11,
  );

  if (candles) {
    const body = Math.max(3, Math.min(14, (graphW / Math.max(points.length, 1)) * 0.62));
    points.forEach((point, index) => {
      const x = xFor(index);
      const rising = point.close >= point.open;
      ctx.strokeStyle = rising ? palette.gain : palette.loss;
      ctx.fillStyle = ctx.strokeStyle;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, yFor(point.high));
      ctx.lineTo(x, yFor(point.low));
      ctx.stroke();
      const y = Math.min(yFor(point.open), yFor(point.close));
      const h = Math.max(1, Math.abs(yFor(point.open) - yFor(point.close)));
      if (rising) ctx.fillRect(x - body / 2, y, body, h);
      else ctx.strokeRect(x - body / 2, y, body, h);
    });
  } else {
    ctx.beginPath();
    ctx.strokeStyle = palette.brand;
    ctx.lineWidth = 2.5;
    points.forEach((point, index) => {
      const x = xFor(index);
      const y = yFor(point.close);
      if (index) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.stroke();
  }

  const markerMap = new Map<number, TradeMarker[]>();
  (base?.markers ?? []).forEach((marker) => {
    const index = instrumentMarkerIndex(marker, points, period);
    if (index < 0) return;
    if (!markerMap.has(index)) markerMap.set(index, []);
    markerMap.get(index)!.push(marker);
  });

  markerMap.forEach((markers, index) => {
    const marker = markers.at(-1)!;
    const sell = SELL_DIRECTIONS.has(marker.direction);
    const x = xFor(index);
    const y = Math.max(top + 10, yFor(points[index].close) - (sell ? -18 : 18));
    ctx.fillStyle = sell ? palette.loss : palette.gain;
    ctx.beginPath();
    ctx.arc(x, y, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = palette.surface;
    ctx.font = '700 10px Fira Sans, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(sell ? 'S' : 'B', x, y + 3.5);
    ctx.textAlign = 'left';
  });

  if (focusIndex >= 0) {
    const x = xFor(focusIndex);
    ctx.strokeStyle = palette.crosshair;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + graphH);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  return {
    points,
    candles,
    markers: base?.markers ?? [],
    min,
    max,
    left,
    right,
    top,
    bottom,
    width,
    height,
    xFor,
    yFor,
    markerMap,
  };
}

export function tooltipAnnounceText(
  point: ChartPoint,
  markers: TradeMarker[],
  candles: boolean,
): string {
  const markerPart = markers.length ? `；${markers.map((item) => item.direction).join('、')}` : '';
  return `${instrumentTimeLabel(point.time)}，${candles ? '收' : ''} ${fmtMoney(point.close)}${markerPart}`;
}
