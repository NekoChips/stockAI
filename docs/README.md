# StockAI 文档规范

本文档是项目文档的唯一导航入口。除项目根目录的 `README.md`（面向部署和快速了解项目）外，设计、方案、规格、复核和发布记录统一存放在本目录。

## 目录职责

```text
docs/
├── README.md       # 本规范与文档索引
├── product/        # 产品边界、业务规则、用户流程
├── architecture/   # 系统架构、模块边界、长期技术决策
├── design/         # 前端设计系统、交互规范、验收清单
├── specs/          # 功能规格、接口约束、数据源约束
├── plans/          # 待实施或实施中的改造计划
├── operations/     # 运维、迁移、故障处理和发布操作手册
├── reviews/        # 代码复核、验收和问题清单
├── releases/       # 已发布版本的变更记录
└── archive/        # 已废弃或被新文档替代的资料
```

目录不是按工具或参与者划分，而是按文档的生命周期职责划分：

| 目录 | 应回答的问题 | 主要读者 |
| --- | --- | --- |
| `product` | 系统要解决什么问题，哪些行为被允许？ | 产品、验收、开发 |
| `architecture` | 模块如何协作，哪些边界不能被绕过？ | 开发、评审 |
| `design` | 页面和交互应该长什么样，如何验收？ | 前端、设计、验收 |
| `specs` | 功能或数据源的精确约束是什么？ | 开发、测试 |
| `plans` | 如何分阶段实施，完成标准是什么？ | 开发、评审 |
| `operations` | 如何部署、迁移、排障和恢复？ | 运维、发布 |
| `reviews` | 当前实现有哪些问题，验证结论是什么？ | 开发、评审 |
| `releases` | 某个版本交付了什么，升级有什么注意事项？ | 发布、运维、用户 |
| `archive` | 为什么保留这份旧资料，它被什么取代？ | 追溯、审计 |

## 命名规范

### 普通文档

统一使用：

```text
YYYY-MM-DD-topic.md
```

示例：

```text
2026-08-26-code-issues-remediation.md
2026-08-26-alphafeed-external-market.md
2026-08-26-function-governance-design.md
```

命名要求：

- 日期使用文档首次建立或形成当前基线的日期，格式固定为四位年、两位月、两位日。
- `topic` 使用小写英文和短横线，避免空格、下划线、中文和含义不清的缩写。
- 文件名描述主题，不把作者、工具名或临时状态放进文件名。
- 文档后续修改不改文件名日期；在文档元信息中更新 `updated` 日期。
- `docs/README.md` 是导航入口的固定例外，不加日期。
- 发布记录使用版本号作为稳定标识，例如 `docs/releases/v0.1.3.md`，不重复加日期。

### 文档元信息

新建文档应在标题后维护以下信息；历史迁移文档保留原文，下一次修改时补齐：

```markdown
**状态：** draft | active | implemented | superseded | archived
**负责人：** <team-or-role>
**创建日期：** 2026-08-26
**更新日期：** 2026-08-26
**关联：** `<related-doc-path>`
```

状态含义：

- `draft`：草稿，尚未形成可执行结论。
- `active`：当前生效，后续实现或运维应以此为准。
- `implemented`：已实现，保留用于验收和追溯。
- `superseded`：被新文档替代，但仍有历史参考价值。
- `archived`：已归档，不再作为实现依据。

## 维护规则

1. 新需求先进入 `product` 或 `specs`，需要分阶段实施时再建立 `plans` 文档。
2. 设计文档只描述目标体验和验收标准；代码中的 token、接口和数据库结构分别以代码、接口实现和迁移脚本为最终事实来源。
3. 实施完成后，将计划状态更新为 `implemented`，并补充对应的 `reviews` 或 `releases` 记录。
4. 新文档替代旧文档时，旧文档状态改为 `superseded`，移动到 `docs/archive/`，并在旧文档或新文档中写明替代关系。
5. 同一主题只保留一个当前生效文档，避免同时维护多个“最终版”“最新方案”文件。
6. 运维脚本、数据库迁移和部署配置的具体命令应放在 `operations`，不要只写在聊天记录或临时计划中。
7. 文档引用使用相对路径；迁移文件后必须全局搜索旧路径并同步更新。
8. 文档提交前至少检查 Markdown 链接、状态、日期、示例命令和敏感信息，禁止提交真实密码、API Key 或生产连接串。

## 当前文档索引

### 架构与设计

- [功能治理与模块拆分设计](./architecture/2026-08-26-function-governance-design.md)
- [前端设计系统](./design/2026-08-26-design-system.md)
- [SPA 前端功能验收清单](./design/2026-08-25-frontend-parity-checklist.md)
- [决策事件摘要与原始审计分离设计](./design/2026-08-26-decision-event-audit-separation.md)

### 产品

- [决策事件治理与摘要审计分离产品需求](./product/2026-08-26-decision-event-governance.md)

### 规格与实施计划

- [React + Ant Design SPA 规格](./specs/2026-08-25-react-antd-spa-design.md)
- [双主题与交互增强规格](./specs/2026-08-26-dual-theme-ux-design.md)
- [AlphaFeed 海外市场数据规格](./specs/2026-08-26-alphafeed-external-market.md)
- [策略设计规格](./specs/2026-08-21-strategy-design.md)
- [React + Ant Design SPA 实施计划](./plans/2026-08-25-react-antd-spa.md)
- [项目优化计划](./plans/2026-08-21-optimization.md)
- [交易看板第二阶段加载优化](./plans/2026-08-26-dashboard-loading-optimization.md)
- [策略系统整体实施计划](./plans/2026-08-26-strategy-implementation.md)
- [代码问题整改计划](./plans/2026-08-26-code-issues-remediation.md)
- [功能治理与模块拆分实施计划](./plans/2026-08-26-function-governance.md)
- [双主题与交互增强实施计划](./plans/2026-08-26-dual-theme-ux.md)

### 复核与发布

- [代码问题审查](./reviews/2026-08-25-code-issues-review.md)
- [策略实现审阅](./reviews/2026-08-24-strategy-implementation-review.md)
- [功能治理实施复核](./reviews/2026-08-26-function-governance-review.md)
- [v0.1.3 发布记录](./releases/v0.1.3.md)

### 运维

- [决策事件维护](./operations/2026-08-26-decision-event-maintenance.md)

## 归档说明

本次整理将历史根目录方案和原 `docs/superpowers`、`docs/design-system` 路径下的资料迁移到上述 canonical 目录，内容不做业务改写。后续不再新增这些旧目录；被替代的文档统一进入 `docs/archive/`，并保留替代关系和原始日期，便于回溯。
