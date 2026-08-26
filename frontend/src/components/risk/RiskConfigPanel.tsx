import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Form,
  InputNumber,
  Row,
  Space,
  Typography,
} from 'antd';
import { confirmRiskConfig, saveRiskConfig } from '@/api/risk';
import { useUiStore } from '@/stores/uiStore';
import type { JsonDecimal, OverviewPayload, RiskConfig } from '@/types/dashboard';
interface RiskConfigPanelProps {
  risk: RiskConfig;
}

const PCT_FIELDS: { key: keyof RiskConfig; label: string; help?: string }[] = [
  { key: 'max_symbol_weight', label: '单只标的总上限', help: '所有单标的共同上限' },
  { key: 'max_etf_weight', label: '单只 ETF 上限' },
  { key: 'max_stock_weight', label: '单只股票上限' },
  { key: 'max_etf_total_weight', label: 'ETF 总仓位上限' },
  { key: 'max_stock_total_weight', label: '个股总仓位上限' },
  { key: 'max_total_exposure', label: '组合总仓位上限' },
  { key: 'min_cash_ratio', label: '最低现金比例' },
];

const THRESHOLD_FIELDS: { key: keyof RiskConfig; label: string }[] = [
  { key: 'max_drawdown', label: '组合最大回撤' },
  { key: 'single_position_loss', label: '单标的止损阈值' },
  { key: 'trailing_drawdown', label: '移动回撤阈值' },
  { key: 'portfolio_daily_loss', label: '组合单日亏损阈值' },
  { key: 'high_atr_ratio', label: '高波动 ATR 阈值' },
];

function pctDisplay(value: JsonDecimal | undefined): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(0)}%` : '--';
}

function riskFormValues(risk: RiskConfig): Record<string, number | undefined> {
  const keys = [
    ...PCT_FIELDS.map((f) => f.key),
    ...THRESHOLD_FIELDS.map((f) => f.key),
    'max_operations_per_symbol',
  ] as const;
  return Object.fromEntries(
    keys.map((key) => {
      const raw = risk[key];
      const n = Number(raw);
      return [key, Number.isFinite(n) ? n : undefined];
    }),
  );
}

export function RiskConfigPanel({ risk }: RiskConfigPanelProps) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const announce = useUiStore((s) => s.announce);

  useEffect(() => {
    form.setFieldsValue(riskFormValues(risk));
  }, [risk, form]);

  const patchOverview = (risk_config: RiskConfig) => {
    queryClient.setQueryData(['overview'], (old: OverviewPayload | undefined) =>
      old ? { ...old, risk_config } : old,
    );
  };

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, JsonDecimal>) => saveRiskConfig(payload),
    onSuccess: (result) => {
      patchOverview(result.risk_config);
      announce('风险配置已保存，等待人工确认。');
    },
    onError: (error) => {
      announce(
        error instanceof Error && error.message
          ? error.message
          : '风险配置保存失败，请检查输入。',
      );
    },
  });

  const confirmMutation = useMutation({
    mutationFn: () => confirmRiskConfig(),
    onSuccess: (result) => {
      patchOverview(result.risk_config);
      setEditorOpen(false);
      announce('风险配置已确认，下一轮盯盘生效。');
    },
    onError: (error) => {
      announce(error instanceof Error && error.message ? error.message : '风险配置确认失败。');
    },
  });

  const pending = Boolean(risk.pending_confirmation);
  const statusLabel = pending ? '待人工确认' : '当前生效';

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, value ?? '']),
    ) as Record<string, JsonDecimal>;
    saveMutation.mutate(payload);
  };

  const pctField = (key: keyof RiskConfig, label: string, help?: string) => (
    <Form.Item
      key={key}
      name={key}
      label={label}
      help={help}
      rules={[{ required: true, message: '请输入' }]}
    >
      <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} addonAfter="%" />
    </Form.Item>
  );

  return (
    <Card
      title="仓位与执行约束"
      extra={
        <Space wrap>
          <Badge status={pending ? 'warning' : 'success'} text={statusLabel} />
          <Button size="small" onClick={() => setEditorOpen((open) => !open)}>
            {editorOpen ? '收起编辑' : '编辑约束'}
          </Button>
          <Button
            size="small"
            disabled={!pending || confirmMutation.isPending}
            loading={confirmMutation.isPending}
            onClick={() => confirmMutation.mutate()}
          >
            确认配置
          </Button>
        </Space>
      }
      style={{ marginBottom: 20 }}
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        先看关键边界，需要调整时再展开编辑；系统硬上限不可突破。
      </Typography.Paragraph>
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={6}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            组合总仓位
          </Typography.Text>
          <div style={{ fontWeight: 650, fontSize: 18 }}>{pctDisplay(risk.max_total_exposure)}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            最低现金 {pctDisplay(risk.min_cash_ratio)}
          </Typography.Text>
        </Col>
        <Col xs={12} sm={6}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            ETF 容量
          </Typography.Text>
          <div style={{ fontWeight: 650, fontSize: 18 }}>
            单只 {pctDisplay(risk.max_etf_weight)}
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            组合合计 {pctDisplay(risk.max_etf_total_weight)}
          </Typography.Text>
        </Col>
        <Col xs={12} sm={6}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            个股容量
          </Typography.Text>
          <div style={{ fontWeight: 650, fontSize: 18 }}>
            单只 {pctDisplay(risk.max_stock_weight)}
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            组合合计 {pctDisplay(risk.max_stock_total_weight)}
          </Typography.Text>
        </Col>
        <Col xs={12} sm={6}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            执行频率
          </Typography.Text>
          <div style={{ fontWeight: 650, fontSize: 18 }}>
            {risk.max_operations_per_symbol ?? '--'} 笔 / 日
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            单个标的操作上限
          </Typography.Text>
        </Col>
      </Row>
      {editorOpen ? (
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Collapse
            defaultActiveKey={['capacity', 'threshold', 'execution']}
            items={[
              {
                key: 'capacity',
                label: '仓位容量',
                children: (
                  <>
                    <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
                      限制组合和单类资产的资金占用
                    </Typography.Paragraph>
                    <Row gutter={16}>
                      {PCT_FIELDS.map((f) => (
                        <Col xs={24} sm={12} key={f.key}>
                          {pctField(f.key, f.label, f.help)}
                        </Col>
                      ))}
                    </Row>
                  </>
                ),
              },
              {
                key: 'threshold',
                label: '风险阈值',
                children: (
                  <>
                    <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
                      触发降仓、止损或暂停信号的边界
                    </Typography.Paragraph>
                    <Row gutter={16}>
                      {THRESHOLD_FIELDS.map((f) => (
                        <Col xs={24} sm={12} key={f.key}>
                          {pctField(f.key, f.label)}
                        </Col>
                      ))}
                    </Row>
                  </>
                ),
              },
              {
                key: 'execution',
                label: '执行约束',
                children: (
                  <>
                    <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
                      避免同一标的在短时间内反复操作
                    </Typography.Paragraph>
                    <Form.Item
                      name="max_operations_per_symbol"
                      label="单标的每日操作上限"
                      help="限制单个标的一天内的交易动作数量"
                      rules={[{ required: true, message: '请输入' }]}
                    >
                      <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} addonAfter="笔" />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
          <Button type="primary" loading={saveMutation.isPending} onClick={() => void handleSave()}>
            保存为待确认
          </Button>
        </Form>
      ) : null}
    </Card>
  );
}
