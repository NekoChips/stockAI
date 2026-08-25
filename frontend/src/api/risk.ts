import { apiSend } from './client';
import type { JsonDecimal, RiskConfig } from '@/types/dashboard';

export function saveRiskConfig(payload: Record<string, JsonDecimal>) {
  return apiSend<{ risk_config: RiskConfig }>('/api/risk-config', 'POST', payload);
}

export function confirmRiskConfig() {
  return apiSend<{ risk_config: RiskConfig }>('/api/risk-config/confirm', 'POST');
}
