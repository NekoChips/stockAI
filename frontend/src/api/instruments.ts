import { apiGet } from './client';
import type { InstrumentDetail } from '@/types/dashboard';

export function fetchInstrumentDetail(symbol: string, signal?: AbortSignal) {
  return apiGet<InstrumentDetail>(
    `/api/instruments/${encodeURIComponent(symbol)}/detail`,
    signal,
  );
}
