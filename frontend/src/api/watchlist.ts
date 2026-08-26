import { apiGet, apiSend } from './client';
import type {
  InstrumentCatalogStatus,
  InstrumentSearchResult,
  OverviewPayload,
  WatchlistItem,
} from '@/types/dashboard';

export function searchInstruments(q: string, signal?: AbortSignal) {
  return apiGet<{ items: InstrumentSearchResult[]; catalog?: InstrumentCatalogStatus }>(
    `/api/watchlist/search?q=${encodeURIComponent(q)}`,
    signal,
  );
}

export function addWatchlistItem(
  item: { symbol: string; name: string; asset_type: string },
  signal?: AbortSignal,
) {
  return apiSend<{ item: WatchlistItem; dashboard: OverviewPayload }>(
    '/api/watchlist',
    'POST',
    item,
    signal,
  );
}

export function removeWatchlistItem(symbol: string, signal?: AbortSignal) {
  return apiSend<{ removed: string; watchlist: WatchlistItem[]; dashboard: OverviewPayload }>(
    `/api/watchlist/${encodeURIComponent(symbol)}`,
    'DELETE',
    undefined,
    signal,
  );
}

export function setWatchlistTrading(symbol: string, enabled: boolean, signal?: AbortSignal) {
  return apiSend<{ updated: string; enabled: boolean; dashboard: OverviewPayload }>(
    `/api/watchlist/${encodeURIComponent(symbol)}/trading`,
    'POST',
    { enabled },
    signal,
  );
}
