import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, Spin, Tag, Typography } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import type { InstrumentDetail as InstrumentDetailData, TradeMarker } from '@/types/dashboard';
import { fmtMoney, fmtPct, toneClass } from '@/utils/format';
import { useUiStore } from '@/stores/uiStore';
import {
  buildInstrumentChartState,
  chartNoteText,
  chartSummaryText,
  drawInstrumentChart,
  instrumentTimeLabel,
  INSTRUMENT_PERIODS,
  pointerToPointIndex,
  quoteTimeLabel,
  tooltipAnnounceText,
  type InstrumentChartState,
  type InstrumentPeriod,
} from './instrumentChart';

const SELL_DIRECTIONS = new Set(['卖出', '减仓', '清仓']);

interface InstrumentDetailProps {
  data: InstrumentDetailData;
}

export function InstrumentDetail({ data }: InstrumentDetailProps) {
  const announce = useUiStore((s) => s.announce);
  const theme = useUiStore((s) => s.theme);
  const [period, setPeriod] = useState<InstrumentPeriod>('intraday');
  const [focusIndex, setFocusIndex] = useState(-1);
  const [tooltip, setTooltip] = useState<{
    visible: boolean;
    left: number;
    top: number;
    time: string;
    candles: boolean;
    open: number;
    high: number;
    low: number;
    close: number;
    markers: TradeMarker[];
  }>({
    visible: false,
    left: 0,
    top: 0,
    time: '',
    candles: false,
    open: 0,
    high: 0,
    low: 0,
    close: 0,
    markers: [],
  });

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartStateRef = useRef<InstrumentChartState | null>(null);

  const instrument = data.instrument;
  const quote = data.latest_quote ?? {};
  const markers = data.trade_markers ?? [];
  const change = Number(quote.change_percent);

  const chartBase = useMemo(() => buildInstrumentChartState(data, period), [data, period]);
  const pointCount = chartBase.points.length;

  useEffect(() => {
    setFocusIndex(-1);
    setTooltip((prev) => ({ ...prev, visible: false }));
  }, [period, data]);

  useEffect(() => {
    if (pointCount) {
      setFocusIndex((prev) => Math.min(Math.max(prev, 0), Math.max(pointCount - 1, 0)));
    }
  }, [pointCount]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    chartStateRef.current = drawInstrumentChart(canvas, chartBase, period, focusIndex);
  }, [chartBase, period, focusIndex]);

  useEffect(() => {
    redraw();
  }, [redraw, theme]);

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
      if (!state?.points.length) return;
      const nextIndex = Math.max(0, Math.min(index, state.points.length - 1));
      setFocusIndex(nextIndex);
      const point = state.points[nextIndex];
      const pointMarkers = state.markerMap.get(nextIndex) ?? [];
      const wrap = wrapRef.current;
      const width = wrap?.clientWidth ?? 0;
      const height = wrap?.clientHeight ?? 0;
      setTooltip({
        visible: true,
        left: Math.max(8, Math.min(pointerX ?? Math.round(width * 0.64), width - 205)),
        top: Math.max(8, Math.min(pointerY ?? 18, height - 116)),
        time: instrumentTimeLabel(point.time),
        candles: state.candles,
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
        markers: pointMarkers,
      });
      announce(tooltipAnnounceText(point, pointMarkers, state.candles));
    },
    [announce],
  );

  const chartText = chartSummaryText(period, pointCount);

  return (
    <div className="instrument-detail">
      <Link to="/">
        <Button type="default" icon={<ArrowLeftOutlined />} className="detail-back">
          返回交易看板
        </Button>
      </Link>

      <Card styles={{ body: { padding: 0 } }} aria-live="polite">
        <div className="instrument-hero">
          <div className="instrument-summary">
            <span className="kicker">标的详情</span>
            <Typography.Title level={2} className="instrument-name" style={{ margin: 0 }}>
              {instrument.name || instrument.symbol || '标的详情'}
            </Typography.Title>
            <div className="instrument-symbol">
              {instrument.symbol || '--'} · {instrument.asset_type === 'etf' ? 'ETF' : '沪深股票'}
            </div>
          </div>
          <div className="instrument-stat">
            <span className="kicker">最新价</span>
            <strong className="tabular">
              {quote.latest_price == null ? '--' : fmtMoney(quote.latest_price)}
            </strong>
            <span className="stat-note">
              {quoteTimeLabel(quote.observed_at || quote.quoted_at || quote.updated_at)}
            </span>
          </div>
          <div className="instrument-stat">
            <span className="kicker">今日涨跌</span>
            <strong className={`tabular ${Number.isFinite(change) ? toneClass(change / 100) : ''}`}>
              {Number.isFinite(change) ? fmtPct(change / 100) : '--'}
            </strong>
            <span className="stat-note">
              {quote.previous_close == null
                ? '昨收 --'
                : `昨收 ${fmtMoney(quote.previous_close)}`}
            </span>
          </div>
          <div className="instrument-stat">
            <span className="kicker">模拟成交</span>
            <strong className="tabular">{markers.length} 笔</strong>
            <span className="stat-note">标记显示在图表中</span>
          </div>
        </div>

        <div className="instrument-chart-tools">
          <div className="instrument-period-tabs" aria-label="K线周期">
            {INSTRUMENT_PERIODS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={period === key ? 'active' : ''}
                aria-pressed={period === key}
                onClick={() => setPeriod(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="instrument-chart-note">{chartNoteText(period, data, pointCount)}</span>
        </div>

        <div className="instrument-chart-wrap" ref={wrapRef}>
          <canvas
            ref={canvasRef}
            tabIndex={0}
            role="img"
            aria-describedby="instrumentChartText"
            aria-label="标的行情图。可使用左右方向键读取行情数据。"
            onPointerMove={(event) => {
              const canvas = canvasRef.current;
              if (!canvas || !chartStateRef.current?.points.length) return;
              const rect = canvas.getBoundingClientRect();
              const index = pointerToPointIndex(
                event.clientX,
                canvas,
                chartStateRef.current.points.length,
              );
              showChartPoint(index, event.clientX - rect.left + 8, event.clientY - rect.top + 8);
            }}
            onPointerLeave={() => setTooltip((prev) => ({ ...prev, visible: false }))}
            onKeyDown={(event) => {
              const state = chartStateRef.current;
              if (!state?.points.length) return;
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
                showChartPoint(state.points.length - 1);
              }
            }}
          />
          <div
            className={`chart-tooltip instrument-chart-tooltip${tooltip.visible ? ' visible' : ''}`}
            role="status"
            aria-live="polite"
            style={{ left: tooltip.left, top: tooltip.top }}
          >
            {tooltip.visible ? (
              <>
                <strong>{tooltip.time}</strong>
                {tooltip.candles ? (
                  <>
                    <div className="chart-tooltip-row">
                      <span>开 / 高</span>
                      <b>
                        {fmtMoney(tooltip.open)} / {fmtMoney(tooltip.high)}
                      </b>
                    </div>
                    <div className="chart-tooltip-row">
                      <span>低 / 收</span>
                      <b>
                        {fmtMoney(tooltip.low)} / {fmtMoney(tooltip.close)}
                      </b>
                    </div>
                  </>
                ) : (
                  <div className="chart-tooltip-row">
                    <span>最新价</span>
                    <b>{fmtMoney(tooltip.close)}</b>
                  </div>
                )}
                {tooltip.markers.map((marker) => (
                  <div key={`${marker.timestamp}-${marker.direction}`} className="chart-tooltip-row">
                    <span>{marker.direction}</span>
                    <b>{marker.summary}</b>
                  </div>
                ))}
              </>
            ) : null}
          </div>
        </div>

        <p className="sr-only" id="instrumentChartText">
          {chartText}
        </p>

        <div className="instrument-detail-footer">
          <section className="instrument-detail-section">
            <Typography.Title level={5} style={{ margin: 0 }}>
              数据说明
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              分时与分钟 K 由当日监控快照聚合；日、周、月 K 使用已入库历史日线。
            </Typography.Paragraph>
          </section>
          <section className="instrument-detail-section">
            <Typography.Title level={5} style={{ margin: 0 }}>
              模拟操作
            </Typography.Title>
            <div className="trade-marker-list">
              {markers.length ? (
                [...markers].reverse().map((marker) => (
                  <article key={`${marker.timestamp}-${marker.direction}`} className="trade-marker-item">
                    <div>
                      <Tag color={SELL_DIRECTIONS.has(marker.direction) ? 'green' : 'default'}>
                        {marker.direction}
                      </Tag>
                      <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 12 }}>
                        {marker.summary}
                      </Typography.Paragraph>
                    </div>
                    <time>{quoteTimeLabel(marker.timestamp)}</time>
                  </article>
                ))
              ) : (
                <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                  暂无模拟成交；后续买入、加减仓和清仓会在图中标记。
                </Typography.Paragraph>
              )}
            </div>
          </section>
        </div>
      </Card>
    </div>
  );
}

export function InstrumentDetailLoading() {
  return (
    <div className="instrument-detail">
      <Link to="/">
        <Button type="default" icon={<ArrowLeftOutlined />} className="detail-back">
          返回交易看板
        </Button>
      </Link>
      <Card>
        <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
          <Spin tip="正在读取本地行情与模拟成交数据。" />
        </div>
      </Card>
    </div>
  );
}
