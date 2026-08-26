import { apiGet, apiSend } from './client';
import type { StrategiesPayload, StrategyProfile } from '@/types/dashboard';

export function fetchStrategies(signal?: AbortSignal) {
  return apiGet<StrategiesPayload>('/api/dashboard/strategies', signal);
}

export function saveStrategyProfile(profile: StrategyProfile, signal?: AbortSignal) {
  return apiSend<StrategiesPayload>('/api/strategies/profiles', 'POST', profile, signal);
}

export function confirmStrategyProfile(profileId: string, signal?: AbortSignal) {
  return apiSend<StrategiesPayload>(
    `/api/strategies/profiles/${encodeURIComponent(profileId)}/confirm`,
    'POST',
    undefined,
    signal,
  );
}

export function discardStrategyDraft(profileId: string, signal?: AbortSignal) {
  return apiSend<{ discarded: string }>(
    `/api/strategies/profiles/${encodeURIComponent(profileId)}/draft`,
    'DELETE',
    undefined,
    signal,
  );
}
