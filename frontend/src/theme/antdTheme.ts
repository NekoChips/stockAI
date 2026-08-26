import { theme, type ThemeConfig } from 'antd';
import { themeTokens, type ThemeMode } from './tokens';

export function getAntdTheme(mode: ThemeMode): ThemeConfig {
  const t = themeTokens[mode];
  return {
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: t.brand,
      colorInfo: t.accent,
      // Ant success/error 槽位仅供组件默认态；业务涨跌一律走 .gain / .loss
      colorSuccess: t.loss,
      colorError: t.gain,
      colorWarning: t.warning,
      colorBgLayout: t.bg,
      colorBgContainer: t.surface,
      colorText: t.ink,
      colorTextSecondary: t.subtle,
      colorBorder: t.line,
      colorBorderSecondary: t.line,
      borderRadius: 8,
      fontFamily: '"Fira Sans", "PingFang SC", "Microsoft YaHei", sans-serif',
    },
    components: {
      Layout: {
        headerBg: t.surface,
        bodyBg: t.bg,
      },
      Menu: {
        itemSelectedColor: t.brand,
        horizontalItemSelectedColor: t.brand,
        horizontalItemSelectedBg: 'transparent',
      },
      Card: {
        colorBgContainer: t.surface,
      },
    },
  };
}
