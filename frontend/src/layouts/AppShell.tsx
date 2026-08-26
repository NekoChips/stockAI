import { Layout, Menu, Button, Alert, Typography } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useUiStore } from '@/stores/uiStore';
import { invalidateDashboardQueries } from '@/components/dashboard/DashboardRefreshControls';

const { Header, Content } = Layout;

const items = [
  { key: '/', label: '交易看板' },
  { key: '/backtests', label: '回测记录' },
  { key: '/strategies', label: '策略中心' },
  { key: '/reports', label: '日报归档' },
];

function retryCurrentRoute(
  pathname: string,
  queryClient: ReturnType<typeof useQueryClient>,
) {
  if (pathname === '/' || pathname === '') {
    invalidateDashboardQueries(queryClient);
    return;
  }
  if (pathname.startsWith('/strategies')) {
    void queryClient.invalidateQueries({ queryKey: ['strategies'] });
    void queryClient.invalidateQueries({ queryKey: ['overview'] });
    return;
  }
  if (pathname.startsWith('/backtests')) {
    void queryClient.invalidateQueries({ queryKey: ['backtests'] });
    return;
  }
  if (pathname.startsWith('/reports')) {
    void queryClient.invalidateQueries({ queryKey: ['reports'] });
    void queryClient.invalidateQueries({ queryKey: ['report'] });
    return;
  }
  if (pathname.startsWith('/instruments/')) {
    void queryClient.invalidateQueries({ queryKey: ['instrument'] });
    return;
  }
  void queryClient.invalidateQueries();
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const notice = useUiStore((s) => s.notice);
  const liveMessage = useUiStore((s) => s.liveMessage);
  const setNotice = useUiStore((s) => s.setNotice);
  const selected =
    items.find((item) =>
      item.key === '/' ? location.pathname === '/' : location.pathname.startsWith(item.key),
    )?.key ?? '/';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          background: '#fff',
          paddingInline: 24,
        }}
      >
        <Typography.Title level={4} style={{ margin: 0 }}>
          StockAI
        </Typography.Title>
        <Menu
          mode="horizontal"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        {notice ? (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={notice}
            action={
              <Button
                size="small"
                onClick={() => {
                  setNotice('');
                  retryCurrentRoute(location.pathname, queryClient);
                }}
              >
                重试
              </Button>
            }
          />
        ) : null}
        <Outlet />
        <div className="sr-only" aria-live="polite">
          {liveMessage}
        </div>
      </Content>
    </Layout>
  );
}
