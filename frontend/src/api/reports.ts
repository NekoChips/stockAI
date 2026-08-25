import { apiGet } from './client';
import type { DailyReportPayload, DailyReportsPayload } from '@/types/dashboard';

export interface ReportsQuery {
  limit?: number;
  offset?: number;
}

export function fetchReports(query: ReportsQuery = {}, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  if (query.offset !== undefined) params.set('offset', String(query.offset));
  const qs = params.toString();
  const path = qs ? `/api/dashboard/reports?${qs}` : '/api/dashboard/reports';
  return apiGet<DailyReportsPayload>(path, signal);
}

export function fetchReport(reportDate: string, signal?: AbortSignal) {
  return apiGet<DailyReportPayload>(
    `/api/dashboard/reports/${encodeURIComponent(reportDate)}`,
    signal,
  );
}
