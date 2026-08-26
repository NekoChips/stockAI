import { Button, Tooltip } from 'antd';
import { MoonOutlined, SunOutlined } from '@ant-design/icons';
import { useUiStore } from '@/stores/uiStore';

export function ThemeToggle() {
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const nextLabel = theme === 'light' ? '切换到暗色主题' : '切换到亮色主题';

  return (
    <Tooltip title={nextLabel}>
      <Button
        type="text"
        className="theme-toggle"
        aria-label={nextLabel}
        onClick={toggleTheme}
        icon={theme === 'light' ? <MoonOutlined /> : <SunOutlined />}
      />
    </Tooltip>
  );
}
