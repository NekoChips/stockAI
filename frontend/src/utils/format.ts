export function fmtMoney(value: unknown): string {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function fmtPct(value: unknown): string {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

export function toneClass(value: unknown): 'gain' | 'loss' | '' {
  const n = Number(value);
  if (n > 0) return 'gain';
  if (n < 0) return 'loss';
  return '';
}
