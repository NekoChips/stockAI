import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Typography } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { fetchInstrumentDetail } from '@/api/instruments';
import {
  InstrumentDetail,
  InstrumentDetailLoading,
} from '@/components/instrument/InstrumentDetail';
import { useUiStore } from '@/stores/uiStore';

export default function InstrumentDetailPage() {
  const { symbol = '' } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const announce = useUiStore((s) => s.announce);
  const setNotice = useUiStore((s) => s.setNotice);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['instrument', symbol],
    queryFn: ({ signal }) => fetchInstrumentDetail(symbol, signal),
    enabled: Boolean(symbol),
  });

  useEffect(() => {
    if (isError) {
      setNotice(
        error instanceof Error && error.message
          ? error.message
          : '无法读取本地行情数据，请稍后重试。',
      );
      announce('标的详情读取失败。');
    }
  }, [isError, error, setNotice, announce]);

  useEffect(() => {
    if (data?.instrument?.name) {
      announce(`${data.instrument.name} 标的详情已打开。`);
    }
  }, [data?.instrument?.name, announce]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (window.history.length > 1) {
        navigate(-1);
      } else {
        navigate('/');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [navigate]);

  if (!symbol) {
    return (
      <Typography.Paragraph type="secondary">缺少标的代码。</Typography.Paragraph>
    );
  }

  if (isLoading) {
    return <InstrumentDetailLoading />;
  }

  if (isError || !data) {
    return (
      <div className="instrument-detail">
        <Link to="/">
          <Button type="default" icon={<ArrowLeftOutlined />} className="detail-back">
            返回交易看板
          </Button>
        </Link>
        <Card>
          <Typography.Title level={4} style={{ marginTop: 0 }}>
            标的详情读取失败
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            无法读取本地行情数据，请稍后重试。
          </Typography.Paragraph>
        </Card>
      </div>
    );
  }

  return <InstrumentDetail data={data} />;
}
