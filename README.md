# StockAI

面向沪深 A 股市场的本地模拟盘 AI-Agent。StockAI 使用公开行情数据完成固定观察池的实时盯盘、策略分析、模拟成交、收盘复盘和 Web 驾驶舱展示；不会连接券商或提交真实委托。

> 本项目仅用于研究、回测和模拟盘练习，不构成任何投资建议。公开行情源可能存在延迟、限流、缺失或字段调整，不能据此进行真实交易决策。

## 功能概览

- **沪深市场范围**：仅允许 `SH`、`SZ` 市场的股票与 ETF。
- **AKShare 公开行情**：读取实时行情、历史 K 线、证券目录及主要大盘指数 K 线；指数历史数据具备备用获取路径。
- **可维护观察池**：默认观察 `588170.SH`（科创100ETF基金）和 `588200.SH`（科创芯片ETF基金）；Web 页面支持按六码代码或名称搜索、添加和删除标的。
- **实时盯盘模拟**：在 A 股连续竞价时段按可配置间隔运行，生成决策并由风控模块约束后写入模拟成交和持仓。
- **策略组合**：技术指标与量化策略共同评分，包括趋势、动量、波动率、成交量、时间序列动量、均值回归、相对强弱轮动、波动率目标和回撤控制。
- **风险控制**：限制单标的仓位、总仓位、现金比例、最大回撤、单日成交次数，并处理 A 股 T+1 可卖数量和最小交易单位。
- **自动回测优化**：基于本地历史 K 线生成候选参数与回测指标；候选记录默认处于“待人工确认”状态。
- **收盘日报**：每天收盘后将账户、持仓、成交、策略证据和次日关注点追加到同一份本地 Markdown 文件，以日期标题分隔。
- **Web 驾驶舱**：展示账户概览、决策轨道、实时持仓、收益与指数对比、跑赢/跑输分析、盈亏日历、盈亏排行榜、模拟成交和回测记录。

## 技术架构

```text
AKShare / 备用公开数据源
        |
        v
行情适配器 -> 可切换持久化存储 -> 特征、策略聚合与风控 -> 模拟经纪商
                                  |                    |
                                  v                    v
                             回测候选             决策、成交、持仓
                                  \                    /
                                   v                  v
                              Markdown 日报 / Web 驾驶舱
```

默认使用 SQLite，数据访问通过存储接口抽象；后续可以实现相同接口来替换为 MySQL 或其他数据库，而无需重写策略与页面逻辑。

## 环境与数据管理

| 环境 | 配置文件 | 存储 | 使用方式 |
| --- | --- | --- | --- |
| 开发版 | `config/default.yaml` | SQLite | 本地开发、单元测试与日常模拟盘验证。 |
| 发布版 | `config/release.container.yaml` | MySQL | Docker 容器通过环境变量连接 MySQL，并自动初始化所需表结构。 |

发布版配置采用继承方式：`config/release.example.yaml` 是本机或非容器运行时的可提交模板，`config/release.local.yaml` 是本机私有文件。Docker 发布版读取 `config/release.container.yaml`，由 `docker/.env.release` 注入 MySQL 地址、端口、数据库、用户名与密码。

`config/*.local.yaml` 与 `config/*.secret.yaml` 已被 `.gitignore` 忽略。不要把发布数据库凭据写入 `default.yaml`、`release.example.yaml`、README、日志或 Git 提交。

MySQL 适配器仅在发布进程首次访问存储时延迟加载并建立连接，随后自动创建需要的表和索引。开发与单元测试仍默认使用 SQLite，不会加载或连接 MySQL。

## 镜像发布与 Docker Compose 部署

生产部署从 GitHub Container Registry（GHCR）拉取镜像，部署机不再构建源码。[docker-compose.yml](./docker-compose.yml) 可直接粘贴到 NAS 图形界面，也可用于命令行部署。已有的 `docker-compose.release.yml` 仅作为离线环境或镜像仓库不可用时的本地构建备用方案。

### 镜像发布规则

[publish-image.yml](./.github/workflows/publish-image.yml) 会构建 `linux/amd64` 与 `linux/arm64` 镜像并推送至 `ghcr.io/nekochips/stockai`：

- 推送到 `develop`：发布 `develop` 与对应的 `sha-*` 镜像。
- 推送到 `release`：发布 `release`、`latest` 与对应的 `sha-*` 镜像。
- 推送 `v*` Git 标签：发布版本标签、`latest` 与对应的 `sha-*` 镜像。
- GitHub Actions 页面也支持手动执行工作流。

生产环境默认使用 `latest`，测试环境使用 `develop`，需要精确发布或回滚时使用 `v0.1.0` 一类不可变版本标签。首次发布后应在 GitHub Packages 中确认镜像为 Public；若保持 Private，部署机需先使用具有 `read:packages` 权限的令牌执行 `docker login ghcr.io`。

### NAS 图形界面直接部署

这种方式不需要上传源码或发布压缩包。在 NAS 的容器管理界面创建 Compose 项目：

1. 项目名称填写 `stockai`。
2. 存放路径选择共享文件夹中的项目目录，例如 `共享文件夹/docker/stockai`。
3. 将 [docker-compose.yml](./docker-compose.yml) 的完整内容粘贴到“Compose配置”，或者通过“导入”选择该文件。
4. 在编辑器中替换全部 `CHANGE_ME`，分别填写 MySQL 地址、数据库名、用户名和密码，并保留值两侧的双引号；端口不是 `3306` 时一并修改 `STOCK_AI_MYSQL_PORT`。
5. 如宿主机端口 `8765` 已占用，将 `"8765:8765"` 左侧的端口改成其他端口，例如 `"8876:8765"`。
6. 勾选“创建完成后立即运行”，然后点击“立即部署”。

模板直接使用 `ghcr.io/nekochips/stockai:latest`，包含 Web、实时盯盘和一次性初始化服务。`bootstrap` 会同步证券目录、观察池历史 K 线和基准指数，执行完成后以状态码 `0` 停止，这是正常状态；`web` 和 `monitor` 会持续运行。

MySQL 目标数据库需要提前创建，账户需要具备建表、建索引、读写和删除权限。真实数据库凭据只填写在 NAS 项目编辑器中，不要回写到仓库里的模板。Markdown 日报会保存在所选项目路径的 `reports/` 目录，交易、持仓、观察池和回测数据保存在外部 MySQL。

部署完成后访问 `http://NAS地址:8765`。若 GHCR 镜像不是 Public，需要先在 NAS 的镜像仓库设置中配置具有 `read:packages` 权限的 GitHub 凭据，否则项目无法拉取镜像。

### NAS 图形界面更新

GitHub Actions 发布新的 `latest` 镜像后，在 NAS 项目界面停止项目并执行重新构建或重新部署。模板设置了 `pull_policy: always`，部署时会拉取最新镜像；MySQL 数据和项目目录下的 `reports/` 不会随容器重建而删除。

需要回滚时，将 Compose 中的镜像标签从 `latest` 改成之前的版本标签，例如 `ghcr.io/nekochips/stockai:v0.1.0`，然后重新部署项目。

### 命令行服务器部署

命令行部署机需要 Docker Engine 与 Docker Compose Plugin。将 `docker-compose.yml` 放入部署目录，替换其中全部 `CHANGE_ME` 后执行：

```bash
docker compose pull
docker compose up -d --remove-orphans
```

`bootstrap` 会自动完成首次数据初始化。浏览器访问 `http://部署机地址:8765`。

### 从旧版部署迁移

之前通过 `docker-compose.release.yml` 在服务器构建镜像的部署，需要先在旧发布目录停止旧服务。不要添加 `-v`，避免误删 Docker 卷：

```bash
docker compose -f docker-compose.release.yml down
```

将旧目录中的 `runtime/reports/` 迁移到新发布目录的 `reports/`，然后按“命令行服务器部署”执行。外部 MySQL 数据不会随容器停止而删除。确认新服务正常后，旧源码目录和旧本地镜像可以自行归档或删除。

### 命令行一键更新

新镜像发布后，在部署目录执行一条命令即可拉取镜像并重建变化的服务：

```bash
docker compose up -d --pull always --remove-orphans
```

更新不会清空 MySQL，也不会删除 `runtime/reports/`。查看服务、健康状态和日志：

日常业务代码更新只需要发布新镜像并执行上述命令；只有 `docker-compose.yml` 或发布环境变量结构发生变化时，才需要同步新的部署文件。

```bash
docker compose ps
docker compose logs --tail=100 monitor web bootstrap
```

修改 MySQL、端口或其他环境变量后，使用 `--force-recreate` 让容器重新读取配置：

```bash
docker compose up -d --pull always --force-recreate --remove-orphans
```

### 命令行版本回滚

将 `docker-compose.yml` 中的镜像标签改为上一个版本，例如 `ghcr.io/nekochips/stockai:v0.1.0`，然后再次执行一键更新命令。回滚只替换应用容器，不会回滚或删除 MySQL 数据；涉及数据库结构变更时必须先确认版本兼容性。

### 本地构建备用方案

无法访问 GHCR 时可以在部署机使用源码构建：

```bash
docker compose --env-file docker/.env.release -f docker-compose.release.yml up -d --build --remove-orphans
```

如需生成完整发布压缩包，可执行 `sh scripts/package-release.sh 0.1.0-mysql`。脚本会排除敏感配置、运行数据和 macOS 扩展属性，避免 Linux 解压时出现 `LIBARCHIVE.xattr.*` 告警。

## 环境要求

- Python 3.9 或更高版本
- 可访问 AKShare 所依赖的公开行情接口

安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

项目未安装为包时，也可以在命令前加 `PYTHONPATH=src`。

## 快速开始

以下命令默认使用 [config/default.yaml](./config/default.yaml)。首次使用建议按顺序初始化证券目录、观察池历史 K 线和基准指数 K 线：

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app sync-instruments --config config/default.yaml
PYTHONPATH=src python3 -m stock_ai_agent.app sync-history --config config/default.yaml
PYTHONPATH=src python3 -m stock_ai_agent.app sync-benchmarks --config config/default.yaml
```

启动本地 Web 驾驶舱：

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app web --config config/default.yaml --host 127.0.0.1 --port 8766
```

浏览器访问 [http://127.0.0.1:8766](http://127.0.0.1:8766)。页面中可以维护观察池、查看当前模拟持仓和收益分析，并确认回测候选记录。

启动实时盯盘模拟：

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app monitor --config config/default.yaml
```

默认只在工作日 `09:30-11:30` 与 `13:00-15:00`（`Asia/Shanghai`）执行交易迭代。用于本地验证时可限制执行轮数并忽略交易时段：

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app monitor \
  --config config/default.yaml \
  --max-iterations 1 \
  --ignore-market-hours
```

## CLI 命令

| 命令 | 用途 |
| --- | --- |
| `sync-instruments` | 同步沪深股票与 ETF 全量目录到当前配置的数据存储，供代码搜索和名称联想使用。 |
| `sync-history` | 同步当前有效观察池的历史日 K 线。 |
| `sync-benchmarks` | 同步上证指数、深证成指、沪深300、创业板指、科创50的历史日 K 线。 |
| `run-once` | 基于已保存的 K 线和最新行情执行一次模拟分析，并生成日报。 |
| `monitor` | 按轮询间隔进行实时盯盘模拟；收盘后自动生成日报。 |
| `post-close` | 使用当天持久化的决策、成交与组合状态补生成收盘日报。 |
| `optimize-strategy` | 对本地历史数据执行参数网格回测，保存待人工确认的候选。 |
| `web` | 启动本地 Web 驾驶舱。 |

公共参数：

- `--config`：配置文件路径，默认 `config/default.yaml`。
- `--reports`：日报输出目录，默认 `reports`。
- `--poll-seconds`：覆盖实时盯盘轮询秒数。
- `--max-iterations`：限制盯盘执行轮数。
- `--ignore-market-hours`：仅用于本地验证，忽略交易时段限制。
- `--host`、`--port`：Web 服务监听地址与端口。

## 配置说明

主要配置位于 [config/default.yaml](./config/default.yaml)：

- `data.provider` 与 `data.history_provider`：当前默认为 `akshare`，可配置为其他已实现的行情适配器。
- `storage`：默认 SQLite 文件为 `data/stock_ai_agent.sqlite3`。
- `storage.backup_dir`：SQLite 备份目录，默认 `data/backups`。
- `storage.mysql`：发布版 MySQL 的 `host`、`port`、`database`、`username`、`password`；只应存在于被忽略的本地发布配置中。
- `universe`：默认固定观察池；页面添加的标的会持久化到本地并合并进有效观察池。
- `benchmarks`：收益分析使用的五个 A 股主要指数。
- `monitor`：轮询时间、收盘日报时间、交易时段约束与 T+1 结算开关。
- `paper_account`：初始资金、手续费率与滑点率。
- `risk`：仓位、现金、回撤和日内成交限制。
- `strategy.weights` 与 `strategy.quant`：技术信号与量化策略的权重、回看周期、均值回归阈值、回撤止损和冷却期等参数。

修改参数后，建议重新执行 `sync-history`、`sync-benchmarks` 或 `optimize-strategy`，并在页面中审查新的模拟结果。

## Web 驾驶舱

交易看板包含：

- 当前模拟资产、现金、仓位、当日收益率、决策数、成交数和刷新时间。
- 决策轨道，按行情订阅、信号扫描、风险复核、模拟订单展示当前执行状态。
- 实时持仓和观察池管理。观察池搜索优先查询本地证券目录，避免每次输入都请求全市场数据。
- 盈亏分析：支持当年、当月、自定义时间区间；日期区间选择框始终显示，切换预设区间时会同步更新起止日期，手动选择日期则自动进入自定义模式。所有曲线以选定起始日为 0 基准，比较 AI-Agent 与五个指数，并展示最新跑赢/跑输差值。
- 盈亏日历：支持月度每日收益/收益率和年度逐月汇总；无操作日期按 0 统计，可选择数据范围内的历史月份或年份。
- 盈亏排行榜：支持按盈亏金额、收益率、持仓天数排序。
- 回测记录：展示策略、参数、指标和状态；支持批量人工确认，不展示策略源代码。

## 本地数据与日报

- SQLite 数据库：`data/stock_ai_agent.sqlite3`。
- Markdown 日报：`reports/daily_reports.md`。同一交易日会覆盖对应日期段，新的交易日会追加新的一级标题。
- 证券目录每日在实时盯盘后台同步；指数历史数据也会在后台尝试同步，失败不会阻塞当轮策略计算。

发布版数据保存在 MySQL。请使用部署环境的数据库备份策略或 MySQL 原生备份工具保护发布数据；SQLite 的 `backup-data` 和 `restore-data` 命令仅适用于开发版。

这些本地运行产物已在 `.gitignore` 中排除，不会被默认提交到版本库。

### SQLite 备份与恢复

SQLite 数据库位于 `data/stock_ai_agent.sqlite3`，项目重启时会继续使用同一文件，不会自动清空数据。请定期执行备份，尤其是在升级代码、调整策略或恢复操作前：

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app backup-data --config config/default.yaml
```

备份默认保存到 `data/backups/`，文件名包含 UTC 时间戳。备份使用 SQLite 原生备份 API，并在完成前执行完整性校验。

恢复前先停止 `monitor` 和 `web` 进程，再指定备份文件：

```bash
PYTHONPATH=src python3 -m stock_ai_agent.app restore-data \
  --config config/default.yaml \
  --backup-file data/backups/stock_ai_agent-YYYYMMDDTHHMMSSffffffZ.sqlite3
```

恢复过程会先为当前数据库创建一份回滚备份；只有待恢复文件通过 SQLite 完整性校验后，才会以原子替换方式写入目标数据库。`backup-data` 和 `restore-data` 目前只支持 SQLite 开发环境。

## 测试

执行完整单元测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

当前测试覆盖行情适配、指标计算、技术与量化策略、风控、模拟经纪商、SQLite、MySQL 发布配置校验、观察池、回测、日报、实时盯盘和 Web 数据接口。

## 已知边界

- 公开数据源会受网络、限流与字段变化影响。目录和指数历史数据有备用获取路径，但部署环境仍建议接入稳定的数据服务。
- 历史 K 线用于研究与回测，不能替代逐笔数据或交易所正式行情。
- 系统当前是模拟盘，不含券商登录、真实账户资产读取或真实下单能力。
- 回测候选与策略参数需要人工审查后再确认；确认操作不会自动触发真实交易。

## README 维护约定

后续凡是新增、删除或调整以下内容时，必须在同一变更中同步更新本 README：

- 用户可见功能、页面交互与可视化口径。
- CLI 命令、配置项、默认观察池、数据源或存储方式。
- 策略、风险控制、回测、日报和模拟成交的行为。
- 环境要求、启动方式、测试方式和已知限制。
- 开发版/发布版划分、备份恢复流程与敏感配置处理方式。
- Docker 镜像、Compose 编排、发布包与生产部署流程。

每次变更应确保 README 的命令、配置说明和功能描述仍与代码一致。

## 仓库内容约定

GitHub 仓库只保留项目业务源码、测试、正式文档、可提交的配置模板、数据库适配器、Docker 部署文件和发布脚本。以下内容仅供本地开发辅助，不进入版本库：

- 本地 AI Agent、Skill、编辑器和设计系统目录。
- `design.md`、`plan.md`、`review.md`、`final_report.md` 等过程文档。
- OpenSpec 过程文件、运行日志、学习记录和构建发布包。
- SQLite 数据、备份、日报、虚拟环境及包含敏感信息的本地配置。

若新增其他开发辅助工具，应同步补充 `.gitignore`，并确认不会误排除业务代码、测试或正式部署文件。
