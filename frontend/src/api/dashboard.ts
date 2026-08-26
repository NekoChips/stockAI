import { apiGet } from './client';
import type {
  CalendarPayload,
  DecisionEventsPayload,
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

export function fetchDecisionEvents(
  params?: { date?: string; limit?: number },
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams();
  if (params?.date) qs.set('date', params.date);
  if (params?.limit != null) qs.set('limit', String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : '';
  return apiGet<DecisionEventsPayload>(`/api/dashboard/decision-events${suffix}`, signal);
}
