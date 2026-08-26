import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import { PlusOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  confirmStrategyProfile,
  discardStrategyDraft,
  fetchStrategies,
  saveStrategyProfile,
} from '@/api/strategies';
import { useUiStore } from '@/stores/uiStore';
import type {
  ProfileDiffEntry,
  StrategyChange,
  StrategyDefinition,
  StrategyProfile,
} from '@/types/dashboard';

/** Mirror legacy `newStrategyProfile()`: local draft cloned from default. */
export function createNewStrategyDraft(profiles: StrategyProfile[]): StrategyProfile {
  const base = profiles.find((item) => item.profile_id === 'default') ?? ({} as StrategyProfile);
  return {
    ...base,
    profile_id: '',
    name_zh: '新策略组合',
    name_en: 'New Strategy Profile',
    scope_type: 'symbol',
    scope_value: '',
    status: 'draft',
    revision: 0,
    draft_diff: [],
    pending_activation: false,
  };
}

function scopeLabel(profile: StrategyProfile): string {
  if (profile.scope_type === 'default') return '默认组合';
  if (profile.scope_type === 'symbol') return `标的 ${profile.scope_value ?? ''}`;
  return `资产类型 ${profile.scope_value ?? ''}`;
}

function statusLabel(profile: StrategyProfile): string {
  if (profile.pending_activation) return '待下一轮生效';
  return profile.status === 'active' ? '生效中' : '待确认';
}

function hasDraft(profile: StrategyProfile): boolean {
  return profile.status !== 'active' || (profile.draft_diff?.length ?? 0) > 0;
}

function canConfirmOrDiscard(profile: StrategyProfile): boolean {
  return profile.status !== 'active' && !profile.pending_activation;
}

interface ProfileFormValues {
  profile_id: string;
  name_zh: string;
  name_en: string;
  scope_type: string;
  scope_value: string;
  enabled: string[];
  weights: Record<string, number>;
  technical: string;
  quant: string;
  external: string;
  aggregator: string;
}

function profileToForm(profile: StrategyProfile): ProfileFormValues {
  return {
    profile_id: profile.profile_id,
    name_zh: profile.name_zh ?? '',
    name_en: profile.name_en ?? '',
    scope_type: profile.scope_type ?? 'default',
    scope_value: profile.scope_value ?? '',
    enabled: profile.enabled ?? [],
    weights: Object.fromEntries(
      Object.entries(profile.weights ?? {}).map(([key, value]) => [key, Number(value) || 0]),
    ),
    technical: JSON.stringify(profile.technical ?? {}, null, 2),
    quant: JSON.stringify(profile.quant ?? {}, null, 2),
    external: JSON.stringify(profile.external ?? {}, null, 2),
    aggregator: JSON.stringify(profile.aggregator ?? {}, null, 2),
  };
}

function parseJsonField(value: string, label: string): Record<string, unknown> {
  try {
    return JSON.parse(value || '{}') as Record<string, unknown>;
  } catch {
    throw new Error(`${label} 参数必须是有效 JSON`);
  }
}

function DraftDiff({ diff }: { diff: ProfileDiffEntry[] }) {
  if (!diff.length) return null;
  return (
    <div className="strategy-draft-banner">
      <Typography.Text strong>待确认变更</Typography.Text>
      <ul style={{ margin: '8px 0 0', padding: 0, listStyle: 'none' }}>
        {diff.map((item) => (
          <li
            key={item.field}
            style={{ display: 'grid', gridTemplateColumns: '84px 1fr 1fr', gap: 6, marginTop: 6 }}
          >
            <span>{item.field}</span>
            <Typography.Text delete type="danger" style={{ overflowWrap: 'anywhere' }}>
              {JSON.stringify(item.before)}
            </Typography.Text>
            <Typography.Text type="success" style={{ overflowWrap: 'anywhere' }}>
              {JSON.stringify(item.after)}
            </Typography.Text>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StrategyMembers({
  definitions,
  enabled,
  onEnabledChange,
}: {
  definitions: StrategyDefinition[];
  enabled: string[];
  onEnabledChange: (ids: string[]) => void;
}) {
  const members = definitions.filter((item) => item.strategy_id !== 'strategy_aggregator');
  return (
    <Row gutter={[8, 8]}>
      {members.map((item) => (
        <Col xs={24} md={8} key={item.strategy_id}>
          <div
            className={`strategy-toggle-row${enabled.includes(item.strategy_id) ? ' is-on' : ''}`}
            style={{
              display: 'grid',
              gridTemplateColumns: 'auto 1fr 72px',
              alignItems: 'center',
              gap: 7,
              padding: 9,
              borderRadius: 5,
            }}
          >
            <Checkbox
              checked={enabled.includes(item.strategy_id)}
              onChange={(e) => {
                const next = e.target.checked
                  ? [...enabled, item.strategy_id]
                  : enabled.filter((id) => id !== item.strategy_id);
                onEnabledChange(next);
              }}
            />
            <div style={{ minWidth: 0 }}>
              <div>{item.name_zh}</div>
              <Typography.Text type="secondary" style={{ fontSize: 10, fontFamily: 'monospace' }}>
                {item.name_en}
              </Typography.Text>
            </div>
            <Form.Item
              name={['weights', item.strategy_id]}
              noStyle
              initialValue={0}
            >
              <InputNumber min={0} step={0.05} size="small" style={{ width: '100%' }} />
            </Form.Item>
          </div>
        </Col>
      ))}
    </Row>
  );
}

export function StrategyWorkspace() {
  const [selectedProfileId, setSelectedProfileId] = useState('default');
  const [localProfiles, setLocalProfiles] = useState<StrategyProfile[] | null>(null);
  const [form] = Form.useForm<ProfileFormValues>();
  const enabledIds = Form.useWatch('enabled', form) ?? [];
  const queryClient = useQueryClient();
  const announce = useUiStore((s) => s.announce);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['strategies'],
    queryFn: ({ signal }) => fetchStrategies(signal),
  });

  const center = data?.strategies;
  const serverProfiles = center?.profiles ?? [];
  const profiles = localProfiles ?? serverProfiles;
  const definitions = center?.definitions ?? [];
  const changes = center?.changes ?? [];

  const profile = useMemo(
    () => profiles.find((item) => item.profile_id === selectedProfileId) ?? profiles[0],
    [profiles, selectedProfileId],
  );

  useEffect(() => {
    if (localProfiles) return;
    if (serverProfiles.length && !serverProfiles.some((item) => item.profile_id === selectedProfileId)) {
      setSelectedProfileId(serverProfiles[0]?.profile_id ?? 'default');
    }
  }, [serverProfiles, selectedProfileId, localProfiles]);

  useEffect(() => {
    if (profile) {
      form.setFieldsValue(profileToForm(profile));
    }
  }, [profile, form]);

  const invalidate = () => {
    setLocalProfiles(null);
    void queryClient.invalidateQueries({ queryKey: ['strategies'] });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: StrategyProfile) => saveStrategyProfile(payload),
    onSuccess: (result) => {
      invalidate();
      if (result.saved_profile_id) setSelectedProfileId(result.saved_profile_id);
      announce('策略组合已保存，等待人工确认。');
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '策略保存失败，请检查参数。');
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (profileId: string) => confirmStrategyProfile(profileId),
    onSuccess: () => {
      invalidate();
      announce('策略组合已确认，下一轮盯盘生效。');
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '策略确认失败。');
    },
  });

  const discardMutation = useMutation({
    mutationFn: (profileId: string) => discardStrategyDraft(profileId),
    onSuccess: () => {
      invalidate();
      announce('策略草稿已撤销，当前生效版本保持不变。');
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '撤销草稿失败。');
    },
  });

  const handleNewProfile = () => {
    const draft = createNewStrategyDraft(serverProfiles);
    setLocalProfiles([draft]);
    setSelectedProfileId('');
  };

  const handleRefresh = () => {
    setLocalProfiles(null);
    void refetch();
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const payload: StrategyProfile = {
        profile_id: values.profile_id.trim(),
        name_zh: values.name_zh.trim(),
        name_en: values.name_en.trim(),
        scope_type: values.scope_type,
        scope_value: values.scope_value.trim(),
        enabled: values.enabled,
        weights: Object.fromEntries(
          Object.entries(values.weights ?? {}).map(([key, value]) => [key, String(value ?? 0)]),
        ),
        technical: parseJsonField(values.technical, '技术指标参数 JSON'),
        quant: parseJsonField(values.quant, '量化参数 JSON'),
        external: parseJsonField(values.external, '外部市场与龙虎榜参数 JSON'),
        aggregator: parseJsonField(values.aggregator, '聚合器参数 JSON'),
      };
      saveMutation.mutate(payload);
    } catch (error) {
      if (error instanceof Error && error.message.includes('JSON')) {
        announce(error.message);
      }
    }
  };

  const activeCount = serverProfiles.filter((item) => item.status === 'active').length;
  const canActOnProfile = Boolean(profile?.profile_id) && profile != null && canConfirmOrDiscard(profile);

  const changeColumns: ColumnsType<StrategyChange> = [
    { title: '组合', dataIndex: 'profile_id', key: 'profile_id' },
    { title: '动作', dataIndex: 'action', key: 'action' },
    { title: '操作人', dataIndex: 'operator', key: 'operator', render: (v) => v ?? '--' },
    { title: '时间', dataIndex: 'created_at', key: 'created_at' },
  ];

  if (isLoading) {
    return <Spin style={{ display: 'block', margin: '48px auto' }} />;
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <Typography.Text type="secondary">
          常用操作集中在当前组合工作区，高级参数按需展开。
        </Typography.Text>
        <Space>
          <Tag>{activeCount} 个生效组合</Tag>
          <Button icon={<ReloadOutlined />} loading={isFetching} onClick={handleRefresh}>
            刷新策略
          </Button>
        </Space>
      </div>

      <Row gutter={[1, 16]} className="strategy-list-shell">
        <Col xs={24} lg={7}>
          <Card
            size="small"
            title="策略组合"
            extra={<Tag>{profiles.length} 个</Tag>}
            styles={{ body: { padding: '12px 8px' } }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
              <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
                选择组合查看和编辑
              </Typography.Paragraph>
              <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={handleNewProfile}>
                新建组合
              </Button>
            </div>
            {profiles.length ? (
              <List
                dataSource={profiles}
                renderItem={(item) => {
                  const selected = item.profile_id === (profile?.profile_id ?? selectedProfileId);
                  const draft = hasDraft(item);
                  return (
                    <List.Item
                      className={`strategy-list-item${selected ? ' is-selected' : ''}`}
                      style={{
                        padding: '8px 10px',
                        marginBottom: 4,
                        borderRadius: 6,
                        cursor: 'pointer',
                      }}
                      onClick={() => setSelectedProfileId(item.profile_id)}
                    >
                      <div style={{ width: '100%' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                          <div>
                            <Typography.Text strong>{item.name_zh || item.profile_id}</Typography.Text>
                            <div>
                              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                                {item.name_en || item.profile_id} · {scopeLabel(item)}
                              </Typography.Text>
                            </div>
                          </div>
                          <Badge
                            status={item.status === 'active' && !item.pending_activation ? 'success' : 'warning'}
                            text={statusLabel(item)}
                          />
                        </div>
                        <Space size={8} className="strategy-meta" style={{ marginTop: 6, fontSize: 10 }}>
                          <span>{(item.enabled ?? []).length} 项策略</span>
                          <span>Revision {item.revision ?? '--'}</span>
                          {draft ? <span className="strategy-draft-flag">有草稿</span> : null}
                        </Space>
                      </div>
                    </List.Item>
                  );
                }}
              />
            ) : (
              <Empty description="暂无策略组合。系统初始化后会生成默认组合。" />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={17}>
          <Card size="small" styles={{ body: { padding: 20 } }}>
            {!profile ? (
              <Empty description="暂无可编辑策略组合。" />
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                  <div>
                    <Typography.Title level={5} style={{ margin: 0 }}>
                      {profile.name_zh || profile.profile_id}
                    </Typography.Title>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {profile.name_en || profile.profile_id} · {scopeLabel(profile)}
                    </Typography.Text>
                  </div>
                  <Space wrap>
                    <Badge
                      status={profile.status === 'active' ? 'success' : 'warning'}
                      text={statusLabel(profile)}
                    />
                    <Button
                      size="small"
                      disabled={!canActOnProfile || discardMutation.isPending}
                      loading={discardMutation.isPending}
                      onClick={() => discardMutation.mutate(profile.profile_id)}
                    >
                      撤销草稿
                    </Button>
                    <Button
                      size="small"
                      disabled={!canActOnProfile || confirmMutation.isPending}
                      loading={confirmMutation.isPending}
                      onClick={() => confirmMutation.mutate(profile.profile_id)}
                    >
                      确认生效
                    </Button>
                  </Space>
                </div>

                <Row gutter={[1, 1]} className="strategy-metric-shell">
                  {[
                    { label: '当前状态', value: statusLabel(profile) },
                    { label: '启用策略', value: `${(profile.enabled ?? []).length} 项` },
                    { label: '配置版本', value: `Revision ${profile.revision ?? '--'}` },
                  ].map((item) => (
                    <Col xs={8} key={item.label}>
                      <div className="strategy-metric-cell">
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          {item.label}
                        </Typography.Text>
                        <div style={{ fontWeight: 650, fontFamily: 'monospace', marginTop: 4 }}>{item.value}</div>
                      </div>
                    </Col>
                  ))}
                </Row>

                <DraftDiff diff={profile.draft_diff ?? []} />

                <Form form={form} layout="vertical" style={{ marginTop: 18 }}>
                  <Typography.Title level={5}>组合信息</Typography.Title>
                  <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 12 }}>
                    用于快速识别和分配适用范围
                  </Typography.Text>
                  <Row gutter={10}>
                    <Col xs={24} md={8}>
                      <Form.Item name="profile_id" label="组合 ID（系统生成）">
                        <Input readOnly={!profile.profile_id} />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="name_zh" label="中文名称">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="name_en" label="English Name">
                        <Input />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="scope_type" label="适用范围">
                        <Select
                          options={[
                            { value: 'default', label: '默认' },
                            { value: 'asset_type', label: '资产类型' },
                            { value: 'symbol', label: '单标的' },
                          ]}
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="scope_value" label="范围值">
                        <Input placeholder="如 etf 或 588170.SH" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item label="当前状态">
                        <Input value={statusLabel(profile)} disabled />
                      </Form.Item>
                    </Col>
                  </Row>

                  <Typography.Title level={5} style={{ marginTop: 8 }}>
                    策略成员与权重
                  </Typography.Title>
                  <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 12 }}>
                    勾选启用，权重支持小数调整
                  </Typography.Text>
                  <StrategyMembers
                    definitions={definitions}
                    enabled={enabledIds}
                    onEnabledChange={(ids) => form.setFieldValue('enabled', ids)}
                  />

                  <Collapse
                    style={{ marginTop: 16 }}
                    items={[
                      {
                        key: 'advanced',
                        label: '高级参数：技术指标、量化、外部市场与聚合器',
                        children: (
                          <Row gutter={10}>
                            {(
                              [
                                ['technical', '技术指标参数 JSON'],
                                ['quant', '量化参数 JSON'],
                                ['external', '外部市场与龙虎榜参数 JSON'],
                                ['aggregator', '聚合器参数 JSON'],
                              ] as const
                            ).map(([name, label]) => (
                              <Col xs={24} md={12} key={name}>
                                <Form.Item name={name} label={label}>
                                  <Input.TextArea rows={6} style={{ fontFamily: 'monospace', fontSize: 11 }} />
                                </Form.Item>
                              </Col>
                            ))}
                          </Row>
                        ),
                      },
                    ]}
                  />

                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      loading={saveMutation.isPending}
                      onClick={() => void handleSave()}
                    >
                      保存为待确认
                    </Button>
                  </div>
                </Form>
              </>
            )}
          </Card>
        </Col>
      </Row>

      {changes.length > 0 ? (
        <Card size="small" title="最近变更" style={{ marginTop: 16 }}>
          <Table
            size="small"
            rowKey={(row) => `${row.profile_id}-${row.created_at}-${row.action}`}
            columns={changeColumns}
            dataSource={changes.slice(0, 20)}
            pagination={false}
          />
        </Card>
      ) : null}
    </div>
  );
}
