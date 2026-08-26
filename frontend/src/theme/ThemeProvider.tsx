import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useEffect, type ReactNode } from 'react';
import { useUiStore } from '@/stores/uiStore';
import { getAntdTheme } from '@/theme/antdTheme';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const themeMode = useUiStore((s) => s.theme);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
  }, [themeMode]);

  return (
    <ConfigProvider locale={zhCN} theme={getAntdTheme(themeMode)}>
      {children}
    </ConfigProvider>
  );
}
