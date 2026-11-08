# RING 部署指南（deploy/）

两条路，同一套组件、同一份数据布局：

| 路径 | 目录 | 适合谁 | 复杂度 |
| --- | --- | --- | --- |
| **A. Docker Compose**（推荐） | `deploy/compose/` | 想最快看到机器人说话的人；一台干净 VPS；不想碰 systemd | 一条命令 + 两次扫码 |
| **B. Ansible 裸机** | `deploy/ansible/` | 要和当前生产一致（uv tool + systemd + 容器跑 NapCat）；已有 ansible 流程 | 一条 playbook |

> 完整手册（架构图、端口表、环境变量表、升级/回滚/备份/卸载）在 [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md)。
>
> 两条路径都已在真实服务器上用**影子栈**验证过（compose 解析、三个镜像构建、四个 health 端点 200、
> 补丁在镜像内生效、Ansible `--syntax-check`），实测日志与前后状态对比见
> [`deploy/compose/VERIFICATION.md`](./compose/VERIFICATION.md)。

## 我该用哪个？

- **只有 2G 内存、一台机器、想跑起来** → Compose，只开 `core` profile。
- **要 HTTPS 域名、要反代** → Compose + `edge` profile（内置 Caddy 自动证书）。
- **要对齐现有生产（systemd、MemoryMax、uv tool、NapCat 容器）** → Ansible。
- **要多机拆分（数据库/记忆库单独一台）** → 目前不支持，两条路径都是单机；拆分需要自己改 compose 的网络与端口。

## 路径 A：Docker Compose

### 前置条件

- Linux（Debian 12+ / Ubuntu 22.04+ 验证过），**Docker Engine 24+ 与 compose v2**
  （Debian/Ubuntu：`apt install docker.io docker-compose-plugin`，或 [官方脚本](https://docs.docker.com/engine/install/)）
- 最低 2 GB 内存 + 2 GB swap；建议 4 GB
- 磁盘 ≥ 15 GB（实测：四个自研镜像合计 **2.58 GB**，外套 NapCat 1.47 GB + Caddy 约 60 MB，
  再加数据目录；预留 15 GB 是给备份、日志和升级时的双层镜像）
- 一个 QQ 号（NapCat 扫码登录）
- 一个 OpenAI 兼容的模型端点：对话模型 + embedding + rerank + vlm（可以是同一个中转）

### 三步起栈

```bash
git clone https://github.com/Names233/RING.git && cd RING/deploy/compose
./ring-init.sh                     # 交互式：生成 .env / 随机密钥 / 目录 / ov.conf / Caddyfile
docker compose --profile core ps   # 三个容器：openviking / maibot / napcat
```

`ring-init.sh` 会问：数据目录、时区、域名、模型网关（AGT_*）、OpenViking 的
embedding/rerank/vlm 端点、WebDAV 备份目的地。回车即用默认值；密钥自动随机生成。

然后按脚本最后的提示做两件事：

1. `ssh -L 6099:127.0.0.1:6099 <user>@<server>`，浏览器打开 `http://127.0.0.1:6099` 扫码登录 QQ；
   在 NapCat WebUI 里确认 OneBot WS 服务端为 `0.0.0.0:3001`，记下 token。
2. 把同一个 token 填进 `data/maibot/plugins/maibot-team_snowluma-adapter/config.toml`
   （`server = "napcat"`、`port = 3001`），并填好 `data/maibot/config/model_config.toml` 的对话模型。
   `./ringctl restart maibot`。

### 常用命令

```bash
./ringctl up core        # 最小可对话
./ringctl up all         # core + ring(自研三服务) + edge(Caddy)
./ringctl ps             # 状态与健康
./ringctl logs maibot    # 跟踪日志
./ringctl doctor         # 体检：docker/配置/端口/健康
./ringctl backup         # 立刻备份一次
./ringctl upgrade        # 拉镜像 + 重建 + 打印回滚方法
./ringctl down           # 停止（保留数据）
```

### profile 说明

| profile | 服务 | 何时开 |
| --- | --- | --- |
| `core` | openviking, maibot, napcat | 必开，最小可对话 |
| `ring` | ring-cloud（18080/18081/18082 三服务同进程） | 需要 persona 路由 / 记忆服务化接口时 |
| `edge` | caddy（80/443，自动 TLS） | 要给 WebUI/记忆库配域名时 |
| `backup` | backup（一次性任务） | `ringctl backup` 时临时拉起 |

### 端口默认值（全部只绑 127.0.0.1）

| 服务 | 宿主端口 | 说明 |
| --- | --- | --- |
| OpenViking | 1933 | 记忆库 HTTP API |
| MaiBot WebUI | 8001 | 管理界面（**无登录墙**，建议只在 SSH 隧道/反代+basic_auth 下用） |
| MaiBot WS | 8000 | maim_message |
| MaiBot API | 8090 | API server |
| NapCat OneBot | 3001 | WS 服务端，给适配器连 |
| NapCat WebUI | 6099 | 扫码登录 |
| ring-cloud | 18080 / 18081 / 18082 | openviking_service / persona_plan_b / ring_router |
| Caddy | 80 / 443 | 唯一对公网开放的端口 |

## 路径 B：Ansible 裸机

```bash
cd deploy/ansible
python -m pip install "ansible-core>=2.16"
cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml   # 填 host、密钥；建议 ansible-vault 加密
ansible-playbook --syntax-check site.yml
ansible-playbook site.yml --check --diff           # 预演
ansible-playbook site.yml
```

它做的事，与当前生产形态一一对应：

| role | 内容 |
| --- | --- |
| `uv` | 建 `ring` 用户与 `/opt/ring/{app,data,maibot,toolenv,tools,backup,napcat}`，装 uv，建 venv |
| `docker` | Docker Engine + compose 插件（NapCat 用容器跑），限制日志体积 |
| `ring` | 拉代码、`uv tool install` 钉版本、**装完就应用 `patches/maibot-openviking`**、渲染 `ov.conf`、四个 systemd unit + 备份 timer、NapCat 容器、Caddy |

生成的 systemd 单元与生产同名同参数：`ring-cloud.service`、`ring-openviking.service`、
`ring-maibot.service`、`ring-backup.{service,timer}`（默认 `04:10` 每日）。

## 常见故障

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| `docker: 'compose' is not a docker command` | 缺 compose 插件 | `apt install docker-compose-plugin`；已装 v1 的机器可 `docker-compose` 兜底 |
| `permission denied ... /var/run/docker.sock` | 用户不在 docker 组 | `sudo usermod -aG docker $USER` 后重新登录 |
| openviking 容器 `unhealthy` | `ov.conf` 的 api_base/密钥错，或 90s 内没起完 | `./ringctl logs openviking`；改 `data/openviking/ov.conf` 后 `./ringctl restart openviking` |
| maiBot 起不来、日志报 `config not found` | 首次启动没生成配置 | 容器会自动 `maibot init`；若是挂载权限问题，检查 `data/maibot` 属主 |
| 机器人不回消息 | 适配器 token 与 NapCat 不一致，或 `server` 写了 `127.0.0.1` | 容器里必须用服务名 `napcat`；见上文第 2 步 |
| `maibot` 报 OpenViking 连接失败 | 容器内 `data/openviking.json` 的 base_url 仍是 `127.0.0.1` | 设 `RING_OV_CONFIG_FORCE=1` 后重启，或手动改 `data/maibot/data/openviking.json` |
| 构建被 OOM kill | 2G 机器并行构建 | 串行构建：`./ringctl build openviking` → `ringcloud` → `maibot`；或临时加 swap |
| Caddy 证书签不下来 | 域名没解析到本机 / 80 端口被占 | `dig +short $OV_DOMAIN`；`ss -ltnp | grep :80` |

## 目录索引

```
deploy/
├── compose/
│   ├── docker-compose.yml      # 四个 profile 的主编排
│   ├── Dockerfile.openviking   # openviking==0.5.3
│   ├── Dockerfile.maibot       # maibot==1.3.19 + 构建期打补丁
│   ├── Dockerfile.ringcloud    # 自研三服务（仓库根为 build context）
│   ├── backup/Dockerfile       # 备份一次性任务
│   ├── maibot/                 # entrypoint.sh + prepare_instance.py（首启初始化/绑定 0.0.0.0）
│   ├── config/                 # ov.conf / Caddyfile / backup.env 模板
│   ├── requirements-runtime.txt
│   ├── .env.example
│   ├── ring-init.sh            # 交互式首装
│   ├── ringctl                 # 控制台（up/down/logs/doctor/backup/restore/upgrade）
│   ├── Makefile                # make init/up/doctor/backup...
│   └── VERIFICATION.md         # 影子栈实测记录（镜像大小/耗时/health/内存/前后状态）
└── ansible/
    ├── site.yml
    ├── inventory.example.ini
    ├── group_vars/all.example.yml
    └── roles/{uv,docker,ring}/
```
