import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Typography } from 'antd';

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/" element={<Typography.Title level={3}>StockAI SPA</Typography.Title>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
