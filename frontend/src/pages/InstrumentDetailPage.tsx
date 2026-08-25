import { Typography } from 'antd';
import { useParams } from 'react-router-dom';

export default function InstrumentDetailPage() {
  const { symbol } = useParams<{ symbol: string }>();
  return <Typography.Title level={3}>标的详情 · {symbol}</Typography.Title>;
}
