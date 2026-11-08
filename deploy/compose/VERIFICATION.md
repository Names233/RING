# 部署验证记录（影子栈实测）

> 本文件记录**在真实服务器上用干净容器验证**的结果，不是"yaml 语法看起来没问题"。
> 验证日期：2026-11-08；验证机：AWS Lightsail / Debian 13.7 / 2 vCPU / 1936 MB RAM + 6 GB swap。
> 生产环境（systemd + 宿主机 NapCat 容器）在整个验证过程中**未被触碰**，验证前后状态逐项对比见第 11 节。

## 1. 结论摘要

| # | 验收项 | 结果 |
| --- | --- | --- |
| 1 | `docker compose config` 可解析，4 个 profile 可列出 | ✅ backup / core / edge / ring |
| 2 | 三个自研镜像构建成功，大小与耗时已记录 | ✅ 2.44 GB / 串行 368 s |
| 3 | 影子栈 4 个 health 端点全部 200 | ✅ 11880 / 11881 / 11882 / 11933 |
| 4 | 补丁在**镜像内**生效（不是运行时手改 site-packages） | ✅ injector/writer 存在 + 三处注入命中 + 运行期日志 |
| 5 | `ansible-playbook --syntax-check site.yml` 通过 | ✅ ansible-core 2.22.0 |
| 6 | Docker 路径真正跑起来（容器 healthy + WebUI 200） | ✅ openviking / ring-cloud / maibot 全 healthy |
| 7 | 脚本语法检查 | ✅ 5 个 shell 脚本 `bash -n` 全 OK；`ringctl doctor` 能跑完 |
| 8 | 影子栈已清理、生产状态未变 | ✅ 见第 10、11 节 |

## 2. 环境

```text
$ uname -srm
Linux 6.12.107+deb13-cloud-amd64 x86_64
$ free -m | head -2
               total        used        free      shared  buff/cache   available
Mem:            1936        1039         362           0         718         896
Swap:           6143        1432        4711
$ docker --version && docker compose version
Docker version 26.1.5, build ...
Docker Compose version v2.29.7      # 验证时新装（生产机原本没有 compose 插件）
```

验证栈完全独立：
- 源码：`/opt/ring-shadow/src`（从仓库打包上传，不含 `.git`）
- 数据：`/opt/ring-shadow/data`
- 端口：`11933`（OV）、`11880/11881/11882`（ring-cloud 三服务）、`18001`（MaiBot WebUI）、`13001/16099`（NapCat，未启动）
- compose project：`ring-shadow`（`down -v` 只影响影子栈）

## 3. `docker compose config` 与 profile

```text
$ cd /opt/ring-shadow/src/deploy/compose
$ sudo docker compose config -q && echo CONFIG_OK
CONFIG_OK
$ sudo docker compose config --profiles
backup
core
edge
ring
$ sudo docker compose --profile core --profile ring --profile edge --profile backup config --services
backup
caddy
maibot
napcat
openviking
ring-cloud
```

宿主端口解析结果（影子 `.env`，全部 `127.0.0.1`）：

```text
published: "80" / "443" / "443"(udp)   ← caddy，唯一对公网
published: "18001" / "18000" / "18090" ← maibot
published: "13001" / "16099"           ← napcat
published: "11933"                     ← openviking
published: "11880" / "11881" / "11882" ← ring-cloud
```

> 注意：compose 的 `config` 默认**只输出已启用 profile 的服务**，不加 `--profile` 时
> `services` 是空的（`services: {}`）。这是 profile 机制的正常行为，不是配置错误。

## 4. 镜像构建（串行，2 GB 内存机器）

构建命令（逐个、串行，避免并行触发 OOM）：

```bash
docker compose --profile core  build openviking
docker compose --profile ring  build ring-cloud
docker compose --profile core  build maibot
```

| 镜像 | 大小 | 构建耗时 | 说明 |
| --- | --- | --- | --- |
| `ring/openviking:0.5.3` | **1.22 GB** | **259 s** | 上游 wheel 依赖极重（litellm + 全套 volcengine SDK + scrapy/trafilatura） |
| `ring/maibot:1.3.19` | **1.08 GB** | **95 s** | 含 playwright/pandas/scipy/faiss-cpu；补丁在构建期写入 |
| `ring/ringcloud:0.1.0` | **142 MB** | **14 s** | 纯 python:3.13-slim + 六个运行期依赖 |
| `ring/backup:0.1.0` | **139 MB** | **15 s** | gpg/curl/tar + 两个备份脚本（单独一轮构建，见下） |
| 合计 | **2.58 GB** | **383 s** | 2 GB 机器全程未 OOM，未使用 `--memory-swap` 兜底 |

```text
$ sudo docker images 'ring/*' --format '{{.Repository}}:{{.Tag}} {{.Size}}'
ring/maibot:1.3.19      1.08GB
ring/ringcloud:0.1.0    142MB
ring/openviking:0.5.3   1.22GB
```

第四个 Dockerfile（`deploy/compose/backup/Dockerfile`，`backup` profile 的一次性任务）单独验证：

```text
$ docker compose --profile backup build backup      # 15 s
$ docker images ring/backup --format '{{.Repository}}:{{.Tag}} {{.Size}}'
ring/backup:0.1.0  139MB

$ docker run --rm --entrypoint sh ring/backup:0.1.0 -c 'command -v gpg; command -v curl; command -v tar; command -v python3; ls -l /usr/local/bin/ring-*.sh'
/usr/bin/gpg
/usr/bin/curl
/usr/bin/tar
/usr/local/bin/python3
-rwxr-xr-x 1 root root 3865 ... /usr/local/bin/ring-backup.sh
-rwxr-xr-x 1 root root 1182 ... /usr/local/bin/ring-restore.sh
```

即四个镜像全部可构建，四个 Dockerfile 里没有只能在作者机器上跑通的东西。

## 5. 补丁在镜像内生效（关键验收项）

`install.py` 是在 **Dockerfile 构建阶段**执行的，因此升级/重建镜像都不会丢补丁：

```text
$ sudo docker run --rm -v /tmp/verify-patch.sh:/verify-patch.sh:ro \
      --entrypoint sh ring/maibot:1.3.19 /verify-patch.sh
SITE_PACKAGES=/usr/local/lib/python3.13/site-packages
-rw-r--r-- 1 root root 20170 Nov  8 21:21 .../src/maisaka/memory/openviking_injector.py
-rw-r--r-- 1 root root 19229 Nov  8 21:21 .../src/maisaka/memory/openviking_writer.py
reasoning_engine.py build_openviking_memory_message 命中次数: 2
runtime.py ensure_started 命中次数: 1
顶层 runtime.py create_task 命中次数: 4
maibot 版本: 1.3.19
```

运行期二次确认（容器真的加载了补丁模块，而不只是文件躺在那里）：

```text
[ring] 已生成 OpenViking 钩子配置: /app/maibot/data/openviking.json（base_url=http://openviking:1933）
[maisaka_openviking_writer] OpenViking 写入任务已启动: interval=60s lookback=7200s batch=40
                          commit_at=20 idle=900s
```

## 6. 影子栈健康检查（四个端点）

```text
$ curl -s -w ' HTTP=%{http_code}\n' http://127.0.0.1:11880/health
{"status":"ok","service":"openviking","storage_root":"/data/openviking"} HTTP=200

$ curl -s -w ' HTTP=%{http_code}\n' http://127.0.0.1:11881/health
{"status":"ok","provider":"persona-plan-b","version":"0.1.0"} HTTP=200

$ curl -s -w ' HTTP=%{http_code}\n' http://127.0.0.1:11882/health
{"status":"ok","service":"ring-router","mode":"CLOUD_COMPANION","local_online":false,
 "last_heartbeat_ts":null,"last_seq":-1,"pending_tasks_count":0} HTTP=200

$ curl -s -w ' HTTP=%{http_code}\n' http://127.0.0.1:11933/health
{"status":"ok","healthy":true,"version":"0.5.3","auth_mode":"api_key"} HTTP=200

$ curl -s -o /dev/null -w 'HTTP=%{http_code}\n' http://127.0.0.1:18001/
HTTP=200
```

容器状态：

```text
$ sudo docker ps --filter name=ring- --format '{{.Names}} {{.Status}} {{.Ports}}'
ring-cloud      Up 6 minutes (healthy)  127.0.0.1:11880->18080/tcp, 127.0.0.1:11881->18081/tcp, 127.0.0.1:11882->18082/tcp
ring-openviking Up 4 minutes (healthy)  127.0.0.1:11933->1933/tcp
ring-maibot     Up 3 minutes (healthy)  127.0.0.1:18000->8000/tcp, 127.0.0.1:18001->8001/tcp, 127.0.0.1:18090->8090/tcp
```

## 7. 容器化后的配置改写（entrypoint 行为验证）

MaiBot 实例首次启动由 `deploy/compose/maibot/entrypoint.sh` 初始化并改写监听地址：

```text
$ grep -nE '^\s*(host|ws_server_host)\s*=' /opt/ring-shadow/data/maibot/config/bot_config.toml
38:host = ["0.0.0.0"]        # 后端监听地址列表……
503:ws_server_host = "0.0.0.0" # 旧版 WebSocket 服务监听地址……

$ sudo python3 -c "import json;d=json.load(open('.../data/maibot/data/openviking.json'));print(d)"
openviking.json = {'enabled': True, 'base_url': 'http://openviking:1933', 'timeout_seconds': 6.0,
                   'limit': 6, 'write_enabled': True, 'flush_interval_seconds': 60,
                   'state_file': '', 'peer_scope': 'all'}
```

即：容器内不能再用 `127.0.0.1`（那是容器自己），entrypoint 把它改成 `0.0.0.0`，
并把 OV 地址写成 compose 服务名 `http://openviking:1933`。文件权限 `0600`。

## 8. 资源占用（docker stats，三个影子容器同时在线）

```text
$ sudo docker stats --no-stream --format '{{.Name}} mem={{.MemUsage}} cpu={{.CPUPerc}}'
ring-maibot     mem=380.7MiB / 700MiB   cpu=1.30%
ring-openviking mem=344.1MiB / 640MiB   cpu=2.38%
ring-cloud      mem=11.85MiB / 180MiB   cpu=0.15%
```

- 影子栈（core 的 OV+MaiBot，加 ring 的 ring-cloud）合计约 **737 MB**，在 1936 MB 机器上
  与生产负载（宿主 NapCat 容器 ~54 MB + antigravity-manager ~32 MB）共存无 swap 抖动。
- `deploy.resources.limits` 生效（`/ 700MiB`、`/ 640MiB`、`/ 180MiB` 即 compose 里配的上限）。
- **NapCat 未在影子环境启动**（会尝试用同一 QQ 号登录，且 1200 MB 上限会挤压生产），
  QQ 登录链路属于"必须在真实部署时人工扫码"的部分，见第 12 节。

## 9. Ansible 路径

```text
$ /tmp/ansible-venv/bin/ansible-playbook --version | head -1
ansible-playbook [core 2.22.0]

$ cd deploy/ansible && ansible-playbook --syntax-check -i inventory.example.ini site.yml
playbook: site.yml
$ echo $?
0
```

只做了 `--syntax-check`（语法 + 变量名 + 模板存在性）。**没有**在服务器上实跑 playbook：
它会把生产机重建成 Ansible 管理的形态（改 `/opt/ring`、覆盖 systemd unit），
与"绝不碰生产"的约束冲突。实跑应在一次性虚拟机上做（见第 12 节）。

## 10. 脚本自检

```text
$ for f in ring-init.sh ringctl ../backup/ring-backup.sh ../backup/ring-restore.sh maibot/entrypoint.sh; do
      bash -n "$f" && echo "OK $f"; done
OK   ring-init.sh
OK   ringctl
OK   ../backup/ring-backup.sh
OK   ../backup/ring-restore.sh
OK   maibot/entrypoint.sh

$ bash ringctl profiles
backup
core
edge
ring

$ bash ringctl doctor
RING 体检  2026-11-08T13:28:58Z
-----------------------------------------------------------
[x] docker daemon           无法访问（当前用户不在 docker 组？）
==> compose                 OK (2.29.7)
==> compose 配置            可解析
==> .env                    无占位符残留
==> ov.conf                 存在（权限 600）
[!] 备份口令                缺失：备份会失败（重跑 ring-init.sh 生成）
==> Caddyfile               存在
[!] 内存 1936MB：低于 4G 时请只跑 core profile，或保证有 swap
```

两条 `[x]/[!]` 都是**预期**的：这台机器上 `admin` 不在 `docker` 组（验证时全程用 `sudo docker`），
且影子环境没跑 `ring-init.sh`（没有备份口令）。真实用户按 README 把用户加入 docker 组、
用 `ring-init.sh` 生成口令后，这两条会变绿。

## 11. 清理与生产前后对比

清理动作（只针对 `ring-shadow` project 与 `/opt/ring-shadow`）：

```bash
sudo docker compose -p ring-shadow --profile core --profile ring down -v
sudo rm -rf /opt/ring-shadow
sudo docker rmi ring/maibot:1.3.19 ring/ringcloud:0.1.0 ring/openviking:0.5.3
```

```text
 Container ring-cloud      Removed
 Container ring-openviking  Removed
 Network ring               Removed
```

| 检查项 | 验证前 | 验证后 |
| --- | --- | --- |
| `systemctl is-active ring-cloud ring-openviking ring-maibot caddy ring-backup.timer` | active ×5 | active ×5 |
| `docker ps` | napcat Up 4 hours；antigravity-manager Up 2 days (healthy) | napcat Up 4 hours；antigravity-manager Up 3 days (healthy) |
| `docker images` | astrbot 1.97GB / napcat 1.47GB / antigravity 1.13GB / hello-world 10.1kB | 同上，`ring/*` 已删除 |
| `docker network ls` | bridge / host / none | bridge / host / none（`ring` 已随 `down -v` 删除） |
| `/opt` | 无 `ring-shadow` | 无 `ring-shadow` |
| 生产 `/health` | 18080/18081/18082 = 200，1933 healthy，8001 = 200 | 完全一致 |
| 磁盘 | 21G used / 36G avail | 21G used / 36G avail |

> 验证镜像`ring/*` 已删除（占用 2.44 GB）。需要再看一次时重跑第 4 节的三条 build 命令即可
> （约 6 分钟，其中 openviking 占 4 分钟）。系统里新增的唯一持久物是
> `/usr/libexec/docker/cli-plugins/docker-compose`（compose v2 插件，生产机原本缺失，
> 不影响任何正在运行的服务）。

## 12. 验证了 / 没验证

**已真实验证**：compose 解析与 profile、三个镜像构建、补丁构建期落地、OV 冷启动、
ring-cloud 三服务健康、MaiBot 容器启动 + WebUI、entrypoint 配置改写、内存与上限、
Ansible 语法、脚本语法与 `ringctl doctor`。

**未验证（需要真实账号/域名/一次性机器，不能在生产机上做）**：
1. **QQ 扫码登录与真实对话**：影子 NapCat 未启动（同号登录会踢掉生产 QQ）。
   预期路径：`ring-init.sh` → SSH 隧道 6099 扫码 → 适配器 token → 群里说话。
2. **Caddy 自动证书**：影子 `.env` 用 `.invalid` 域名，没开 `edge`（80/443 被生产 Caddy 占用）。
3. **backup profile 实跑 WebDAV 上传**：镜像能构建、容器内 gpg/curl/tar/python 齐备
   （见第 4 节），但没有真实 WebDAV 目的地，所以 `ring-backup.sh` 的
   tar→gpg→上传→PROPFIND 保留策略这条链路**没有端到端跑过**，只做了 `bash -n`。
4. **Ansible playbook 实跑**：会重建生产机，仅做语法检查。
5. **模型链路真实调用**：影子 `ov.conf` 用占位 embedding/rerank/vlm 端点（`127.0.0.1:1`），
   只验证 OV 进程健康，不验证向量化质量。

## 13. 验证中发现并修掉的问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `docker compose` 报 `invalid hostPort: 118080` | 端口必须 ≤ 65535，影子端口规划一开始用了 118080 | 改用 `11880/11881/11882`；文档里的端口选择也统一按 5 位以内 |
| OV 容器反复重启：`EmbeddingRebuildRequiredError` | 把生产 `workspace/` 只读副本挂进容器，但影子 `ov.conf` 的 embedding 模型名与生产不同 → collection 元数据不匹配 | 清空 workspace 冷启动即 healthy；这也是**升级换 embedding 模型时必须知道的坑**，已写入 `docs/DEPLOYMENT.md` 的升级章节 |
| `ringctl doctor` 只输出一行 `maibot: command not found` | `.env` 里 `BACKUP_PATHS=openviking maibot ...` 未加引号，`ringctl` 用 `. .env` 直接 source 时把后面的单词当命令执行 | ① `.env.example` / `ring-init.sh` 生成的值加引号；② `ringctl` 改为逐行解析 `KEY=VALUE`（`load_env()` 不再 source），兼容用户手写的不带引号的旧 `.env` |
