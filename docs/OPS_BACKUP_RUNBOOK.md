# RING 云端状态异地备份 —— 实施记录与恢复手册 (runbook)

> 实施日期：2026-11-08（UTC 10:15–10:25）
> 目标机：AWS Lightsail `lightsail` = 52.64.65.113，Debian 13.7，hostname `ip-172-26-8-250`，用户 `admin`（sudo 免密）
> 设计依据：`deliverables/backup-design-draft.md`（本次实施以该草案为唯一依据，偏离处逐条标注）
> 状态：**已落地并跑通一次真实备份 + 一次恢复演练**（2026-11-08 10:22 UTC）

---

## 0. ⚠️ 与草案的唯一实质偏离：目的地是 `/dav/OneDriveNew/`，不是 `/dav/OneDrive/`

草案 §5.2 把"WebDAV 可写"列为唯一未验证假设。本次实测结论：**`/dav/OneDrive/` 这个挂载本身是坏的**，与 Caddy、与账号权限都无关。

证据链（全部在本机 127.0.0.1:5244 上绕过 Caddy 复测，排除反代因素）：

| 探测 | `/dav/test/`（Local 驱动） | `/dav/OneDrive/` | `/dav/OneDriveNew/` | `/dav/GDrive/` | `/dav/Baidu/` |
|---|---|---|---|---|---|
| MKCOL | 201 | **405** | 201 | 201 | 201 |
| PUT | 201 | **405** | 201 | 201 | 201 |
| PROPFIND(子目录) | 207 | 取不到内容 | 207 | 207 | 207 |

同一账号（`ringbackup`，permission=904 含 bit3/7/8/9）在 Local / GDrive / Baidu 挂载上全部可写 ⇒ 账号与 WebDAV 实现没问题。
OpenList 服务端日志（`/opt/openlist/data/log/log.log`）里的真实原因：

```
failed make dir /OneDrive/ring-backup: Please try again later.
failed put /OneDrive/ring-backup: Please try again later.
failed list /OneDrive: Please try again later.
```

这是 OpenList 对 **Microsoft Graph 调用失败**的透传文案。对比 `x_storages` 表里两个挂载的 refresh_token：

* `/OneDrive`（id=2）= 旧格式 `1.Ab…`，len=1453，sha8=`6a165384` → 已失效
* `/OneDriveNew`（id=8）= 新 MSAL 格式 `M.C5…`，len=437，sha8=`bb9e746d` → 有效

即：同一个 OneDrive 网盘账号，旧的授权挂了，后来在 OpenList 后台重新授权过一次，生成的是 `/OneDriveNew`。

**处理方式（未改动用户任何既有配置）**：备份端点指向 `https://ol.namespace.cyou/dav/OneDriveNew/ring-backup`，并把它收敛成 `/etc/ring/backup.env` 里的**单一变量 `DAV_BASE`**。

> 想切回 `/dav/OneDrive/`：在 OpenList 后台对 id=2 的 OneDrive 存储点"重新授权"（走浏览器 OAuth），然后用 `sudo curl -X MKCOL -u "$DAV_USER:$DAV_PASS" https://ol.namespace.cyou/dav/OneDrive/ring-backup/` 验证返回 201，最后只改 `/etc/ring/backup.env` 的 `DAV_BASE` 一行即可，脚本无需改动。
> 建议顺手把坏的 id=2 挂载删掉或改名，避免以后有人再踩。

---

## 1. 交付物（服务器）

```
/opt/ring/backup/bin/ring-backup.sh          主脚本（bash，幂等，set -euo pipefail）
/opt/ring/backup/bin/sqlite_snapshot.py      SQLite 一致性快照（Connection.backup() + quick_check）
/opt/ring/backup/bin/webdav_retention.py     远端保留策略 7 日 / 4 周 / 12 月
/opt/ring/backup/.passphrase                 GPG 口令，root:root 600（44 字节 base64）
/opt/ring/backup/logs/backup-YYYYmmdd.log    每次运行的全量日志（tee 到 journald 同款内容）
/etc/ring/backup.env                         DAV_BASE / DAV_USER / DAV_PASS，root:root 600
/etc/systemd/system/ring-backup.service      oneshot，User=root
/etc/systemd/system/ring-backup.timer        OnCalendar=*-*-* 04:10:00 Asia/Shanghai
/var/backups/ring/spool/                     本地暂存，只保留最近 2 份
```

本地仓库侧：`deliverables/backup-runbook.md`（本文件）。
脚本源码另存一份在工作区 `.tmp/`：`ring-backup.sh.preview`、`sqlite_snapshot.py`、`webdav_retention.py`（与服务器上 sha256 一致）。

已安装版本指纹：

```
ring-backup.sh        8868 bytes  sha256 7e4601bddac73b198c9739ade6daff9a57c6e25a79b49cc319c8bcc4b764ff7e
sqlite_snapshot.py    4066 bytes  sha256 61fcd4b6eb9f36d54cfe2adccef6c193af7d002ab9e37961d5c69f9ea2b1e2dd
webdav_retention.py   4670 bytes  sha256 20b329deda54cf022ef0367c465c6c5592dc3b22b5df015d5170c8834ea92119
```

## 2. 这一次真实跑出来的东西

远端 `/dav/OneDriveNew/ring-backup/`（PROPFIND Depth:1 实测）：

```
manifest.json                                            1531   "最新一次运行"的指针，每天覆盖
ring-backup-20261108T101915Z.tar.gz.gpg               2299380   手动首跑
ring-backup-20261108T101915Z.tar.gz.gpg.sha256            106
ring-backup-20261108T101957Z.tar.gz.gpg               2299453   systemd 首跑
ring-backup-20261108T101957Z.tar.gz.gpg.sha256            106
ring-backup-20261108T102205Z.tar.gz.gpg               2299505   ← 恢复演练用的就是这一份
ring-backup-20261108T102205Z.tar.gz.gpg.sha256            106
ring-backup-20261108T102205Z.tar.gz.gpg.manifest.json    1531   每包自带的 manifest（101915Z/101957Z 是加这个特性之前跑的）
```

本次用于演练的包：

```
artifact   ring-backup-20261108T102205Z.tar.gz.gpg
size       2299505 bytes
sha256     28d5efb6df4b6c81c400a100018c82d7090d84c727d291af29a6b42018d7a5e1
entries    494
明文大小   20778327 bytes（stage 树）→ 2299386 bytes（gzip -6）→ 2299505（gpg）
耗时       ~13 s 全程（含上传+校验+保留策略）
内存峰值   systemd 记账 53.9M（`systemctl status` 的 Mem peak），远低于 2GB 机器余量
```

## 3. 脚本做什么（7 步，顺序即代码顺序）

1. **stage 冷拷贝**：`tar -C / … | tar -C $STAGE/root -xpf -`，收集清单见 §3.1；排除 `maibot/logs`、`maibot/plugins`、`napcat/qq`、`*.bak*`、`__pycache__`、`*.pyc`。`tar rc=1`（读的时候文件变了）容忍并记录，`rc>1` 直接失败。
2. **SQLite 一致性快照**：`sqlite_snapshot.py` 遍历 stage 树，按魔数 `SQLite format 3\x00` 识别库 → `Connection.backup()` 重写到自洽单文件 → `PRAGMA quick_check` → 成功后删掉 stage 里的 `-wal`/`-shm`。失败则从 live 重新拷 `db+wal+shm` 重试 3 次，仍失败就整次运行失败（不上传）。
3. **采集基线**：viking 文件数 / jsonl 数 / names-memories md 数 / sessions 数，以及 OV API `/api/v1/stats/memories`（写进 manifest 供以后比对）。
4. **打包加密**：`tar --use-compress-program='gzip -6' --numeric-owner --owner=0 --group=0` → `gpg --batch --yes --pinentry-mode loopback --passphrase-file … --symmetric --cipher-algo AES256 --s2k-digest-algo SHA512 --s2k-count 65011712` → `sha256sum` sidecar → 写 `<包名>.manifest.json`。
5. **上传**：`curl -T` 推 包 / .sha256 / .manifest.json / manifest.json（每个都 `--fail-with-body --retry 3 --retry-delay 15 --retry-all-errors --max-time 900`）。
6. **回验**：`curl -I` 取远端 `Content-Length` 与本地字节数逐字节比对；再把远端 `.sha256` 读回来 grep 本地 sha256。任一不符 → 整次运行失败。
7. **保留策略 + 本地 spool 收敛**：`webdav_retention.py --keep-daily 7 --keep-weekly 4 --keep-monthly 12`，删除时一并删 `.sha256` 和 `.manifest.json`，404 忽略；保留策略失败**只告警不影响备份成功判定**。本地 spool `ls -1t | tail -n +3` 只留最近 2 份。

其它硬约束：`flock -n /run/lock/ring-backup.lock`（防重入）、`trap on_exit EXIT` 清理 stage、`trap … ERR` 打印出错行号、全程 `tee -a /opt/ring/backup/logs/backup-YYYYmmdd.log`。
**脚本全程不 stop/restart/disable 任何服务**，也不写 `/opt/ring/app` 与 Caddy 配置。

### 3.1 收集清单（脚本里的 `SRC` 数组，逐项）

```
opt/ring/data/openviking                                          OpenViking 全套（workspace/viking、vectordb、records、ov.conf、api key）
opt/ring/maibot/data                                              MaiBot 数据（MaiBot.db、a-memorix、plugins 内 db）
opt/ring/maibot/config
opt/ring/toolenv/maibot/lib/python3.13/site-packages/src/maisaka/memory   边聊边记补丁
opt/ring/napcat/config
opt/ring/app                                                      config / litellm / soul 等（88 个文件）
etc/caddy/Caddyfile
etc/systemd/system/ring-cloud.service
etc/systemd/system/ring-maibot.service
etc/systemd/system/ring-openviking.service
opt/openlist/data/config.json                                     OpenList 自身配置（含存储定义，不含口令明文哈希）
opt/openlist/data/data.db                                         OpenList 元数据（账号/存储）
opt/ring/astrbot/data                                             条件收集：不存在则跳过（本机已卸载，实际跳过）
opt/ring/maibot/backup                                            条件收集
```

> 实测 `/opt/ring/astrbot/data` 不存在（已改名 `/opt/ring/astrbot.removed-20261108`，AstrBot 已卸载），日志里会打 `note: /opt/ring/astrbot/data absent, skipped`。

## 4. 关键实现决定（含被推翻的草案细节）

| # | 决定 | 理由 |
|---|---|---|
| 1 | **不排除 `-wal`/`-shm` 再 tar**（草案 §3.3 的写法有坑） | 所有库都是 WAL 模式且 wal 有 4.1MiB 在飞的写入；只拷 `.db` 会丢最新事务。改为"连 wal 一起拷 → 打开让 SQLite 重放 → `Connection.backup()` → 删 stage 里的 wal/shm"。 |
| 2 | `gzip -6`，**不用** zstd -19 / xz | 实测峰值 107/117MiB，这台 1936MiB + swap 已经吃紧；gzip -6 把 20.8MiB 压到 2.30MiB，13 秒完成。 |
| 3 | LevelDB（`workspace/vectordb`）**热拷贝**，不停机 | 用户拍板：接受最终一致，靠 OpenViking reindex 兜底。脚本里没有任何 `systemctl stop/restart`。 |
| 4 | 每包一份 `<包名>.manifest.json`，另外再传一份会被覆盖的 `manifest.json` 当"最新指针" | 只保留一个 manifest.json 的话，三个月后你去恢复旧包会拿到错的中文说明。 |
| 5 | 保留策略失败不判定备份失败 | DELETE 抖动不该让一次成功的备份变红；但会在日志里明确写 `retention: N deletion failure(s)`。 |
| 6 | 口令文件 `/opt/ring/backup/.passphrase` 只在服务器、**不进任何备份内容** | manifest 里只写"口令见 /opt/ring/backup/.passphrase"。 |
| 7 | `OnFailure=` 只留注释位 | 用户要求本次不做告警，但失败必须进 journald + 日志文件，以后接 ntfy 只需加一行。 |

## 5. GPG 口令（明文，仅此一份，请立刻另存）

```
WATJ0lxtgq0tg6ZPH1iMqRJOVvtKOYonk8JPGgIyjtY=
```

* 来源：`head -c 32 /dev/urandom | base64 -w0` → 44 字符（32 字节熵）。
* 服务器位置：`/opt/ring/backup/.passphrase`（`root:root`，`600`，无换行）。
* **这个口令丢了 = 所有备份都打不开**。服务器本地只有一份，建议立刻存进你的密码管理器（1Password / Bitwarden 等）。
* 轮换：`sudo sh -c 'head -c 32 /dev/urandom | base64 -w0 > /opt/ring/backup/.passphrase'`，然后**旧包需要旧口令才能解**——所以轮换前请确认旧口令另外存着。
* 不使用 passphrase 的替代路径（未采用）：`gpg --export-secret-keys` 公钥加密 + 私钥离线保存。本次按用户拍板用对称加密，简单可控。

## 6. 调度

```
$ systemctl list-timers ring-backup.timer --no-pager
NEXT                        LEFT LAST PASSED UNIT              ACTIVATES
Sun 2026-11-08 20:10:58 UTC   9h -         - ring-backup.timer ring-backup.service
```

`20:10:58 UTC` = `2026-11-09 04:10:58 Asia/Shanghai`。
机器系统时区是 `Etc/UTC`（`timedatectl show -p Timezone` = `Etc/UTC`），所以 **journald 时间戳都是 UTC**，unit 里用 `OnCalendar=*-*-* 04:10:00 Asia/Shanghai` 显式绑时区，不受系统时区影响。

```ini
# /etc/systemd/system/ring-backup.timer
[Timer]
OnCalendar=*-*-* 04:10:00 Asia/Shanghai
RandomizedDelaySec=5m     # 实际触发会在 04:10:00–04:15:00 之间随机
AccuracySec=1min
Persistent=true           # 睡过点会补跑（开机后补一次）
```

```ini
# /etc/systemd/system/ring-backup.service（节选）
[Unit]
After=network-online.target
Wants=network-online.target
# Alerting is intentionally not wired yet. When an ntfy/other channel exists, add:
# OnFailure=ring-backup-alert@%n.service

[Service]
Type=oneshot
User=root
ExecStart=/opt/ring/backup/bin/ring-backup.sh
TimeoutStartSec=3600
Nice=10
```

## 7. 日常运维（可以照抄）

```bash
# 手动跑一次（和 timer 走完全相同的路径）
sudo systemctl start ring-backup.service
sudo systemctl status ring-backup.service --no-pager | head -12
sudo journalctl -u ring-backup.service --no-pager -n 40

# 看下次触发
systemctl list-timers ring-backup.timer --no-pager

# 今天的日志
sudo tail -50 /opt/ring/backup/logs/backup-$(date -u +%Y%m%d).log

# 看远端有什么（凭据在 /etc/ring/backup.env，root only）
sudo sh -c 'set -a; . /etc/ring/backup.env; set +a; \
  curl -sS -u "$DAV_USER:$DAV_PASS" -X PROPFIND -H "Depth: 1" \
    --data "<D:propfind xmlns:D=\"DAV:\"><D:prop><D:getcontentlength/></D:prop></D:propfind>" \
    "$DAV_BASE/"'

# 本地 spool（只留最近 2 份）
ls -l /var/backups/ring/spool/
```

判定标准：日志结尾出现 `=== ring-backup OK ===` + `verified: remote artifact matches local sha256 …`。出现 `=== ring-backup FAILED rc=N ===` 就去 logs 里找 `FAILED:` 那行。

## 8. 恢复手册

### 8.1 只取某个文件出来看（最常见，零风险）

```bash
set -a; . /etc/ring/backup.env; set +a
ART=ring-backup-20261108T102205Z.tar.gz.gpg      # 换成你要的那个
mkdir -p /tmp/restore && cd /tmp/restore
curl -sS --fail-with-body -u "$DAV_USER:$DAV_PASS" -O "$DAV_BASE/$ART"
curl -sS --fail-with-body -u "$DAV_USER:$DAV_PASS" -O "$DAV_BASE/$ART.sha256"
sha256sum -c "$ART.sha256"                        # 必须 OK 再往下

export GNUPGHOME=/tmp/restore/gnupg; mkdir -p "$GNUPGHOME"; chmod 700 "$GNUPGHOME"
gpg --batch --pinentry-mode loopback \
    --passphrase-file /opt/ring/backup/.passphrase \
    --decrypt --output "$ART.tar.gz" "$ART"

tar -tzf "$ART.tar.gz" | head -50                 # 先看清单
tar -xzf "$ART.tar.gz" -C ./root './opt/ring/app'  # 只解某个子树
```

### 8.2 整机/整服务恢复（会覆盖线上目录，先备份现状）

> ⚠️ 下面这条会写线上目录，执行前人要在场、且先确认"现状已另存一份"。演练时我们只做到解压 + 比对，没有覆盖。

```bash
# 0) 现状先留一份（万一恢复错了还能回退）
sudo tar -czf /tmp/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).tar.gz \
     /opt/ring/data/openviking /opt/ring/maibot/data /opt/ring/app

# 1) 停服务（恢复期间停）
sudo systemctl stop ring-maibot ring-openviking

# 2) 解包到临时目录
cd /tmp/restore && mkdir -p root && tar -xzf "$ART.tar.gz" -C root

# 3) 覆盖回去（按需挑选子树；下面是最小集）
sudo cp -a root/opt/ring/data/openviking/. /opt/ring/data/openviking/
sudo cp -a root/opt/ring/maibot/data/.     /opt/ring/maibot/data/
sudo cp -a root/opt/ring/maibot/config/.   /opt/ring/maibot/config/
sudo cp -a root/opt/ring/app/.             /opt/ring/app/
sudo cp -a root/etc/caddy/Caddyfile        /etc/caddy/Caddyfile
sudo cp -a root/etc/systemd/system/ring-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo caddy validate --config /etc/caddy/Caddyfile

# 4) 起服务
sudo systemctl start ring-openviking ring-maibot
sudo systemctl status ring-openviking ring-maibot --no-pager | head -20

# 5) OpenViking 索引兜底（LevelDB 是热拷贝，可能落后）：调 reindex
curl -s -H "Authorization: Bearer $(sudo cat /opt/ring/data/openviking/user_api_key.txt)" \
     -X POST http://127.0.0.1:1933/api/v1/reindex      # 具体路径以 OV 0.5.3 为准
curl -s -H "Authorization: Bearer $(sudo cat /opt/ring/data/openviking/user_api_key.txt)" \
     http://127.0.0.1:1933/api/v1/stats/memories       # 期望 total_memories=5, entities=2, events=3
```

### 8.3 恢复自检清单（照抄）

```bash
# 记忆基线
M=/opt/ring/data/openviking/workspace/viking/default/user/names/memories
find $M -maxdepth 1 -name '*.md' ! -name '.*' | wc -l    # 期望 5  (total_memories)
find $M/entities -name '*.md' | wc -l                     # 期望 2
find $M/events   -name '*.md' | wc -l                     # 期望 3
find /opt/ring/data/openviking/workspace/viking -type f | wc -l   # 期望 107

# SQLite 完好性（逐个库 quick_check）
python3 - <<'PY'
import os, sqlite3
for dp,_,fns in os.walk("/opt/ring"):
    for n in fns:
        if not n.endswith((".db",".sqlite3")): continue
        p=os.path.join(dp,n)
        if open(p,"rb").read(16)!=b"SQLite format 3\x00": continue
        c=sqlite3.connect("file:%s?mode=ro"%p, uri=True)
        print(p, c.execute("PRAGMA quick_check").fetchone()[0]); c.close()
PY
```

## 9. 本次验收证据（逐条对照）

| 验收项 | 结果 | 证据 |
|---|---|---|
| `systemctl list-timers | grep ring-backup` 有下次触发 | ✅ | `NEXT Sun 2026-11-08 20:10:58 UTC … ring-backup.timer ring-backup.service`（= 2026-11-09 04:10 Asia/Shanghai） |
| timer enabled + active | ✅ | `systemctl is-enabled` = `enabled`，`is-active` = `active`（`timers.target.wants/` 软链已建） |
| 远端有本次包、HTTPS 校验大小一致 | ✅ | 包 `ring-backup-20261108T102205Z.tar.gz.gpg` 2299505 B；远端 `Content-Length` 2299505 = 本地，且回读远端 `.sha256` 与本地 sha256 `28d5efb6…a5e1` 一致 |
| 解密后 `tar -t` 能列全部条目且与清单一致 | ✅ | `tar -tzf` = **494** entries，manifest `tar_entries` = **494**，match=YES |
| 归档里没有残留 `-wal`/`-shm` | ✅ | `tar -tzf … | grep -E -- '-wal|-shm'` 输出为空；8 个库全部 `quick_check=ok` |
| 恢复演练记忆条数与基线一致 | ✅ | 解出来的 names/memories：**5** profile md / **2** entities / **3** events，与 manifest 里备份当刻的 API 快照 `total_memories=5, entities=2, events=3` 逐项吻合；viking 107 文件 / 7 jsonl 也一致 |
| 关键配置文件齐全且一致 | ✅ | Caddyfile、三个 ring-*.service、`ov.conf`、`user_api_key.txt`、`/opt/openlist/data/config.json`、`root_api_key.txt` 全部 **SAME**（sha256）；`/opt/ring/app` 88/88 文件逐字节相同，`maibot/config` 3/3、`napcat/config` 5/5 相同 |
| 没动任何既有服务 | ✅ | `ring-cloud` since 2026-11-05T18:49:47Z、`ring-openviking` since 2026-11-07T13:56:34Z、`ring-maibot` since 2026-11-08T10:02:32Z、`caddy` since 2026-10-22T13:54:20Z —— 备份发生在 10:19–10:22Z，这些 `ActiveEnterTimestamp` 都没变 |
| 资源占用可接受 | ✅ | systemd 记账 Mem peak **53.9M**，CPU 1.19s，全程 13s；跑完 `free -m`：used 1236 / available 700 |
| 演练目录已清理 | ✅ | `/tmp/ring-restore-test` 已 `rm -rf`；`/root/.ring-dav-test` 已删（凭据只在 `/etc/ring/backup.env`） |

## 10. 风险 / 未验证项（诚实清单）

1. **`/OneDrive` 挂载仍然是坏的**（Microsoft Graph 报错）。备份实际落在 `/OneDriveNew`。如果哪天有人把 `/OneDriveNew` 也删了/重新授权，备份会立刻 405 失败（而且脚本会在第 5 步就失败退出，不会静默成功）。建议：清理坏的 id=2 挂载。
2. **只有一个异地目的地**（OneDrive），没有第二副本。OpenList/OneDrive 侧出问题 = 备份没了。草案里的 R2 双写按用户拍板本次不做。
3. **OpenViking LevelDB 是热拷贝**，备份瞬间可能落后于真实状态（eventual consistency）。恢复后必须跑 reindex；`/api/v1/reindex` 的确切路径未在本次验证（只验证了 `/stats/memories`），恢复时按 OV 0.5.3 实际接口来。
4. **告警没接**：失败只会进 journald + 日志文件，没人主动通知你。`ring-backup.service` 里已留 `# OnFailure=…` 注释位。
5. **口令单点**：`/opt/ring/backup/.passphrase` 只有服务器一份，丢了等于所有备份作废。本次报告里给了明文，请立刻另存。
6. **保留策略只验证过"不删"的方向**：现在远端只有 3 个包，7/4/12 的删除分支没有被真实触发过（`retention: remote=3 keep=3 drop=0`）。逻辑是"最新 7 日 ∪ 最新 4 个 ISO 周 ∪ 最新 12 个自然月 ∪ 本次"，首次真正删除要等包数量超限；真到那天建议看一眼日志。
7. **timer 的 04:10 真实触发还没发生过**（今天刚 enable）。下一次 `2026-11-09 04:10:58 Asia/Shanghai`，届时看 `systemctl list-timers` 的 `LAST` 是否被填上。
8. **OpenList 账号 `ringbackup` 的权限是手改数据库 + 走 admin API 刷缓存得到的**（`permission=904`）。OpenList 升级后如果重置了权限模型，需要重新确认 bit8(WebDAV 读) / bit9(WebDAV 写) 还在。
9. **OpenList 的 WebDAV BasicAuth 失败 5 次会锁 IP 5 分钟**（`DefaultMaxAuthRetries=5`，`DefaultLockDuration=5m`）。`/etc/ring/backup.env` 里的口令写错会导致备份连续失败且被 429 —— 看到 429 先等 5 分钟再排查。
10. **本机时区是 UTC**，日志和 journald 都是 UTC，看日志时注意 +8 换算。
11. **两个早期测试包**（`…101915Z`、`…101957Z`）留在远端，缺 per-artifact manifest，功能上完全可用；不想要可以手动 DELETE。演练只用了最新的 `…102205Z`。

## 11. 变更记录

| 时间 (UTC) | 动作 |
|---|---|
| 2026-11-08 10:15 | 建 `/opt/ring/backup/{bin,logs}`、`/var/backups/ring/spool`；生成口令；写 `/etc/ring/backup.env` |
| 2026-11-08 10:17 | 推三个脚本（sha256 已核对）；`bash -n` + py `compile()` 通过 |
| 2026-11-08 10:18 | WebDAV 写测试：MKCOL 201 / PUT 201 / HEAD 37=37 / DELETE 204（打在 `/OneDriveNew/ring-backup/`） |
| 2026-11-08 10:19 | 手动首跑成功（11s，包 2299380 B） |
| 2026-11-08 10:19–10:20 | 装 `ring-backup.service`/`.timer`，`systemd-analyze verify` OK，`enable --now`，systemd 首跑成功（2299453 B，Mem peak 55.1M） |
| 2026-11-08 10:20 | 第一次恢复演练（…101957Z）：sha 校验 OK、494 条目、5/2/3 计数吻合、8 库 quick_check=ok、关键配置全 SAME |
| 2026-11-08 10:21 | 加"每包一份 manifest"特性，重推脚本 |
| 2026-11-08 10:22 | systemd 第三跑成功（2299505 B）；最终恢复演练用这一份，全部自检通过；清理 `/tmp/ring-restore-test` 与 `/root/.ring-dav-test`、删除探针目录 `/dav/OneDriveNew/ring-bk-probe/` 与 `/dav/test/ring-bk/` |
