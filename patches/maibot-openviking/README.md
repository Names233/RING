# MaiBot × OpenViking 记忆钩子（补丁材料 + 幂等安装器）

本目录记录的是**部署在远端服务器上的既有实现**的抽取结果，不是新功能开发。

背景：远端 MaiBot 实例长期记忆链路需要读写 OpenViking（下称 OV）。当时是在服务器上
**直接修改 site-packages** 完成的（新增两个模块 + 三处挂载），既不进 git 也不可复现。
本目录把那次现场改动完整固化成：精确副本 + 真实 unified diff + 脱敏配置样例 + 幂等
安装/回滚脚本 + 本说明，使得同样的改动可以在任何同版本 MaiBot 上重放或撤销。

> 目标实例路径约定（下方命令均按此）：
> - 实例根目录 `MAI_ROOT=/opt/ring/maibot`
> - 虚拟环境 `/opt/ring/toolenv/maibot`（Python 3.13.5）
> - `SITE_PACKAGES=/opt/ring/toolenv/maibot/lib/python3.13/site-packages`
> - 配置 `$MAI_ROOT/data/openviking.json`（600）
> - 写入游标 `$MAI_ROOT/data/openviking_write_state.json`（运行期自动生成）

## 1. 适用版本

| 组件 | 版本 / 事实 |
| --- | --- |
| MaiBot | **1.3.19** |
| maibot-dashboard | 1.9.13 |
| maibot-plugin-sdk | 2.21.0 |
| Python | 3.13.5（venv：`/opt/ring/toolenv/maibot`） |
| site-packages | `/opt/ring/toolenv/maibot/lib/python3.13/site-packages` |

三处挂载点的行号锚点是**按 MaiBot 1.3.19 的上游源码**标注的。其他版本若上游文件变动，
`install.py` 会因为锚点未唯一命中而拒绝写入（见 §6.4），不会产生半吊子改动。

## 2. 目录结构

```
patches/maibot-openviking/
├── README.md                  # 本文件
├── install.py                 # 幂等安装/回滚器（默认 dry-run）
├── config-sample.json         # openviking.json 脱敏样例（api_key = "REPLACE_ME"）
├── openviking_injector.py     # 读侧：把 OV 记忆注入 planner（服务器 1:1 副本）
├── openviking_writer.py       # 写侧：轮询把聊天增量写入 OV（服务器 1:1 副本）
└── mounts/
    ├── 0001-reasoning-engine-openviking-injector.patch
    ├── 0002-maisaka-runtime-start-writer.patch
    └── 0003-runtime-main-writer-bootstrap.patch
```

三个 `.patch` 都是**真实 upstream → 现状**的 unified diff：服务器 `$MAI_ROOT/backup/` 下
保留了打补丁前的原始文件（`openviking-202611071112/`、`openviking-writer-202611071415/`），
因此行号、上下文、缩进均为实测结果，不是估推。可直接 `patch -p1` 试用，也可只当作说明读。

## 3. 三处挂载点

### 3.1 `src/maisaka/reasoning_engine.py`（3 个 hunk）

锚点函数：`MaisakaReasoningEngine._build_planner_injected_user_messages`（MaiBot 1.3.19 中
定义于第 280 行；被修改的三段分别在 import 区（第 82 行附近）、第 320 行、第 333 行）。

1. **import 区**（`@@ -82,6 +82,7 @@`）：在 `heuristic_memory_injector` 与
   `image_memory_injector` 之间加入
   `from src.maisaka.memory.openviking_injector import openviking_memory_injector`。
2. **注入器定义与 pending 集合**（`@@ -320,9 +321,18 @@`）：在 `build_image_memory_message`
   之后新增内嵌协程 `build_openviking_memory_message()`（异常只 `logger.debug` 后返回空串，
   不打断其他注入器）；`pending` 集合由三项变为四项（加 `"OpenViking记忆"`）；阶段提示语
   改为 `"正在准备：启发式记忆、OpenViking记忆、人物画像、图片记忆"`。
3. **并发汇聚**（`@@ -333,16 +343,19 @@`）：`asyncio.gather` 的第 4 路
   `measure_injection("OpenViking记忆", build_openviking_memory_message)`；返回值解包加
   `openviking_memory_message`；`remaining` 提示串加该项；末尾
   `if openviking_memory_message: injected_messages.append(...)`（插在启发式记忆之后、
   人物画像之前）。

### 3.2 `src/maisaka/runtime.py`（1 个 hunk）

锚点函数：`MaisakaHeartFlowChatting.start()`（1.3.19 第 275 行）。在
`self._ensure_background_tasks_running()`（第 286 行之后）插入 try/except：函数内
`from src.maisaka.memory.openviking_writer import openviking_memory_writer` 后
`await openviking_memory_writer.ensure_started()`，异常记
`logger.debug(f"{self.log_prefix} OpenViking 写入任务启动失败: {exc}")`。
含义：每个聊天实例启动时顺带拉起写侧协程（`ensure_started` 幂等，重复调用无副作用）。

### 3.3 `src/runtime.py`（1 个 hunk）

锚点函数：`raw_main()`（1.3.19 第 490 行）。在
`_run_until_complete(loop, initialize_task)`（第 531 行之后）插入：`loop.create_task(...)`
+ `_run_until_complete(loop, _start_writer)`，异常 `logger.warning`。
含义：进程级启动路径上也拉一次写侧任务，保证即使没有聊天实例也会开始轮询。

> 两处启动点同时存在是**有意冗余**：`ensure_started()` 幂等（`self._task is not None and
> not self._task.done()` 直接返回），谁先到谁生效，可覆盖「只跑 dashboard 不跑聊天」的部署形态。

## 4. 新增模块（读侧 / 写侧）

两个文件均为服务器现有内容的**字节级副本**（base64 管道传输），除本 README 的脱敏说明外
未做任何改动。

### 4.1 `openviking_injector.py`（读侧，538 行）

- 配置数据类 `OpenVikingConfig`（第 27-55 行，`@dataclass(frozen=True)`），字段即配置项。
- 配置文件定位：`get_instance_root() / "data" / OPENVIKING_CONFIG_FILENAME`（第 226 行）。
- 请求：`POST` 到 `OPENVIKING_SEARCH_PATH = "/api/v1/search/search"`，注入文本带
  标记 `OPENVIKING_MEMORY_REFERENCE_MARKER = "【OpenViking记忆-内部参考】"`，明确告知模型
  这是内部参考而非用户发言。
- 密钥解析 `_resolve_api_key`：优先 `config.api_key`，否则按 mtime 缓存读取
  `config.api_key_file`（本环境指向 `/opt/ring/data/openviking/user_api_key.txt`）。
- 模块级单例 `openviking_memory_injector = OpenVikingInjector()`（第 538 行）。
- 缓存：`cache_ttl_seconds` / `min_interval_seconds` / `min_new_messages` /
  `failure_cooldown_seconds`（失败后冷却，避免拖慢每轮对话）。

### 4.2 `openviking_writer.py`（写侧，527 行）

- `OPENVIKING_SESSIONS_PATH = "/api/v1/sessions"`、`OPENVIKING_SESSION_ID_PREFIX = "mb-"`。
- 后台协程 `ensure_started()`（第 79 行，幂等，任务名 `openviking-memory-writer`），
  内层 `_run_loop` 每 `max(5.0, config.flush_interval_seconds)` 秒跑一轮（默认 60s）。
- 增量游标：`$MAI_ROOT/data/openviking_write_state.json`（文件名常量
  `OPENVIKING_WRITE_STATE_FILENAME`，可用 `config.state_file` 覆盖），结构
  `{version, updated_at, sessions: {<session md5>: {cursor, last_commit_at, last_task_id,
  last_write_at, uncommitted}}}`，写入走临时文件 + `replace`，避免半写。
- commit 判定在 `_maybe_commit`：`due_by_count = uncommitted >= commit_message_threshold`
  （默认 20）、`due_by_idle = idle_commit_seconds > 0 and (now - last_write_at) >= idle_commit_seconds`
  （默认 900s）。模块内 `OPENVIKING_COMMIT_POLICY`（第 37-43 行）刻意把上游自动策略抬到
  `message_count_threshold=1000` / `idle_timeout_seconds=86400`，即**关闭上游自动 commit**，
  完全由本模块自己决定提交节奏。
- 单次 commit 超时 `OPENVIKING_COMMIT_TIMEOUT_SECONDS = 20.0`（第 36 行），取
  `max(config.timeout_seconds, 20.0)`。

两模块的依赖仅：`aiohttp`、`src.common.logger.get_logger`、`src.common.paths.get_instance_root`。
已对两者做过 `api_key|token|secret|bearer` 检索，只命中变量名与 `Bearer` f-string，无硬编码密钥。

## 5. 配置（`$MAI_ROOT/data/openviking.json`，权限 600）

`config-sample.json` 与实际配置**同序同值**，仅 `api_key` 写成 `"REPLACE_ME"`：

| 字段 | 值 | 说明 |
| --- | --- | --- |
| enabled | true | 读侧总开关 |
| base_url | http://127.0.0.1:1933 | OV 本地端口 |
| api_key | "REPLACE_ME" | 留空则走 api_key_file |
| api_key_file | /opt/ring/data/openviking/user_api_key.txt | 密钥文件（不入库） |
| timeout_seconds | 6 | 单请求超时 |
| limit / max_tokens | 6 / 700 | 召回条数与注入预算 |
| peer_scope | "all" | 检索范围 |
| window_size / min_messages | 8 / 4 | 上下文窗口与最小消息数 |
| query_max_chars / max_chars | 600 / 1200 | 查询与注入文本长度上限 |
| cache_ttl_seconds / min_interval_seconds | 120 / 30 | 结果缓存与最小请求间隔 |
| min_new_messages / failure_cooldown_seconds | 4 / 120 | 增量触发与失败冷却 |
| write_enabled | true | 写侧总开关 |
| flush_interval_seconds | 60 | 写侧轮询间隔 |
| lookback_seconds | 7200 | 首次回填回看窗口 |
| max_batch_per_session | 40 | 单轮单会话最多写多少条 |
| commit_message_threshold / idle_commit_seconds | 20 / 900 | 显式 commit 触发条件 |
| state_file | "" | 空则用默认游标路径 |
| max_content_chars | 2000 | 单条消息入库截断 |

密钥三种来源，优先级：`config.api_key` → `config.api_key_file` 文件内容 →
`install.py` 运行时环境变量（见 §6.2，只用于**写配置**，不参与运行期解析）。

## 6. 安装手册

### 6.1 先看计划（默认 dry-run，不写任何文件）

```bash
cd patches/maibot-openviking
python install.py --site-packages /opt/ring/toolenv/maibot/lib/python3.13/site-packages \
                  --mai-root /opt/ring/maibot
```

不带 `--apply` 时只打印：三段挂载的「目标文件 / 锚点 / 将修改或已是目标状态 / diff 预览」、
两个新增模块的目标路径、配置文件的动作。目录不存在会明确报错而不是猜。

### 6.2 真安装

```bash
export OPENVIKING_API_KEY='...'          # 或者
export OPENVIKING_API_KEY_FILE=/opt/ring/data/openviking/user_api_key.txt

python install.py --apply \
  --site-packages /opt/ring/toolenv/maibot/lib/python3.13/site-packages \
  --mai-root /opt/ring/maibot
# 之后重启 MaiBot 进程
```

- 写文件前会按相对路径把将被修改的文件备份到
  `$MAI_ROOT/backup/openviking-hook-<UTC 时间戳>/`（保持 `src/...` 层级，两处
  `runtime.py` 不会互相覆盖）。
- `openviking.json` 已存在时**默认不动**（打印 skip-existing）；要先重置样例才加
  `--force-config`。写入后 `chmod 0600`。
- 想完全跳过配置：`--no-config`。
- 密钥只从环境变量读，日志里打码成 `****(len=N)`，不落盘。

### 6.3 幂等性

重复执行 `--apply` 是安全的：每处挂载都做「目标片段已存在且源片段不存在 → already，
什么都不写」的判定，全部命中时脚本输出「已是目标状态 / 内容一致」并正常退出。
因此也可作为「巡检」手段：非零退出说明有人手动改过或版本漂移。

### 6.4 冲突处理

锚点要求**唯一命中**：`Edit.old` 在文件中出现次数必须恰好为 1，`Edit.new` 出现 0 次。
不满足就报 conflict、列出实际计数、**整批拒绝写入**（不会写一半）。常见原因：
MaiBot 升级导致上游行变化、或有人已手工打过部分补丁。此时应重新生成 diff 后更新
`install.py` 里的片段，而不是放宽匹配。

## 7. 回滚手册

```bash
python install.py --uninstall \
  --site-packages /opt/ring/toolenv/maibot/lib/python3.13/site-packages \
  --mai-root /opt/ring/maibot
# 确认输出全部为「将还原 / 将删除」后再加 --apply
```

`--uninstall --apply` 做三件事：把三处挂载逐块反向替换回上游片段、删除
`src/maisaka/memory/openviking_injector.py` 与 `openviking_writer.py`（`memory/` 目录残留的
`__pycache__` 不主动清）、保留 `data/openviking.json` 与游标文件（`--no-config` 同理不涉及）。
回滚仍走同一套锚点校验，冲突同样拒绝写入。

手工兜底：直接用 `$MAI_ROOT/backup/openviking-hook-<时间戳>/` 下的原件覆盖回去，
或按 `mounts/*.patch` 反向打补丁（`patch -R -p1`）。

## 8. 校验（sha256）

服务器原始文件与本地副本逐字节一致（`sha256sum` 双向核对）：

| 文件（相对 site-packages） | 字节数 | sha256 |
| --- | --- | --- |
| src/maisaka/memory/openviking_injector.py | 20170 | 8b9faa0f5c4312ce9c6be71fcc4dc2f8d9be6560329e2573db77efb09ce899f3 |
| src/maisaka/memory/openviking_writer.py | 19229 | bc06c90bb925ed2c6a034e8710d3ec7b773fe56627b4f5e5bab83e366c15b76e |
| src/maisaka/reasoning_engine.py（已挂载） | 104222 | d49c4360b5c6ce14913a07f82274a38d36073eb4f26be0da1955fc31eb806659 |
| src/maisaka/runtime.py（已挂载） | 95541 | f3b9462b1193522f4e33369fc6c37380f04a3f01e148c6929bbc0f31aa9c6dd6 |
| src/runtime.py（已挂载） | 24296 | 26bbb1df199b2b8942bcbfe40134f2b06b87e7e55a4616701ec6d8e4aede5935 |

打补丁前的上游原件（存于服务器 `$MAI_ROOT/backup/`，用于生成 diff）：

| 原件 | 字节数 | sha256 |
| --- | --- | --- |
| openviking-202611071112/reasoning_engine.py | 103455 | 79a24f9d666b6ab4aa4a9b6c5fbe84b4e5eb1fa99b821df99f7dd5b91d8a940f |
| openviking-writer-202611071415/runtime.py（maisaka） | 95212 | 000e4b62eabc98dc39a59f7ada0d7b5a2b1e103dd7d174ef228fe6e42f76fe4b |
| openviking-writer-202611071415/runtime_main.py（src） | 23818 | b1882655a0fdf352709288bbbd74157a2bf49c7eef2c0bf57cabd82e4174eef3 |

核对命令：

```bash
sha256sum patches/maibot-openviking/openviking_injector.py patches/maibot-openviking/openviking_writer.py
```

## 9. 已知偏离（必须知道的事实）

1. **当初是直接改 site-packages，未走任何流程**：新增两个模块、改三处挂载点，均在
   `/opt/ring/toolenv/maibot/lib/python3.13/site-packages` 里就地完成，没有 git 记录、
   没有 review、没有对应上游 PR。本目录是事后补的可复现材料，不代表上游支持这种插入方式。
2. **回填脚本曾丢游标**：早期一次手工回填把 `openviking_write_state.json` 覆盖/清空，
   导致写侧从 `lookback_seconds` 窗口重新回写，产生重复消息。现有写入逻辑用
   临时文件 + `replace` 原子落盘，且本仓库的回滚**不删除**游标文件；如需重置必须人工
   删并接受重放后果。
3. **上游 commit 策略被主动抬到接近关闭**（`OPENVIKING_COMMIT_POLICY`），由本模块的
   20 条 / 900s 条件接管。这属于有意偏离，升级时不要顺手「修正」成上游默认值。
4. **配置文件路径耦合实例根目录**：`get_instance_root()` 决定 `data/openviking.json` 的
   位置；`api_key_file` 指向容器外的 `/opt/ring/data/openviking/user_api_key.txt`，
   该文件不属于 MaiBot 目录树，迁移实例时容易漏。
5. **`install.py` 在 Windows 上跑 dry-run 时**，若不给 `--mai-root`，默认值是
   `/opt/ring/maibot`，在 PowerShell 里会显示成 `\opt\ring\maibot`，属正常现象；
   `--apply` 请始终显式传参。
6. **本目录的 `openviking_injector.py` / `openviking_writer.py` 是服务器现状副本**，
   与「更好的写法」无关：保留了 `_ACTION` 风格的中文日志、既有私有字段命名。

## 10. 风险与注意事项

- **升级 MaiBot 会覆盖 site-packages**：`pip install -U maibot` 或重装会重新解包
  `src/`，两个新增模块可能被清掉、三处挂载一定被还原。升级后请重新执行
  `install.py --dry-run` 检查锚点，再 `--apply`；行号可能漂移，导致报 conflict（安全失败）。
- **不做持久化隔离**：这是对第三方包的原地修改，任何「重装/校验完整性」操作都可能回退。
  长期方案应是把钩子做成 plugin 或用官方扩展点，本目录只是把现状可复现化。
- OV 侧不可用时的行为：读侧失败 `logger.debug` 后返回空串（对话继续），写侧异常在
  `_run_loop` 内吞掉等下轮；不会阻塞主流程，但也没有告警升级，需要看日志
  `maisaka_openviking_writer` 才能发现长期写失败。
- 游标文件与会话 id 绑定（`mb-<md5>`），换设备/换库会导致历史会话无法续写（从头回填）。

## 11. 本地验证记录

- `python -m py_compile install.py openviking_injector.py openviking_writer.py` 通过
  （本地 CPython 3.14.7；服务器运行 3.13.5，代码未使用 3.14 特性）。
- `python install.py --dry-run --no-diff` 在无 site-packages 的机器上可运行，正常打印三段
  挂载说明与配置段，退出码 0。
- 端到端回放（在 `E:\RING\_tmp_ov_verify` 的沙箱副本上进行，未触碰服务器）：把三份上游原件
  摆成目录树 → `--apply --no-config` → 三个文件 sha256 与服务器**现状**逐一相等
  （d49c4360… / f3b9462b… / 26bbb1df…）→ 再 `--apply` 全部落在 already →
  `--uninstall --apply` → 三个文件 sha256 与上游原件逐一相等，新增模块被删除。
- 未在真实服务器上执行过 `--apply`（本次任务约束为只读）。

## 12. 未验证 / 待观察

- 真实服务器上 `install.py --apply` 的全流程（本次只读，仅用离线副本回放）。
- 与 OV 服务端的实际联通（`http://127.0.0.1:1933`）与召回质量；本次只做静态核对。
- MaiBot 升级后的锚点漂移程度（1.3.19 之外版本未取样本）。
- 并发压力下的写侧表现（多会话同时轮询、commit 超时重试的边界）。
