import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, Drawer, Input, List, Space, Tag, Typography } from 'antd';
import { addWatchlistItem, searchInstruments } from '@/api/watchlist';
import { useUiStore } from '@/stores/uiStore';
import type { InstrumentSearchResult } from '@/types/dashboard';

interface AddInstrumentDrawerProps {
  open: boolean;
  onClose: () => void;
}

const SEARCH_DEBOUNCE_MS = 240;

export function AddInstrumentDrawer({ open, onClose }: AddInstrumentDrawerProps) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<InstrumentSearchResult[]>([]);
  const [catalogEmpty, setCatalogEmpty] = useState(false);
  const [selected, setSelected] = useState<InstrumentSearchResult | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const queryClient = useQueryClient();
  const announce = useUiStore((s) => s.announce);

  const reset = () => {
    setQuery('');
    setResults([]);
    setSelected(null);
    setSearching(false);
    setCatalogEmpty(false);
  };

  useEffect(() => {
    if (!open) {
      reset();
      if (timerRef.current) clearTimeout(timerRef.current);
    }
  }, [open]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setSelected(null);

    const text = query.trim();
    if (text.length < 2) {
      setResults([]);
      setSearching(false);
      return;
    }

    setSearching(true);
    const controller = new AbortController();
    timerRef.current = setTimeout(() => {
      searchInstruments(text, controller.signal)
        .then((payload) => {
          setResults(payload.items ?? []);
          setCatalogEmpty(Number(payload.catalog?.count ?? 0) > 0);
        })
        .catch((err: unknown) => {
          if (err instanceof DOMException && err.name === 'AbortError') return;
          setResults([]);
          announce('标的搜索失败。');
        })
        .finally(() => setSearching(false));
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      controller.abort();
    };
  }, [query, announce]);

  const addMutation = useMutation({
    mutationFn: (item: InstrumentSearchResult) => addWatchlistItem(item),
    onSuccess: (payload) => {
      queryClient.setQueryData(['overview'], payload.dashboard);
      announce(`${selected?.name ?? payload.item.symbol} 已加入观察池。`);
      onClose();
    },
    onError: (error) => {
      announce(
        error instanceof Error && error.message
          ? error.message
          : '添加标的失败，请检查代码和市场范围。',
      );
    },
  });

  const emptyText =
    query.trim().length < 2
      ? '请输入至少两个字符。'
      : searching
        ? '正在检索标的...'
        : catalogEmpty
          ? '未找到符合条件的沪深股票或 ETF。'
          : '证券目录正在同步，请稍后再试。';

  return (
    <Drawer
      title="添加观察标的"
      open={open}
      onClose={onClose}
      width={420}
      destroyOnClose
      keyboard
      footer={
        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            disabled={!selected}
            loading={addMutation.isPending}
            onClick={() => selected && addMutation.mutate(selected)}
          >
            加入观察池
          </Button>
        </Space>
      }
    >
      <Input
        placeholder="输入代码或名称搜索"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        allowClear
        autoFocus
      />
      {selected ? (
        <div className="watchlist-selected">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已选择
          </Typography.Text>
          <div style={{ fontWeight: 650 }}>
            {selected.name} · {selected.symbol}
          </div>
        </div>
      ) : null}
      <List
        style={{ marginTop: 16 }}
        locale={{ emptyText }}
        dataSource={results}
        renderItem={(item) => (
          <List.Item
            onClick={() => setSelected(item)}
            className={
              selected?.symbol === item.symbol ? 'watchlist-result is-selected' : 'watchlist-result'
            }
            style={{
              cursor: 'pointer',
              borderRadius: 8,
              paddingInline: 12,
            }}
          >
            <List.Item.Meta
              title={
                <Space>
                  <span>{item.name}</span>
                  <Tag>{item.asset_type === 'etf' ? 'ETF' : '股票'}</Tag>
                </Space>
              }
              description={item.symbol}
            />
          </List.Item>
        )}
      />
    </Drawer>
  );
}
