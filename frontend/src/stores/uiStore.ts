import { create } from 'zustand';
import {
  THEME_STORAGE_KEY,
  isThemeMode,
  type ThemeMode,
} from '@/theme/tokens';

function readStoredTheme(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeMode(raw)) return raw;
  } catch {
    /* ignore quota / private mode */
  }
  return 'light';
}

interface UiState {
  notice: string;
  liveMessage: string;
  theme: ThemeMode;
  setNotice: (message: string) => void;
  announce: (message: string) => void;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  notice: '',
  liveMessage: '',
  theme: readStoredTheme(),
  setNotice: (notice) => set({ notice }),
  announce: (liveMessage) => set({ liveMessage }),
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
    set({ theme });
  },
  toggleTheme: () => {
    const next: ThemeMode = get().theme === 'light' ? 'dark' : 'light';
    get().setTheme(next);
  },
}));
