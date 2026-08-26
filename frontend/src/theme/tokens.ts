export type ThemeMode = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'stockai-theme';

export interface SemanticTokens {
  bg: string;
  surface: string;
  surface2: string;
  ink: string;
  subtle: string;
  line: string;
  brand: string;
  brandSoft: string;
  accent: string;
  gain: string;
  loss: string;
  gainWash: string;
  lossWash: string;
  warning: string;
  ring: string;
}

export const themeTokens: Record<ThemeMode, SemanticTokens> = {
  light: {
    bg: '#F4F7FB',
    surface: '#FFFFFF',
    surface2: '#EEF3F9',
    ink: '#0F172A',
    subtle: '#64748B',
    line: '#D8E2F0',
    brand: '#0F766E',
    brandSoft: '#CCFBF1',
    accent: '#0369A1',
    gain: '#DC2626',
    loss: '#059669',
    gainWash: '#FEF2F2',
    lossWash: '#ECFDF5',
    warning: '#D97706',
    ring: '#0F766E',
  },
  dark: {
    bg: '#020617',
    surface: '#0B1220',
    surface2: '#111827',
    ink: '#F1F5F9',
    subtle: '#94A3B8',
    line: '#1E293B',
    brand: '#2DD4BF',
    brandSoft: '#134E4A',
    accent: '#38BDF8',
    gain: '#F87171',
    loss: '#34D399',
    gainWash: '#3F1515',
    lossWash: '#0F2E24',
    warning: '#FBBF24',
    ring: '#2DD4BF',
  },
};

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark';
}
