import { apiGet } from './client';
import type {
  CalendarPayload,
  OverviewPayload,
  PerformancePayload,
  PerformanceQuery,
} from '@/types/dashboard';

export function fetchOverview(signal?: AbortSignal) {
  return apiGet<OverviewPayload>('/api/dashboard/overview', signal);
}

export function fetchPerformance(query: PerformanceQuery, signal?: AbortSignal) {
  const qs = new URLSearchParams({
    performance_start: query.performance_start,
    performance_end: query.performance_end,
  }).toString();
  return apiGet<PerformancePayload>(`/api/dashboard/performance?${qs}`, signal);
}

export function fetchCalendar(signal?: AbortSignal) {
  return apiGet<CalendarPayload>('/api/dashboard/calendar', signal);
}
