import { apiSend } from './client';
import type { JsonDecimal, RiskConfig } from '@/types/dashboard';

export function saveRiskConfig(payload: Record<string, JsonDecimal>, signal?: AbortSignal) {
  return apiSend<{ risk_config: RiskConfig }>('/api/risk-config', 'POST', payload, signal);
}

export function confirmRiskConfig(signal?: AbortSignal) {
  return apiSend<{ risk_config: RiskConfig }>('/api/risk-config/confirm', 'POST', undefined, signal);
}
