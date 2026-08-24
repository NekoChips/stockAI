# StockAI

StockAI 是面向沪深 A 股股票与 ETF 的模拟盘 AI-Agent。它使用公开行情数据进行实时盯盘、策略分析、模拟成交、收盘复盘和 Web 看板展示，不连接券商，也不会提交真实委托。

项目仅用于研究、回测和模拟盘练习，不构成任何投资建议。公开行情源可能存在延迟、限流或数据缺失。

## 主要能力

- 仅支持沪深 A 股股票与 ETF；默认观察池为空，标的需由用户在页面添加并单独启用交易。
- 默认使用 AlphaFeed Python SDK 获取实时行情和历史 K 线，AlphaFeed 失败、限流或未配置 API Key 时自动切换 AKShare；指数和证券目录继续保留公开源 fallback。
- 在交易时段执行技术指标与量化策略，经过风控后写入模拟成交和持仓。
- 策略中心将策略定义、组合、标的分配和变更记录持久化到 MySQL；支持中英文策略指标名称、按标的组合和人工确认后动态生效。
- 策略包含技术、量化、期指仓位、外围市场与龙虎榜信号；外围市场只作为 A 股决策证据，绝不进入持仓、成交或收益统计。数据缺失或超过有效期时，对应策略自动失效。
- 模拟订单有已创建、风控通过、已提交、部分成交、已成交、已拒绝和已取消状态；成交记录关联订单，遵守买入卖一/卖出买一、手续费最低收费、股票卖出印花税、T+1 与涨跌停区间。
- 风险仓位上限和单标的每日操作上限支持页面修改，保存为草稿、人工确认后由下一轮 monitor 生效；新上限不会自动清仓已有持仓。
- 提供数据库日报归档、收益与指数对比、盈亏日历、盈亏排行榜和回测记录。
- Web 看板支持观察池搜索、添加/删除标的、实时价格与当日涨跌幅展示，以及回测候选的人工确认；重复观望信号会自动合并，避免轨道和数据库积压。
- 可从实时持仓或观察池进入标的详情，查看分时、五日、1/5/15/30/60 分钟 K、日 K、周 K、月 K；模拟买入、加减仓和清仓会标记在对应图表，并可悬浮查看成交摘要。
- 发布版使用 MySQL，镜像通过 GitHub Container Registry 发布。
- 开发版默认使用进程内 Mock 数据存储，不依赖 SQLite，也不会落地交易或行情数据；本地验证通过 Mock 行情和单元测试完成。

Web 层按职责拆分为数据组装、写操作、健康检查、HTTP 路由、静态资源和公共响应工具模块；`stock_ai_agent.web` 保留为兼容导入入口。

## v0.1.3 数据结构升级

本版本首次连接 MySQL 时会自动创建订单状态机、决策轨迹、外部市场分析、龙虎榜席位画像及三轨价格表。历史 K 线同时保存原始价、前复权价和复权因子：模拟成交、持仓估值和收益使用原始价；技术指标、趋势与回测使用前复权价。

已有数据库建议在部署新镜像前执行一次下列非破坏性建表脚本；`fills.order_id` 由应用启动时以幂等方式补齐：

```bash
mysql -h <db_ip> -P <db_port> -u <db_user> -p stock_ai \
  < migrations/003_strategy_execution_and_price_tracks.sql
```

收盘后 monitor 自动生成待确认的回测候选；策略组合仍遵循“保存草稿 -> 人工确认 -> 下一轮 monitor 生效”，草稿可撤销，但不提供配置回滚。

## Docker 镜像

最新镜像：

```text
ghcr.io/nekochips/stockai:latest
```

历史版本使用不可变版本标签，例如：

```text
ghcr.io/nekochips/stockai:v0.1.1
```

`latest` 会随 `release` 分支或 `v*` 标签更新；版本标签用于精确部署和回滚。

当前镜像构建会锁定核心依赖版本：AlphaFeed `0.1.4`、AKShare `1.18.94`、PyMySQL `1.1.1`，并以非 root 用户运行。

## 部署前准备

- Docker Engine 和 Docker Compose Plugin。
- 一台可访问的 MySQL，数据库需要提前创建。
- MySQL 账号需要具备建表、建索引、读写和删除权限。
- AlphaFeed API Key；部署时填写 Compose 中的 `ALPHAFEED_API_KEY`。未填写时系统会自动使用 AKShare 备用源。
- GHCR 中的镜像需要是 Public；若为 Private，部署前先登录 GHCR。

仓库中的 [docker-compose.yml](./docker-compose.yml) 是镜像部署文件，直接使用 `ghcr.io/nekochips/stockai:latest`，不需要上传源码或构建镜像。

## NAS 图形界面部署

在 NAS 的容器管理界面创建 Compose 项目：

1. 项目名称填写 `stockai`，选择一个持久化的项目目录。
2. 将 [docker-compose.yml](./docker-compose.yml) 的内容粘贴到 Compose 配置中。
3. 将所有 `CHANGE_ME` 替换为实际 MySQL 配置、`ALPHAFEED_API_KEY`，以及 Web Basic Auth 的账号密码；如数据库端口不是 `3306`，同步修改 `STOCK_AI_MYSQL_PORT`。
4. 如果宿主机 `8765` 端口已占用，将映射左侧端口改成其他端口，例如 `8876:8765`。
5. 点击“立即部署”。

部署后 `web` 会立即提供页面，`monitor` 会在启动阶段仅补齐不足策略门槛的观察池历史 K 线，并在后台增量同步基准指数。观察池 K 线未达到策略计算所需数量时，monitor 不会执行策略或模拟交易，而是保留运行并自动重试。交易时段内 monitor 每 60 秒执行一轮；非交易时段不会保持 60 秒轮询，而是睡眠至下一个交易边界，收盘后先完成 15:05 日报再进入长睡眠。部署完成后访问：

```text
http://NAS地址:8765
```

## 命令行部署

将 `docker-compose.yml` 放入部署目录，替换其中的 MySQL 配置后执行：

```bash
docker compose pull
docker compose up -d --remove-orphans
```

更新到最新镜像：

```bash
docker compose up -d --pull always --remove-orphans
```

修改数据库、端口或其他环境变量后，强制重新创建容器：

```bash
docker compose up -d --pull always --force-recreate --remove-orphans
```

## 版本回滚

将 Compose 中的镜像改为需要的版本，例如：

```yaml
image: ghcr.io/nekochips/stockai:v0.1.0
```

然后重新执行：

```bash
docker compose up -d --pull always --force-recreate --remove-orphans
```

回滚只替换应用容器，不会删除 MySQL 数据。涉及数据库结构变更时，应先确认版本兼容性。

## 状态与日志

```bash
docker compose ps -a
docker compose logs --tail=100 web monitor
```

Web 服务提供轻量健康检查：

```text
http://部署机地址:8765/healthz
```

`/readyz` 还会检查 MySQL 连通性和最近行情是否新鲜；容器编排使用该地址作为就绪探针。MySQL 尚未完成初始化或行情尚未同步时，`readyz` 返回 `503`，这是保护机制，不代表 Web 进程崩溃。

不要使用 `docker compose down -v`，以免误删其他持久化卷。持仓、决策、成交、K 线和日报归档均保存在 MySQL 中，项目不再生成 Markdown 日报文件。除 `/healthz` 外，发布版 Web 页面和 API 均要求 HTTP Basic Auth。

行情与历史 K 线默认先使用 AlphaFeed，并严格按 A 股 Free 套餐做保守限流：实时快照每次最多 5 个标的、日 K 线每次仅 1 个标的；两类接口分别限制为最多 8 次/60 秒、相邻请求至少 7.5 秒，预留 20% 余量。观察池扩容后会自动分片，休眠或未启用交易的标的只保留日 K 同步，不请求实时快照。策略和 Web 优先读取数据库，K 线首次初始化后只从数据库最新日期起同步缺口，常规日 K 更新在收盘日报归档后后台执行，避免盘中反复拉取整段历史。请只运行一个 `monitor` 服务实例，避免多个实例共用同一 API Key 造成重复调用。

交易日历保存在 MySQL 的 `trading_calendar` 表中，统一维护 CN、US、KR 三套市场。每次判断交易日时优先读取数据库，不在 monitor 进程内缓存；仅当数据库缺少对应年份时才从 `exchange_calendars` 获取并回写数据库。策略配置保存在 `strategy_definitions`、`strategy_profiles`、`strategy_change_log` 等表中，策略中心中的保存操作先生成待确认版本，确认后由下一轮 monitor 动态读取。

`market_quotes` 采用当日追加式快照：监控每轮的报价都会入库，实时持仓仅读取每个标的最新一条；交易日首次运行时会先将旧快照归档为一分钟 K，再清理上一个交易日的原始快照。因此标的详情的分时和分钟 K 不会额外调用行情接口，而是由当天已入库快照聚合生成；五日视图由最近五个交易日的归档分钟 K 与当天快照组成。服务重启后，当天已有快照仍可用于查看分时图。

AlphaFeed 调用失败、返回空数据、SDK 缺失、API Key 缺失或触发限流时，系统自动切换 AKShare，历史指数数据还会继续使用现有公开源 fallback。所有源均失败时 monitor 会显示初始化告警并定时重试，避免 Agent 在缺少观察池数据时继续运行。

## 数据库配置

生产环境的数据库地址、端口、数据库名、用户名和密码只填写在部署平台的 Compose 配置中，不要提交到 GitHub。修改配置后使用 `--force-recreate` 重新创建容器，使新环境变量生效。

## MySQL 数值字段迁移

本版本为新建 MySQL 数据库使用 `DECIMAL`、`DATE` 和 `DATETIME(6)`，不再把价格、收益和时间戳保存为 `VARCHAR`。已有数据库升级需要人工执行，应用不会自动执行破坏性 DDL。

请在维护窗口按以下顺序操作：

1. 停止 StockAI 容器，保留 MySQL 数据库运行。
2. 先备份数据库：

   ```bash
   mysqldump -h <db_ip> -P <db_port> -u <db_user> -p \
     --single-transaction --routines --events stock_ai > stock_ai_before_numeric_migration.sql
   ```

3. 确认备份文件可读，再执行仓库中的 `migrations/001_mysql_numeric_datetime.sql`：

   ```bash
   mysql -h <db_ip> -P <db_port> -u <db_user> -p stock_ai \
     < migrations/001_mysql_numeric_datetime.sql
   ```

4. 检查脚本输出中的 `invalid_bars_timestamps`、`invalid_quote_timestamps`、`invalid_fill_timestamps` 均为 `0`，并核对迁移前后的 `bars`、`market_quotes` 行数。
5. 确认 `SHOW CREATE TABLE` 中价格/收益为 `DECIMAL`、日期为 `DATE`、时间戳为 `DATETIME(6)` 后，再启动新镜像：

   ```bash
   docker compose up -d --pull always --force-recreate --remove-orphans
   docker compose ps
   docker compose logs --tail=100 web monitor
   ```

迁移脚本不是幂等脚本，只能对同一数据库执行一次。若校验数量不为 0，请停止后续操作，保留备份并先处理异常时间值。
