import { create } from 'zustand';

interface UiState {
  notice: string;
  liveMessage: string;
  setNotice: (message: string) => void;
  announce: (message: string) => void;
}

export const useUiStore = create<UiState>((set) => ({
  notice: '',
  liveMessage: '',
  setNotice: (notice) => set({ notice }),
  announce: (liveMessage) => set({ liveMessage }),
}));
