import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { AppShell } from '@/layouts/AppShell';

const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const BacktestPage = lazy(() => import('@/pages/BacktestPage'));
const StrategyPage = lazy(() => import('@/pages/StrategyPage'));
const DailyReportPage = lazy(() => import('@/pages/DailyReportPage'));
const InstrumentDetailPage = lazy(() => import('@/pages/InstrumentDetailPage'));

function PageFallback() {
  return <Spin style={{ display: 'block', margin: '48px auto' }} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route
            index
            element={
              <Suspense fallback={<PageFallback />}>
                <DashboardPage />
              </Suspense>
            }
          />
          <Route
            path="backtests"
            element={
              <Suspense fallback={<PageFallback />}>
                <BacktestPage />
              </Suspense>
            }
          />
          <Route
            path="strategies"
            element={
              <Suspense fallback={<PageFallback />}>
                <StrategyPage />
              </Suspense>
            }
          />
          <Route
            path="reports"
            element={
              <Suspense fallback={<PageFallback />}>
                <DailyReportPage />
              </Suspense>
            }
          />
          <Route
            path="instruments/:symbol"
            element={
              <Suspense fallback={<PageFallback />}>
                <InstrumentDetailPage />
              </Suspense>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
