# SnowLuma / QQ 适配器：重连指数退避 + 失败日志节流（补丁材料）

本目录是 MaiBot 第三方插件 `maibot-team.snowluma-adapter`（SnowLuma / QQ 适配器）
一处**尚未上线**的现场改造：断线重连从固定 5 秒改为指数退避（封顶 300 秒），
连续失败的 `warning` 按 300 秒窗口节流。补丁只碰 `transport.py`，不改配置结构、
不改对外协议、不改既有日志文案。

> 定位：这是**补丁交付**，不是已部署状态。服务器上插件文件仍是原样
> （`transport.py` sha256 `e550026f…`），套用与回滚由人工决定，步骤见 §6 / §7。

## 1. 现象与动机

QQ 掉线时 NapCat 不会启动 OneBot 正向 WebSocket 监听，适配器 `_connection_loop`
因此每 `reconnect_delay_sec`（默认 5 秒）失败一次，并每次打一条完整 `warning`：

```
SnowLuma 适配器连接失败:ws://127.0.0.1:3001/；目标端口拒绝连接…；将在 5 秒后重连
```

两个后果：

1. **日志刷屏**：一次几十分钟的掉线会产出数百条内容完全相同的 warning，
   真正有价值的其他日志被淹没；
2. **无退避**：白天短暂抖动与「QQ 根本没登录、NapCat 永远不会监听」被同等对待，
   后者纯属无效重试，却仍然 5 秒一次地敲端口。

QQ 重新登录后适配器会自动连上（本次已复现：重登后马上恢复），所以**不需要**
改重试次数上限或加熔断；需要的只是「越失败越慢」+「同样的失败少说几遍」。

## 2. 适用版本（实测）

| 组件 | 版本 / 事实 |
| --- | --- |
| 插件 | `maibot-team.snowluma-adapter` **1.1.13**（tag `v1.1.13`） |
| 插件 git | HEAD `9b409b1920291f5f12f31c68b0b41604ea40a78a`（`fix: 修复客户端识别与通知黑名单`），分支 `master` |
| 上游仓库 | https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter |
| 插件目录 | `/opt/ring/maibot/plugins/maibot-team_snowluma-adapter`（`transport.py` 在包根，无 `src/`） |
| 宿主进程 | `ring-maibot.service`（MaiBot / MaiSaka WebUI） |
| Python | 3.13.5（venv `/opt/ring/toolenv/maibot`） |

补丁上下文是对**服务器现状文件**（未打补丁的 1.1.13）生成的，行号即实测行号。
上游一旦改动 `transport.py`，`patch` 会因为上下文不匹配而拒绝（安全失败），
需重新生成 diff 而不是放宽匹配。

## 3. 为什么「改配置」做不到

运行时配置里**只有**一个与重连相关的旋钮，就是固定等待时长：

- `constants.py:7` — `DEFAULT_RECONNECT_DELAY_SEC = 5.0`
- `config.py:479-494` — `reconnect_delay_sec: float = Field(default=DEFAULT_RECONNECT_DELAY_SEC, ...)`，
  `label` 为「重连等待（秒）」，`order` 5，即 WebUI 配置页上的那一个输入框
- `config.py:601-624` — `@field_validator("heartbeat_interval", "reconnect_delay_sec", "action_timeout_sec", mode="before")`
  的 `_normalize_positive_float_fields`：只做「必须为正浮点，非法就回退默认值」的规范化，
  没有任何上限、倍数、开关语义
- 实际生效值：`config.toml` 第 22 行 `reconnect_delay_sec = 5.0`（同文件的 client token
  是本机密钥，按惯例不在本目录留副本）

也就是说配置**能**做的只有「把 5 秒改成 30 秒」这种线性拉伸：抖动也会一起变慢，
而且依然是「无限重试 + 每次都打 warning」。缺的是三样东西——
**最大重试次数、退避开关、失败日志级别**——三者在 1.1.13 的配置模型里都不存在
（`config.py` 里 `reconnect` 只有上述 479/603/622 三处命中），所以只能改代码。

## 4. 补丁内容

`reconnect-backoff.patch`：7 个 hunk，`65 insertions(+), 7 deletions(-)`，
只改 `transport.py`（`--- a/transport.py` / `+++ b/transport.py`，可直接 `-p1`）。

| hunk | 位置（打补丁前 → 后） | 内容 |
| --- | --- | --- |
| 1 | `@@ -10,6 +10,7 @@` | 在 `import socket` 后加 `import time`（节流要用 `time.monotonic`） |
| 2 | `@@ -37,6 +38,12 @@` | 模块级常量：`RECONNECT_BACKOFF_EXPONENT_CAP = 6`、`MAX_RECONNECT_DELAY_SEC = 300.0`、`FAILURE_LOG_THROTTLE_SEC = 300.0` |
| 3 | `@@ -70,6 +77,9 @@` | `__init__` 增加 `_reconnect_attempt: int = 0`、`_failure_log_monotonic: Optional[float] = None`、`_failure_log_suppressed: int = 0` |
| 4 | `@@ -209,16 +219,16 @@` | `_connection_loop`：连接成功后（`适配器已连接` 那行之后）把三个字段复位；原内联 `logger.warning(...)` 换成 `self._log_connection_failure(display_url, server_config, exc)` |
| 5 | `@@ -227,7 +237,10 @@` | `_connection_loop` 末尾：`await asyncio.sleep(server_config.reconnect_delay_sec)` → `delay = self._next_reconnect_delay(server_config)`、`self._reconnect_attempt += 1`、`await asyncio.sleep(delay)` |
| 6 | `@@ -388,6 +401,51 @@` | 新增 `_next_reconnect_delay()` 与 `_log_connection_failure()` 两个方法 |
| 7 | `@@ -493,7 +551,7 @@` | `_build_reconnect_hint()`：`{server_config.reconnect_delay_sec:g}` → `{self._next_reconnect_delay(server_config):g}` |

### 4.1 退避公式

```python
def _next_reconnect_delay(self, server_config: QQServerConfig) -> float:
    exponent = min(self._reconnect_attempt, RECONNECT_BACKOFF_EXPONENT_CAP)   # 指数封顶 2**6
    return min(server_config.reconnect_delay_sec * 2**exponent, MAX_RECONNECT_DELAY_SEC)  # 总上限 300s
```

- base 取配置里的 `reconnect_delay_sec`，所以 WebUI 上「重连等待（秒）」仍然有意义：
  它就是**第一次**重连的等待时间，并且是整条阶梯的起点。
- 实测序列（base=5）：`5, 10, 20, 40, 80, 160, 300, 300, …`（第 7 次起恒定 300 秒）。
- 下界不被压低：base 大于 300 时直接取 300（例如 base=200 → 300）；
  base=2.5 的阶梯是 `2.5, 5, 10, 20, 40, 80, 160, 160, …`（先撞指数封顶）。
- `_reconnect_attempt` 只在 `await asyncio.sleep()` **之前**自增，且只在**连接成功后**清零，
  因此「连上又掉」会重新从 base 开始，不会因为历史失败一直停在 300 秒。

### 4.2 失败日志节流

`_log_connection_failure()` 的规则：

1. 首次失败（`_failure_log_monotonic is None`）→ 立刻输出**完整 warning**，
   文案与原实现逐字一致（前缀 `SnowLuma 适配器连接失败:`、错误描述、重连提示三段的拼接顺序不变）；
2. 300 秒窗口内的后续失败 → 只有 `logger.debug`，内容带 `（已节流）` 与
   `（连续失败 N 次）`，并累加 `_failure_log_suppressed`；
3. 窗口过期后的下一条失败 → 恢复完整 warning，并在末尾追加
   `（此前的 N 次同类失败已省略）`，计数归零；
4. 连接成功 → 节流窗口与计数一起清零。

净效果：无论掉线多久，warning 频率上限都是「每 5 分钟一条」，且每条都说明中间省略了多少次；
排查时把日志级别调到 debug 依然能看到每一次失败。

### 4.3 兼容性／不变量

- **`将在 5 秒后重连` 文案原样保留**：第一轮失败时 `_reconnect_attempt == 0`，
  `_build_reconnect_hint()` 求值为 `；将在 5 秒后重连`，与打补丁前完全相同；
  插件自带回归测试 `tests/test_transport_errors.py:76` 的断言因此仍然成立（实测见 §9.5）。
- `logger.warning` 仍然是**单参数**字符串调用（测试里有 `logger.warning.call_args.args[0]`），
  新 helper 没有引入 `%s` 占位或 `extra=`。
- 脱敏逻辑（`_redact_connection_error`）、错误描述（`_describe_connection_error`）、
  token 缺失提示都**未改动**，节流只决定「说不说」，不改变「说什么」。
- 新增的都是私有成员，未触碰 `config.py` / `config.toml` / `constants.py`，
  所以 WebUI 配置页与配置文件格式不变，回滚时也不会残留不认识的配置项。

## 5. 目录内容与校验和

```
patches/snowluma-adapter/
├── README.md                  # 本文件
├── reconnect-backoff.patch    # 相对插件 1.1.13 现状文件的 unified diff（只含 transport.py）
├── transport.py               # 打补丁后的完整 transport.py（现状 + 补丁），可直接覆盖
└── verify_backoff.py          # 不依赖 aiohttp 的退避/节流验证脚本（25 条断言）
```

| 文件 | 字节 | sha256 |
| --- | --- | --- |
| reconnect-backoff.patch | 5802 | 280767427d2d78482de8d7c8cd8eb9b0d76fe8f994a9668041c94c678624c1d0 |
| transport.py（打补丁后） | 25199 | d89f6aa295fdeec2a3da03266c485da72e53bdc7c585ef0339d390937874afcd |
| verify_backoff.py | 14589 | ca1e1cba1a6d1cd1718075164f9d8ca24638861660ddb75e1961893988856068 |

服务器上**打补丁前**的原始 `transport.py`（生成 diff 的基准）：

| 文件 | 字节 | sha256 |
| --- | --- | --- |
| 插件根 `transport.py`（1.1.13 现状） | 22325 | e550026f30e650133ee3c83d24ab8b8fb84fb6e73e6d6a65c3ee0b2171bcfa0b |

核对命令：

```bash
sha256sum transport.py reconnect-backoff.patch verify_backoff.py
```

## 6. 应用步骤（服务器，需要 sudo 才能重启服务）

```bash
PLUG=/opt/ring/maibot/plugins/maibot-team_snowluma-adapter
TS=$(date -u +%Y%m%d%H%M%S)
BK=/opt/ring/maibot/backup/snowluma-adapter-$TS
mkdir -p "$BK" && cp -a "$PLUG/transport.py" "$BK/transport.py"

# 1) 先只检查：必须打印 "checking file transport.py" 且退出码 0
cd "$PLUG" && patch -p1 --dry-run -i /path/to/reconnect-backoff.patch

# 2) 真打
cd "$PLUG" && patch -p1 --forward -i /path/to/reconnect-backoff.patch

# 3) 结果必须等于 d89f6aa2…
sha256sum "$PLUG/transport.py"

# 4) 语法自检（注意：不要在插件目录里跑 python，见下方告警）
cd /tmp && /opt/ring/toolenv/maibot/bin/python -m py_compile "$PLUG/transport.py" && echo compile-ok

# 5) 让适配器用上新代码
sudo systemctl restart ring-maibot
```

打完补丁后可以离线复验（不连服务器、不改插件）：

```bash
# 把 verify_backoff.py 放到插件目录之外，用插件目录自带的 transport.py 验证
cd /tmp && SNOWLUMA_TRANSPORT=$PLUG/transport.py \
  /opt/ring/toolenv/maibot/bin/python /path/to/verify_backoff.py
# 期望最后一行：OK: 全部 25 项断言通过
```

> **告警（真实踩过的坑）**：插件目录里有自己的 `types.py`，任何以插件目录为 cwd
> 或把插件目录塞进 `sys.path` 的 Python 调用都会遮蔽标准库 `types`，报
> `ImportError: cannot import name 'WrapperDescriptorType' from 'types'`。
> 所以 `verify_backoff.py` 必须放在插件目录**之外**运行（它内部按文件路径加载
> `transport.py`，也可用 `SNOWLUMA_TRANSPORT` 指定副本）。

## 7. 回滚

三种，按侵入性从低到高：

```bash
# A) 反向打补丁（补丁是纯文本改动，可逆）
cd /opt/ring/maibot/plugins/maibot-team_snowluma-adapter
patch -R -p1 --forward -i /path/to/reconnect-backoff.patch
sha256sum transport.py          # 应回到 e550026f…

# B) 用插件自己的 git（该目录是 1.1.13 的 git 检出，transport.py 是跟踪文件）
cd /opt/ring/maibot/plugins/maibot-team_snowluma-adapter
git checkout -- transport.py    # 注意：会丢掉该文件上的所有本地改动

# C) 用 §6 里 cp 出来的备份覆盖
cp -a /opt/ring/maibot/backup/snowluma-adapter-<时间戳>/transport.py .
```

回滚后同样需要 `sudo systemctl restart ring-maibot`。回滚**不需要**动 `config.toml`：
本补丁没有新增配置项，插件读到的仍然是原来的 `reconnect_delay_sec`。

## 8. 最大的风险：插件升级会整目录覆盖

WebUI 的「插件升级 / 重装」不是「解压覆盖」，而是**整目录 rename 替换**，
实现在
`/opt/ring/toolenv/maibot/lib/python3.13/site-packages/src/webui/routers/plugin/release_install.py`
（327 行）：

- `release_install.py:213-229` — `replace_files()`：先把新版本解到
  `.update_tmp/<name>.<uuid>`（`:202-203`），往候选目录写入 `.maibot-release.json`
  回执，然后 `target.rename(backup)` + `candidate.rename(target)`。**旧目录整体被挪走，
  新目录整体就位**——目录里任何文件（包括改过的 `transport.py`）都随之消失。
- `release_install.py:64-71` — `_preserve_user_files(source, target)`：升级前只会把
  `{"config.toml", "config_back", "data"}` 以及**未跟踪**的非 venv 文件搬过去；
  同时用 `git diff HEAD --name-only` 校验，若发现 `config.toml`/`.maibot-release.json`
  之外的**已跟踪文件**有本地改动，直接抛 409
  `插件存在本地代码修改，请先处理：<files>`，升级中止。

这条 409 其实帮了大忙，它把风险分成两种：

| 补丁状态 | 升级时的行为 | 后果 |
| --- | --- | --- |
| 只 `patch`、**未提交** git | 409 拒绝升级，列出 `transport.py` | 不会静默丢补丁，但会**卡住**升级，需要先处理 |
| 已 `git commit` 到插件仓 | 校验通过，升级照做，目录整体被替换 | 补丁**静默消失**，行为悄悄退回固定 5 秒 |

第二种情况并非不可挽回：`replace_files()` 返回的 `backup_path`（`:303`）指向
`.update_backups/<name>.<uuid>`，旧目录（含打过补丁的 `transport.py`）留在那里，
且不会被自动清理。可以从备份里取回补丁版本，或直接按 §6 对新版本重打。

### 应对建议（按推荐顺序）

1. **升级后立刻重打**：把 §6 的第 1 步（`--dry-run`）做成升级流程的一部分；
   上下文不匹配就说明上游动过 `transport.py`，此时应重新生成 diff 而不是强打。
2. **保留本地提交 + 记录**：把补丁提交进插件仓（附带 commit message 说明原因），
   这样升级触发的 409/备份行为可预测，也能用 `git log` 看出上一位维护者为什么改。
3. **不要依赖 WebUI 升级**：涉及本地改造的插件，用「检出上游 tag → 重打补丁 →
   重启服务」的脚本替代一键升级，把补丁套用变成幂等步骤。
4. **争取上游**：退避 + 节流对上游是普适收益（NapCat 未就绪是常见状态），
   理想结局是把 `MAX_RECONNECT_DELAY_SEC`/`FAILURE_LOG_THROTTLE_SEC` 做成配置项
   合进上游，本目录只作为过渡材料。

## 9. 验证记录（本次实测，未触碰服务器插件文件）

1. **本地脚本**（Windows，CPython 3.14.7，无 aiohttp）：
   `python verify_backoff.py` → 打印
   `base=5s 退避序列: 5, 10, 20, 40, 80, 160, 300, 300`、
   `_connection_loop 实际间隔: 5, 10, 20, 40, 80`、
   `连接成功后重置为: 5, 10（第二段重新按阶梯增长）`，
   末行 `OK: 全部 25 项断言通过`，退出码 0。
2. **补丁可应用性**：对服务器原始 `transport.py` 的字节级副本，
   `git -c core.autocrlf=false apply --check -p1` 与 GNU
   `patch -p1 --dry-run --forward` 均通过，产物 sha256 = `d89f6aa2…`，
   与手写的 `transport.py` 逐字节相同（`--stat`：`1 file changed, 65 insertions(+), 7 deletions(-)`）。
3. **服务器侧应用**：把插件目录整份复制到 `/tmp/sl-verify/plugins/MaiBot-SnowLuma-Adapter-main`
   （**只是副本**），在其上 `patch -p1 --forward`，`sha256sum` 得到
   `e550026f… → d89f6aa2…`，与本地一致。
4. **服务器侧带真实 aiohttp 复验**：
   `SNOWLUMA_TRANSPORT=…/transport.py /opt/ring/toolenv/maibot/bin/python verify_backoff.py`
   （脚本放在 `/tmp` 下运行以避开 `types.py` 遮蔽）→ 同样 `OK: 全部 25 项断言通过`。
5. **插件自带回归测试**：`tests/test_transport_errors.py` 在**打补丁后的副本**上跑，
   14 个用例（13 个 parametrize 展开 + 1 个脱敏用例）**全部通过**，
   包括 `:76` 的 `assert "将在 5 秒后重连" in message`。该 venv 里没有 pytest，
   所以用一个最小 `pytest.mark`/`parametrize`/`monkeypatch` 桩来驱动同一份测试文件；
   这是**等价但不等同**的执行方式（见 §10）。

## 10. 未验证 / 需要人工确认

1. **没有在真实掉线场景下连续观察**：本次验证全是离线（桩 + 副本），没有断网、
   没有退出 QQ 来跑真实的「NapCat 不监听 → 适配器重连」链路；
   实际日志密度（是否真的从每 5 秒一条降到每 5 分钟一条）未做线上统计。
2. **服务器上插件文件未被改动**：本次按约束只交付补丁，`/opt/ring/maibot/plugins/...`
   的 `transport.py` 仍是 `e550026f…`；§6 的 `patch` + `systemctl restart` 没有执行过。
3. **插件自带测试是以 pytest 桩驱动的**（该 venv 无 pytest）：13 个 parametrize 用例与
   1 个 `_log_connection_closed` 用例的断言全部命中，但 pytest 的 fixture 生命周期、
   `@pytest.mark.asyncio` 事件循环策略等细节未由 pytest 本身校验。
4. **WebUI 升级的 409 分支未实跑**：§8 的结论来自阅读
   `release_install.py:64-71 / 213-229`，没有真的在 WebUI 上点一次升级去触发它。
5. **上游未同步**：没有向 `Mai-with-u/MaiBot-SnowLuma-Adapter` 提 PR，
   本补丁在该上游不存在对应 commit。
6. **300 秒 / 2**6 这两个值是经验值**：没有做过「掉线多久算正常」的量化分析，
   若你的部署希望更快恢复，改 `MAX_RECONNECT_DELAY_SEC` 即可（常量在补丁第 2 个 hunk）。

## 11. 已知偏离

1. `transport.py` 是本目录里**唯一**的代码副本，它 = 服务器现状 + 本补丁；
   不包含任何其他「顺手优化」。
2. 节流窗口用 `time.monotonic` 而不是墙钟，进程重启后窗口状态丢失（重启后第一次失败
   必然完整 warning），这是有意的：节流只为压制同一进程内的刷屏。
3. `_reconnect_attempt` 不写日志也不暴露给外部，属于纯内部状态；
   需要观测时看 warning 里的 `（连续失败 N 次）` 或 debug 行。
4. 补丁刻意**没有**加「最大重试次数」：QQ 重新登录后需要能自动恢复，
   熔断会给运维增加一个「为什么它不重连了」的故障模式。
