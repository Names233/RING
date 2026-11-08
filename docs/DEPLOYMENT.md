# RING 部署手册

> 面向"从仓库到能对话"的完整操作手册。两条路径：**Docker Compose**（推荐）与 **Ansible 裸机**（对齐当前生产）。
> 快速选型与故障速查见 [`deploy/README.md`](../deploy/README.md)。

---

## 1. 架构总览

RING 是"一个入口 + 一套记忆 + 一个协议端"的单机系统。MaiBot 是唯一入口（回复所有消息），
OpenViking 是记忆库，NapCat 把 QQ 协议翻译成 OneBot v11，自研 ring-cloud 提供记忆服务化接口、
persona 路由与 A2A 桥。

```
                       ┌───────────────────────────────┐
   公网 / 用户 QQ  ───► │  NapCat (OneBot v11 WS :3001) │
                       └───────────────┬───────────────┘
                                       │ WS（适配器主动连）
                                       ▼
                       ┌───────────────────────────────┐        ┌─────────────────────────┐
                       │  MaiBot :8000/:8001           │ ◄────► │ OpenViking :1933        │
                       │  · 对话主体（唯一入口）        │  HTTP  │ · 记忆读写（REST）      │
                       │  · patches/ 注入的 OV 钩子     │        │ · embedding/rerank/vlm  │
                       └───────────────┬───────────────┘        └────────────┬────────────┘
                                       │ maim_message / A2A                  │ 同一份 workspace
                                       ▼                                     │
                       ┌───────────────────────────────┐                     │
                       │  ring-cloud（同进程三服务）    │─────────────────────┘
                       │  :18080 openviking_service    │
                       │  :18081 persona_plan_b        │
                       │  :18082 ring_router           │
                       └───────────────┬───────────────┘
                                       │ OpenAI 兼容
                                       ▼
                              外部模型网关（对话 / 向量 / 重排 / 视觉）

  edge（可选）：Caddy :80/:443  ──TLS──►  ov.<domain> → openviking:1933
                                          mb.<domain> → maibot:8001
```

**部署形态差异**：Compose 路径把每个组件做成容器（服务名互访）；Ansible 路径把
openviking / maibot / ring-cloud 跑成 systemd 服务（uv tool 安装），只有 NapCat 用容器——
这与当前生产机器完全一致。

### 组件与版本

| 组件 | 版本 | 许可证 | 形态 |
| --- | --- | --- | --- |
| MaiBot | 1.3.19 | GPL-3.0 | pip 包（容器内 `pip install` / 裸机 `uv tool`） |
| OpenViking | 0.5.3 | AGPL-3.0 | pip 包（`openviking-server`） |
| NapCat | `mlikiowa/napcat-docker:latest` | 见上游 | 容器（两条路径都是） |
| ring-cloud（自研） | 仓库 HEAD | MIT | 本仓库 `scripts/run_cloud_node.py` |
| Caddy | 2.x | Apache-2.0 | 容器（compose）/ apt 包（ansible） |

---

## 2. 端口表

| 端口 | 服务 | 绑定 | 用途 | 对外 |
| --- | --- | --- | --- | --- |
| 1933 | OpenViking | 127.0.0.1 | 记忆库 REST API（`/health`） | 经 Caddy `ov.<domain>` |
| 8001 | MaiBot WebUI | 127.0.0.1 | 管理界面 | 经 Caddy `mb.<domain>` |
| 8000 | MaiBot | 127.0.0.1 | maim_message WS 服务端 | 否 |
| 8090 | MaiBot | 127.0.0.1 | API server | 否 |
| 3001 | NapCat | 127.0.0.1 | OneBot v11 WS 服务端（适配器连） | 否 |
| 6099 | NapCat | 127.0.0.1 | WebUI（扫码登录） | 否（用 SSH 隧道） |
| 18080 | ring-cloud | 127.0.0.1 | openviking_service | 否 |
| 18081 | ring-cloud | 127.0.0.1 | persona_plan_b | 否 |
| 18082 | ring-cloud | 127.0.0.1 | ring_router | 否 |
| 80 / 443 | Caddy | 0.0.0.0 | HTTP/HTTPS | **是**（唯一） |

> 容器内部一律监听 `0.0.0.0`，宿主侧用 `127.0.0.1:PORT:PORT` 收口；
> 裸机形态由 `RING_BIND_HOST`（默认 `127.0.0.1`）控制。

---

## 3. 数据目录表

两条路径使用同一套布局（Compose 里前缀是 `${RING_DATA_DIR}`，裸机是 `/opt/ring`）：

| 路径 | 内容 | 是否必须备份 |
| --- | --- | --- |
| `openviking/ov.conf` | 记忆库配置，含 root_api_key（0600） | 是（含密钥） |
| `openviking/workspace/` | 记忆本体（向量 + 原文） | **是** |
| `openviking/records/` | 记忆索引记录 | **是** |
| `maibot/config/` | `bot_config.toml`、`model_config.toml` | 是（含模型 key） |
| `maibot/data/` | `MaiBot.db`、`openviking.json`、WebUI 状态 | **是** |
| `maibot/plugins/` | 适配器插件与其配置（含 NapCat token） | 是 |
| `napcat/config/` | `onebot11_<QQ>.json`、`webui.json` | 是 |
| `napcat/qq/` | QQ 登录态 | 是（重装免扫码） |
| `caddy/` | `Caddyfile`、证书缓存 | 可选 |
| `backup/passphrase` | 备份加密口令（0600） | **是（丢了备份解不开）** |
| `backup/spool/` | 本地留存归档 | 否 |

---

## 4. 环境变量表

Compose 读 `deploy/compose/.env`；Ansible 用 `group_vars/all.yml` 的同义变量名。常用项：

| 变量（compose） | Ansible 变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| `RING_DATA_DIR` | `ring_base` | `./data` / `/opt/ring` | 数据根目录 |
| `TZ` | `backup_timezone` | `Asia/Shanghai` | 时区 |
| `OV_PORT` | `openviking_port` | 1933 | 记忆库端口 |
| `MAIBOT_WEBUI_PORT` | `maibot_webui_port` | 8001 | WebUI 端口 |
| `MAIBOT_VERSION` | `maibot_version` | 1.3.19 | MaiBot 版本 |
| `OPENVIKING_VERSION` | `openviking_version` | 0.5.3 | OpenViking 版本 |
| `OV_ROOT_API_KEY` | `ov_root_api_key` | 随机 | OV 管理密钥（MaiBot 也用它） |
| `OV_EMBEDDING_API_BASE` | `ov_embedding_api_base` | — | 向量模型端点（OpenAI 兼容） |
| `OV_EMBEDDING_MODEL` | `ov_embedding_model` | — | 向量模型名 |
| `OV_EMBEDDING_DIMENSION` | `ov_embedding_dimension` | 1024 | 向量维度，**必须与模型一致** |
| `OV_RERANK_*` | `ov_rerank_*` | — | 重排模型 |
| `OV_VLM_*` | `ov_vlm_*` | — | 视觉/文档模型 |
| `AGT_BASE_URL` | `agt_base_url` | — | ring-cloud 的对话模型网关 |
| `AGT_API_KEY` / `AGT_MODEL` | 同名 | — | 网关密钥 / 模型名 |
| `HEARTBEAT_SECRET_TOKEN` | `heartbeat_secret_token` | 随机 | ring_router 鉴权 |
| `RING_OFFLINE_MODE` | `ring_offline_mode` | 0 | 1=不调外部模型 |
| `OV_DOMAIN` / `MB_DOMAIN` | `ov_domain` / `mb_domain` | example.com | edge 站点域名 |
| `ACME_EMAIL` | `caddy_email` | — | Let's Encrypt 邮箱 |
| `BACKUP_PATHS` / `BACKUP_KEEP` | `backup_paths` / `backup_keep` | 见示例 | 备份范围与远端保留数 |
| `DAV_BASE` / `DAV_USER` / `DAV_PASS` | 同名 | 空 | WebDAV 目的地（空=只留本地） |
| `NAPCAT_UID` / `NAPCAT_GID` | `napcat_uid` / `napcat_gid` | 1000 | 数据目录属主 |

被容器化改动过的两个点（行为向后兼容）：

- `scripts/run_cloud_node.py` 新增 `RING_BIND_HOST`（默认 `127.0.0.1`，容器里设 `0.0.0.0`）；
- MaiBot 容器的 `entrypoint.sh` 首次启动时把 `[http].host` 与 `[maim_message].ws_server_host`
  改成 `0.0.0.0`（可用 `MAIBOT_FORCE_BIND_HOST=0` 关闭），并按环境变量生成
  `data/openviking.json`（`RING_OV_CONFIG_FORCE=1` 强制重写）。

---

## 5. 路径 A：Docker Compose 部署

### 5.1 前置条件

- Linux 主机（Debian 12+ / Ubuntu 22.04+ 已实测）
- Docker Engine ≥ 24 与 **compose v2 插件**（`docker compose version` 有输出）
- 内存 ≥ 2 GB（建议 4 GB）+ swap ≥ 2 GB；磁盘 ≥ 15 GB
- 出网：pypi.org、download.docker.com、上游 npm/pip 源
- 可选：两个域名（A 记录指向本机）+ 80/443 空闲

### 5.2 安装

```bash
git clone https://github.com/Names233/RING.git
cd RING/deploy/compose
./ring-init.sh
```

脚本行为：

1. 校验 docker 与 compose（缺 compose 插件直接报错并给安装命令）;
2. 询问数据目录 / 时区 / 域名 / 模型端点 / WebDAV；
3. 生成随机密钥（`OV_ROOT_API_KEY`、`HEARTBEAT_SECRET_TOKEN`、备份口令）；
4. 建目录、渲染 `openviking/ov.conf`（0600）、`backup/backup.env`（0600）、`caddy/Caddyfile`；
5. 写 `.env`（0600）；
6. `docker compose --profile core up -d --build`（串行构建，首次约 10-20 分钟）。

只想准备配置不启动：`./ring-init.sh --no-up`。无人值守（全默认）：`./ring-init.sh --yes`。

### 5.3 手动起停

```bash
cd deploy/compose
docker compose config --profiles               # 应列出 backup core edge ring
docker compose --profile core up -d --build    # 最小可对话
docker compose --profile ring up -d            # + 自研三服务
docker compose --profile edge up -d            # + Caddy（80/443）
./ringctl backup                               # 跑一次备份
./ringctl down                                 # 停（数据保留）
```

### 5.4 单服务构建与内存

2 GB 机器不要并行构建。串行：

```bash
docker compose --profile core build openviking
docker compose --profile ring build ring-cloud
docker compose --profile core build maibot      # 最大，约 1.5-2 GB 镜像
```

内存上限（`deploy.resources.limits`，与生产 systemd `MemoryMax` 对齐）：

| 服务 | 限制 |
| --- | --- |
| openviking | 640M |
| maibot | 700M |
| napcat | 1200M |
| ring-cloud | 180M |
| backup | 256M |

> 宿主机是 2 GB 时，四个上限之和远超物理内存——**同时只跑得动 core 三个服务**，
> 且需要 swap 兜底。要全开请上 4 GB。

### 5.5 镜像构建期打了什么补丁

`Dockerfile.maibot` 在 `pip install maibot==1.3.19` 之后执行：

```dockerfile
COPY patches/maibot-openviking /tmp/patches/maibot-openviking
RUN python /tmp/patches/maibot-openviking/install.py --apply \
      --site-packages "$(python -c 'import site;print(site.getsitepackages()[0])')" \
      --mai-root /tmp/maibot-patch --no-config --no-diff
RUN python - <<'PY'   # 构建期断言：补丁真的在镜像里
... 检查 src/maisaka/memory/openviking_injector.py 存在、reasoning_engine.py 含钩子 ...
PY
```

这样**升级 MaiBot 版本时补丁不会丢**（生产现状是运行时手改 site-packages，`pip` 升级即失效）。

---

## 6. 路径 B：Ansible 裸机部署

### 6.1 前置条件

- 控制机：Python ≥ 3.10 + `ansible-core >= 2.16`
- 目标机：Debian 12+ / Ubuntu 22.04+，sudo 免密，能出网
- 目标机 80/443 空闲（若启用 Caddy）

### 6.2 变量

```bash
cd deploy/ansible
cp inventory.example.ini inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
```

必填：`ring_repo_url`、`ring_repo_version`（建议写 commit）、`ov_*` 四个模型的端点与 key、
`agt_*`、`ov_root_api_key`、`heartbeat_secret_token`、`caddy_*` / `*_domain`、`dav_*`。

密钥用 vault：`ansible-vault encrypt group_vars/all.yml`，运行加 `--ask-vault-pass`。

### 6.3 运行

```bash
ansible-playbook --syntax-check site.yml
ansible-playbook site.yml --check --diff     # 预演
ansible-playbook site.yml                    # 真跑
ansible-playbook site.yml --tags maibot      # 只重装 MaiBot
```

### 6.4 产物

| 位置 | 内容 |
| --- | --- |
| `/opt/ring/app` | 仓库代码（`git` 检出到 `ring_repo_version`） |
| `/opt/ring/.venv` | ring-cloud 的运行 venv |
| `/opt/ring/toolenv` | uv tool 环境（maibot / openviking） |
| `/opt/ring/data` | 数据（ov.conf、workspace、records） |
| `/opt/ring/maibot` | MaiBot 实例目录（config/data/plugins） |
| `/opt/ring/napcat` | NapCat config 与 QQ 登录态 |
| `/opt/ring/backup` | 备份脚本、口令、spool |
| `/etc/systemd/system/ring-*.service` | 四个单元 + `ring-backup.timer` |
| `/etc/caddy/Caddyfile` | 两个站点（`caddy_enabled: true` 时） |

`maibot` 的补丁应用方式与生产一致：`install.py --apply --site-packages <uv tool 的 site-packages>`，
幂等，可在每次升级后重跑。

---

## 7. 首次启动后必做（两条路径相同）

1. **QQ 登录**：`ssh -L 6099:127.0.0.1:6099 <user>@<host>` → `http://127.0.0.1:6099` → 扫码。
   在 WebUI 里确认 OneBot WS 服务端监听 `0.0.0.0:3001`（compose 内）或 `127.0.0.1:3001`（裸机），
   设一个 token，消息格式选 `array`。
2. **适配器**：`maibot/plugins/maibot-team_snowluma-adapter/config.toml`
   `[client] client_type="napcat"`、`server="napcat"`（compose）/ `"127.0.0.1"`（裸机）、`port=3001`、
   `token=<上一步>`。
3. **对话模型**：`maibot/config/model_config.toml` 填 provider/api_key/model。
4. **记忆**：`maibot/data/openviking.json` 的 `base_url` 指向 `http://openviking:1933`（compose）或
   `http://127.0.0.1:1933`（裸机），`api_key` 用 `OV_ROOT_API_KEY`。
5. **自检**：`./ringctl doctor`（compose）或
   `systemctl status ring-cloud ring-openviking ring-maibot caddy`（裸机）。

---

## 8. 升级与回滚

### Compose

```bash
cd deploy/compose
sed -i 's/^MAIBOT_VERSION=.*/MAIBOT_VERSION=1.3.20/' .env   # 例：升 MaiBot
./ringctl upgrade
```

`ringctl upgrade` = pull 上游镜像 → 重建自研镜像 → `up -d`（只重建变化的容器）。
回滚：把版本号改回旧值，再 `./ringctl up all --force-recreate`。数据不动。

**回滚数据库/记忆**：见下一节，先 `restore` 到临时目录，再决定是否覆盖。

> **改 embedding 模型的坑（实测）**：OpenViking 会把 embedding 的 provider/model/dimension
> 记在 collection 元数据里。如果你换了 `OV_EMBEDDING_MODEL`/`OV_EMBEDDING_DIMENSION`
> （或把别的机器的 `workspace/` 直接拷进来），容器会**启动失败并反复重启**，日志里是：
>
> ```text
> EmbeddingRebuildRequiredError: Existing collection embedding metadata does not match
> current configuration. Rebuild is required before using the current embedding model,
> or set embedding.allow_metadata_override=true to keep existing vectors when only
> provider/model changed (dimension must remain the same).
> ```
>
> 两条出路：① 维度不变、只想改名 → 在 `ov.conf` 的 `embedding` 段加
> `"allow_metadata_override": true`；② 维度变了 → 必须重建向量库（先备份，再清空
> `${RING_DATA_DIR}/openviking/workspace`，重启后会重新索引；原始记忆文本仍在
> `records/` 与 MaiBot 的数据库里）。**只有改名换模型不会丢数据，改维度会丢向量、需要重灌。**

### Ansible

```bash
# 改 group_vars/all.yml 里的 maibot_version，然后：
ansible-playbook site.yml --tags maibot
```

role 是幂等的，重复执行不会重建数据。回滚同样是把版本改回去再跑一次。

---

## 9. 备份与恢复

### 机制

`tar` 打包 `${BACKUP_PATHS}` → `gzip -6` → `gpg --symmetric --cipher-algo AES256`（口令文件）
→ 本地 spool（只留最近 2 份）→ 可选上传 WebDAV → 远端按文件名时间戳保留 `BACKUP_KEEP`（默认 14）。

- Compose：`./ringctl backup`（一次性容器，挂 `backup/passphrase` 只读）
- 裸机：`ring-backup.timer` 每天 `04:10`（`backup_oncalendar` 可改），或 `systemctl start ring-backup.service`

### 恢复

```bash
# compose
./ringctl restore ring-20261108T041000Z.tar.gz.gpg        # → ./restore/
# 裸机
mkdir -p /tmp/restore && gpg --batch --decrypt \
  --passphrase-file /opt/ring/backup/.passphrase \
  /opt/ring/backup/spool/ring-XXX.tar.gz.gpg | tar -C /tmp/restore -xzf -
```

恢复顺序（**先停服务**，避免写坏数据库）：

```bash
./ringctl down                                   # 或 systemctl stop ring-maibot ring-openviking
cp -a restore/openviking/workspace/. data/openviking/workspace/
cp -a restore/maibot/data/. data/maibot/data/
cp -a restore/napcat/config/. data/napcat/config/
./ringctl up core
```

> 口令丢了 = 备份不可恢复。把 `backup/passphrase`（或 `/opt/ring/backup/.passphrase`）
> 单独存进密码管理器。

---

## 10. 卸载

```bash
# Compose（保留数据）
cd deploy/compose && ./ringctl down
# Compose（彻底删除，含本地数据）
./ringctl down && rm -rf ./data
# 删镜像
docker image rm ring/maibot:1.3.19 ring/openviking:0.5.3 ring/ringcloud:0.1.0 ring/backup:0.1.0

# Ansible 裸机
systemctl disable --now ring-maibot ring-openviking ring-cloud ring-backup.timer caddy
rm -f /etc/systemd/system/ring-*.{service,timer} && systemctl daemon-reload
docker rm -f ring-napcat
rm -rf /opt/ring                 # 数据在这里，确认后再删
userdel -r ring
```

---

## 11. 排障

| 现象 | 定位 | 处理 |
| --- | --- | --- |
| `ov.conf` 里改了 key 但没生效 | 容器重启才重读 | `./ringctl restart openviking` |
| OV `/health` 200 但检索报 401 | 用的是 user key 而 root key 才被接受 | 把 `OV_ROOT_API_KEY` 写进 `maibot/data/openviking.json` |
| MaiBot 日志 `openviking connection refused` | 容器内 127.0.0.1 指自己 | 用服务名 `openviking`；确认 `RING_OV_CONFIG_FORCE=1` 重写过配置 |
| 记忆一直没写入 | `write_enabled`/阈值未触发（`min_new_messages=4`、`commit_message_threshold=20`） | 多聊几句；或看 `data/maibot/data/openviking_write_state.json` |
| NapCat 反复掉线 | 适配器没有重连退避 | 应用 `patches/snowluma-adapter/reconnect-backoff.patch` |
| Caddy 报 `no such host` | 域名解析未生效 | `dig +short mb.example.com` 应返回本机 IP |
| 2 GB 机器 OOM | 同时开了 ring/caddy/backup | 只开 `core`；或加 swap：`fallocate -l 2G /swapfile && mkswap /swapfile && swapon /swapfile` |
| `docker compose` 报 `unknown flag: --profile` | 用的是 v1 | 装 compose v2 插件 |

---

## 12. 安全说明

- 仓库里**没有任何真实密钥**：`.env.example`、`group_vars/all.example.yml`、三个 `*.tmpl` 全是占位符；
  `.gitignore` 忽略 `.env`、`inventory.ini`、`group_vars/all.yml`、`deploy/compose/data/`。
- 生成的 `.env`、`ov.conf`、`backup.env`、备份口令一律 `0600`。
- 除 Caddy 的 80/443 外，所有端口只绑 `127.0.0.1`；NapCat WebUI 请用 SSH 隧道。
- MaiBot WebUI 默认**没有登录墙**：公网暴露前请启用 Caddy `basic_auth`（模板里有注释块）
  或干脆不要开 `edge` 的 `mb.` 站点。
- 备份是 GPG 对称加密，口令独立存放；WebDAV 走 HTTPS。

---

## 13. 验证记录

完整实测输出（命令 + 原始返回 + 前后状态对比）在
[`deploy/compose/VERIFICATION.md`](../deploy/compose/VERIFICATION.md)。
这是**真在服务器上跑影子栈**的结果，不是"yaml 看起来没问题"。

### 构建产物（Debian 13.7 / 2 vCPU / 2 GB 内存，串行构建）

| 镜像 | 大小 | 构建耗时 |
| --- | --- | --- |
| `ring/openviking:0.5.3` | 1.22 GB | 259 s |
| `ring/maibot:1.3.19` | 1.08 GB | 95 s |
| `ring/ringcloud:0.1.0` | 142 MB | 14 s |
| `ring/backup:0.1.0` | 139 MB | 15 s |
| **合计** | **2.58 GB** | **383 s（约 6.5 分钟）** |

外加两个上游镜像（`mlikiowa/napcat-docker` 约 1.47 GB、`caddy:2-alpine` 约 60 MB），
一台机器从零到全量镜像约 **4 GB 磁盘**。2 GB 内存机器串行构建全程未 OOM。

### 影子栈实测

| 端点 | 返回 |
| --- | --- |
| `127.0.0.1:11880/health`（openviking_service） | `{"status":"ok","service":"openviking","storage_root":"/data/openviking"}` 200 |
| `127.0.0.1:11881/health`（persona_plan_b） | `{"status":"ok","provider":"persona-plan-b","version":"0.1.0"}` 200 |
| `127.0.0.1:11882/health`（ring_router） | `{"status":"ok","service":"ring-router","mode":"CLOUD_COMPANION",...}` 200 |
| `127.0.0.1:11933/health`（OpenViking） | `{"status":"ok","healthy":true,"version":"0.5.3","auth_mode":"api_key"}` 200 |
| `127.0.0.1:18001/`（MaiBot WebUI） | 200 |

三个容器同时在线时的实际占用：MaiBot 380.7 MB / OpenViking 344.1 MB / ring-cloud 11.9 MB
（合计约 737 MB，均未触及 `deploy.resources.limits` 的上限）。

### 补丁确实进了镜像

```text
SITE_PACKAGES=/usr/local/lib/python3.13/site-packages
-rw-r--r-- ... src/maisaka/memory/openviking_injector.py   (20170 bytes)
-rw-r--r-- ... src/maisaka/memory/openviking_writer.py     (19229 bytes)
reasoning_engine.py build_openviking_memory_message 命中 2 次
runtime.py ensure_started 命中 1 次；顶层 runtime.py create_task 命中 4 次
```

运行期日志同时出现 `[maisaka_openviking_writer] OpenViking 写入任务已启动`，
说明补丁不只是文件到位，模块真的被加载了。

### 没验证的部分

QQ 扫码登录与真实对话、Caddy 自动证书、backup profile 的 WebDAV 上传、Ansible 实跑
——都需要真实账号/域名/一次性机器，不能在生产机上做。逐条理由见
`deploy/compose/VERIFICATION.md` 第 12 节。

---

## 14. 从仓库到能对话：实际步骤

| # | 步骤 | 时间（首次） |
| --- | --- | --- |
| 1 | `git clone` + `cd deploy/compose` | 1 分钟 |
| 2 | `./ring-init.sh`（回答 ~12 个问题） | 3 分钟 |
| 3 | 首次镜像构建（串行，2C2G） | 10-20 分钟 |
| 4 | NapCat 扫码登录 | 2 分钟 |
| 5 | 填适配器 token + `model_config.toml` | 5 分钟 |
| 6 | `./ringctl doctor` 自检 + 群里发一句话 | 2 分钟 |
| 合计 | **6 步，约 25-35 分钟**（不含下载带宽瓶颈） | |
