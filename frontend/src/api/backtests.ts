import { apiGet, apiSend } from './client';
import type { BacktestsPayload, ConfirmBacktestsResult } from '@/types/dashboard';

export function fetchBacktests(signal?: AbortSignal) {
  return apiGet<BacktestsPayload>('/api/dashboard/backtests', signal);
}

export function runBacktest(signal?: AbortSignal) {
  return apiSend<BacktestsPayload>('/api/backtests/run', 'POST', undefined, signal);
}

export function confirmBacktests(ids: number[], signal?: AbortSignal) {
  return apiSend<ConfirmBacktestsResult>('/api/backtests/confirm', 'POST', { ids }, signal);
}
