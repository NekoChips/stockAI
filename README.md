# StockAI

StockAI 是面向沪深 A 股股票与 ETF 的模拟盘 AI-Agent。它使用公开行情数据进行实时盯盘、策略分析、模拟成交、收盘复盘和 Web 看板展示，不连接券商，也不会提交真实委托。

项目仅用于研究、回测和模拟盘练习，不构成任何投资建议。公开行情源可能存在延迟、限流或数据缺失。

## 主要能力

- 仅支持沪深 A 股股票与 ETF，默认观察 `588170.SH` 和 `588200.SH`。
- 默认使用 AlphaFeed Python SDK 获取实时行情和历史 K 线，AlphaFeed 失败、限流或未配置 API Key 时自动切换 AKShare；指数和证券目录继续保留公开源 fallback。
- 在交易时段执行技术指标与量化策略，经过风控后写入模拟成交和持仓。
- 提供数据库日报归档、收益与指数对比、盈亏日历、盈亏排行榜和回测记录。
- Web 看板支持观察池搜索、添加/删除标的，以及回测候选的人工确认。
- 发布版使用 MySQL，镜像通过 GitHub Container Registry 发布。

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
3. 将所有 `CHANGE_ME` 替换为实际 MySQL 配置和 `ALPHAFEED_API_KEY`；如数据库端口不是 `3306`，同步修改 `STOCK_AI_MYSQL_PORT`。
4. 如果宿主机 `8765` 端口已占用，将映射左侧端口改成其他端口，例如 `8876:8765`。
5. 点击“立即部署”。

部署后 `web` 会立即提供页面，`monitor` 会在启动阶段仅补齐不足策略门槛的观察池历史 K 线，并在后台增量同步基准指数。观察池 K 线未达到策略计算所需数量时，monitor 不会执行策略或模拟交易，而是保留运行并自动重试。部署完成后访问：

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

不要使用 `docker compose down -v`，以免误删其他持久化卷。持仓、决策、成交、K 线和日报归档均保存在 MySQL 中，项目不再生成 Markdown 日报文件。

行情与历史 K 线默认先使用 AlphaFeed，并严格按 A 股 Free 套餐做保守限流：实时快照每次最多 5 个标的、日 K 线每次仅 1 个标的；两类接口分别限制为最多 8 次/60 秒、相邻请求至少 7.5 秒，预留 20% 余量。默认两只观察池 ETF 每轮只发送 1 次快照请求；观察池扩容后会自动分片。策略和 Web 优先读取数据库，K 线首次初始化后只从数据库最新日期起同步缺口，常规日 K 更新在收盘日报归档后后台执行，避免盘中反复拉取整段历史。请只运行一个 `monitor` 服务实例，避免多个实例共用同一 API Key 造成重复调用。

AlphaFeed 调用失败、返回空数据、SDK 缺失、API Key 缺失或触发限流时，系统自动切换 AKShare，历史指数数据还会继续使用现有公开源 fallback。所有源均失败时 monitor 会显示初始化告警并定时重试，避免 Agent 在缺少观察池数据时继续运行。

## 数据库配置

生产环境的数据库地址、端口、数据库名、用户名和密码只填写在部署平台的 Compose 配置中，不要提交到 GitHub。修改配置后使用 `--force-recreate` 重新创建容器，使新环境变量生效。
