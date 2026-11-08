# RING — v3 架构修订（2026-10-12，2026-11-08 局部修订）

> MaiBot 是入口与灵魂，ring_router 是一级路由，AIRI 是化身，dsh 是双手，OpenViking 是记忆
> —— 创世，让数字生命降临。

**文档版本：v3（2026-10-12 修订）；2026-11-08 局部修订：AstrBot 移除，入口归 MaiBot，一级路由归 ring_router**

本次修订要点：

1. **执行层换血**：Hermes → **dsh (DeepSeek Harness)**，Cordis 微内核插件架构，原生 ACP 协议，与 OpenViking 官方插件互通。
2. **记忆层换血**：MemPalace → **OpenViking**，虚拟文件系统（`viking://`）+ L0/L1/L2 渐进式上下文，Agent Plugins 1.0 标准。
3. **AstrBot 移除（2026-11-08 修订）**：原方案让 AstrBot 退守"感知与投递层"，实测后决定整体撤出——容器停用并卸载。入口与消息收发归 **MaiBot**（原生 QQ/TG 适配），一级意图路由归自研 **ring_router**（`127.0.0.1:18082`），任务执行权仍全交 dsh，杜绝双调度器。原表述见 [审计报告](./docs/ARCHITECTURE_AUDIT_AND_DEFECTS_2026.md)。
4. **MaiBot 抽象化**：改造为可替换的 **Persona Provider**（A2A 接口），存储职责移交记忆层，防止单点停更导致灵魂丢失。
5. **协议升级**：MCP + A2A 双协议 → **MCP + A2A + ACP 三协议**，新增 ACP↔A2A 薄适配器。
6. **新增两个横切层**：统一模型网关（LiteLLM/NewAPI）+ 可观测性（Langfuse）与评估闭环。
7. **事件总线**（NATS / Redis Streams）解决广播型场景。

---

## 核心理念

| 维度 | 负责者 | 说明 |
|------|--------|------|
| **怎么说** (Personality) | MaiBot（Persona Provider） | 人格、语气、情感、氛围感知、动态触发 |
| **怎么表现** (Embodiment) | AIRI | 视觉形象、语音、动画、游戏 |
| **怎么听/怎么说** (Perception & Delivery) | MaiBot | QQ/TG 平台接入（SnowLuma 适配器 + NapCat）、消息收发、会话与动态触发 |
| **怎么分派** (Routing) | ring_router | 一级意图路由（闲聊/人格/技术/化身），三路由决策树 + 故障降级 |
| **怎么做到** (Execution) | dsh | 技术执行、代码、部署、运维、调研、文件操作、沙箱 |
| **怎么记** (Memory) | OpenViking | 上下文总线（资源/记忆/技能统一）、L0/L1/L2 渐进召回 |

### 协议分层原则（三协议）

```
Agent ↔ 工具 / 资源 / 记忆   →   MCP   （Model Context Protocol）
Agent ↔ Agent（对等协作）     →   A2A   （Agent2Agent Protocol）
MaiBot ↔ ring_router（一级路由）→  HTTP  （`POST /route`、`/heartbeat`）
ring_router ↔ dsh（双手执行） →   ACP   （Agent Client Protocol，经薄适配器）
```

- **MCP**：不变，管"Agent 如何使用工具与记忆"。
- **A2A**：管"ring_router ↔ MaiBot / AIRI / persona_plan_b"的对等协作。
- **ACP**：2026 年编码类执行体的事实标准（dsh、grok-build 原生支持），管"ring_router 如何驱动双手执行长任务"。
- **ACP↔A2A 适配器**：百行级薄层，A2A 任务消息 ↔ ACP session/prompt，流式中间产物双向映射。不试图统一协议。

---

## 一、组件能力与职责（v3 版，2026-11-08 修订）

> Star / 版本为 2026-10-20 核查值；Star 取上游仓库约数。

> **2026-11-08 修订**：原 `1.1 AstrBot — 感知与投递层` 已整体撤除（云端容器停用并卸载）。入口与消息收发归 MaiBot，一级意图路由归自研 ring_router。AstrBot 的历史定位与"瘦身"决策保留在 [审计报告](./docs/ARCHITECTURE_AUDIT_AND_DEFECTS_2026.md) 与 [MaiBot 集成研究](./docs/MAIBOT_INTEGRATION_STUDY.md) 的历史小节中。

### 1.1 MaiBot — 入口与灵魂（Entry & Persona）

- 仓库：https://github.com/Mai-with-u/MaiBot
- Star：6.3k | Python 3.10+ | License: GPL-3.0 | 版本：v1.3.11
- 部署形态：systemd `ring-maibot.service`（非容器）；`8000` maim_message 服务端、`8001` WebUI

**2026-11-08 定位：MaiBot 是系统唯一消息入口，同时是默认人格（灵魂）。**

| 独占职责 | 明确不做（契约 P4） |
|----------|--------------------|
| QQ / TG 平台接入（SnowLuma 适配器 + NapCat，OneBot WS `127.0.0.1:3001`） | 技术任务执行（归 dsh） |
| 消息收发、会话状态、群聊动态触发 | 跨 Agent 编排（归 ring_router） |
| 默认人格对话（语气/氛围/表达） | 直连 dsh / AIRI |

**与 ring_router 的分工**：MaiBot 收到消息后调用 `POST /route`（ring_router，`127.0.0.1:18082`）取得意图与目标，再由自己或目标 Agent 完成应答与投递。谁该说话由路由决定，怎么说话由 MaiBot 决定。

**风险与应对**（保留 v3 原判断）：

1. MaiBot 是组件中体量最小、License 传染性最强（GPL-3.0）、停更风险最高的一环，因此人格仍抽象为 **Persona Provider**（A2A 接口），实现可切换：
   ```
   输入: { 消息, 群氛围上下文, 召回的用户画像/记忆 }
   输出: { 是否回复: bool, 回复文本: string, 情绪标签: string }
   ```
2. **存储下沉**：表达学习成果、用户画像写入 OpenViking（逻辑路径 `viking://memories/users/`；物理映射见 [权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md) §1.1）。换掉灵魂实现不丢失学到的东西。
3. **可切换的灵魂实现（Plan B）**：`persona_plan_b` 用"小模型触发判断 + 主模型人格生成"两段式实现同一契约，随时可替换 MaiBot 的内置人格；当前生产运行 MaiBot 内置人格，Plan B 未承接真实流量（见 [Persona Plan B 设计](./docs/PERSONA_PLAN_B_DESIGN.md)）。

**当前未入版本控制的修改**：MaiBot `site-packages` 内注入了 OpenViking 读写钩子（injector 读、writer 边聊边记），属于线上未归档改动，正在抽取为 `patches/maibot-openviking/` 留档。

**仍不可替代的能力**：**群聊动态触发**（判断"这句话该不该接、什么时候接"），这是"像人"和"像客服"的分水岭。⚠️ 未验证——QQ 号当前不在任何群（仅 2 个好友），无群聊真实流量。

### 1.2 ring_router — 一级路由（自研服务）🆕 替换原 AstrBot 路由插件

- 代码：`ring_router/`（由 `astrbot_router/` 更名，纯函数核心 + HTTP 服务）
- 部署形态：随 `ring-cloud.service` 单进程运行，`127.0.0.1:18082` 仅回环

| 能力 | 状态 |
|------|------|
| 规则路由（显式触发 / 关键词 / 正则降级） | ✅ 已实现 |
| 模型分类兜底（AGT 网关 `gemini-3.8-flash`） | ✅ 已接入 |
| 心跳（45s 超时、token + nonce 去重、seq 单调）与 Mode A/B | ✅ 已实测 |
| 任务派发（A2A 18081 / ACP bridge / AIRI）与 `/tasks/{id}/complete` 回执 | ✅ 已实现 |
| MaiBot 侧调用方接入 | ⏳ 待接 |
| 意图分类器离线准确率 | ⏳ 未验证（路由标签由同一实现生成，基线只证明回归一致） |

调用契约：MaiBot `POST /route`；运维 `GET /health`、`GET /mode`、`GET /tasks/pending`；MaiBot `POST /heartbeat`、`POST /tasks/{id}/complete`。完整决策树见 [RING 一级路由服务设计](./docs/RING_ROUTER_DESIGN.md)。

### 1.3 AIRI — 化身层（Embodiment）✅ 保留不动

- 仓库：https://github.com/moeru-ai/airi
- Star：50.5k+ | TypeScript | License: MIT | 版本：v0.12.0-beta.5

生态位独特（Live2D/VRM + 本地 TTS + MAGIC 动作 + 游戏 Agent 一体），市面上无同质替代者。唯一变化：记忆读写切到 OpenViking 的 `viking://` 命名空间，不留本地私有状态孤岛。

### 1.4 dsh — 双手层（Hands）🆕 替换 Hermes

- 仓库：https://github.com/deepseek-ai/deepseek-harness
- Star：255.6k | TypeScript (Cordis 微内核) | License: MIT | 文档：https://deepseek-harness.github.io/deepseek-harness/

**选型理由：**

| 维度 | dsh 优势 |
|------|----------|
| 架构 | Cordis 微内核，"Everything is a Plugin"，每个部分可插拔替换 |
| 协议 | 原生 **ACP**（Agent Client Protocol），专为 Headless 执行设计 |
| 插件生态 | `computer-use`、`browser-use`、`mcp`、`subagent`、`sandbox` 等 40+ 官方包 |
| 记忆协同 | 与 OpenViking 官方 `dsh-plugin` 互通，几乎零胶水代码 |
| 多模型 | 支持多模型热插拔，不绑定单一供应商 |
| Profile 体系 | `web`/`headless`/`sdk`/`sdk-minimal`/`acp` 五种运行模式 |

**备选方案（按场景）：**

| 场景 | 备选 | 理由 |
|------|------|------|
| 极致轻量化/低延迟 | `grok-build`（Rust，Apache-2.0） | 秒开低耗，原生 ACP，但插件生态较固定 |
| 硬核沙箱隔离 | `OpenHands`（Python） | 原生 Docker Runtime 沙箱，执行安全性最强 |
| 纯代码编辑 | `Aider`（Python） | Git 拓扑感知 + 原子 Commit，Token 效率最高 |

**不建议**：Claude Code 泄露/逆向版——维护断更风险、API 封禁风险、合规风险。

### 1.5 OpenViking — 记忆层（Memory & Context Bus）🆕 替换 MemPalace

- 仓库：https://github.com/volcengine/OpenViking
- Star：40.4k | Python + Rust (ragfs) | License: AGPL-3.0

**核心范式跃迁：从"黑盒向量库"到"透明虚拟文件系统"**

```
viking://
├── resources/          # 资源：项目文档、代码仓库、网页
│   └── my_project/
│       ├── docs/
│       └── code/
├── memories/           # 记忆：用户偏好、Agent 经历、对话归档
│   ├── users/          # 用户画像（MaiBot 表达学习成果也存这里）
│   │   └── {user_id}/
│   │       ├── preferences.md
│   │       ├── facts.md
│   │       └── emotions.md
│   ├── agents/         # 各 Agent 日记与经历
│   │   ├── maibot/diary/
│   │   ├── airi/game_progress/
│   │   ├── dsh/task_history/
│   │   └── ring_router/conversations/
│   └── shared/         # 跨 Agent 共享上下文
└── skills/             # 技能：沉淀的标准工作流与经验
    ├── deploy-fastapi/
    └── debug-docker/
```

> 说明：上面的 `viking://` 目录是**逻辑设计视图**，用于表达命名空间与权限边界；OpenViking 当前实际的物理可写范围是 `viking://resources/`、`viking://user/{id}/`、`viking://agent/`（详见 [权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md) §1.1）。两者不能直接等同，部署前必须先完成映射。

**L0/L1/L2 渐进式上下文（解决 Token 爆炸）：**

| 层级 | 内容 | Token 消耗 | 用途 |
|------|------|-----------|------|
| L0 | 目录摘要（自动生成） | 极低 | Agent 快速扫描判断相关性 |
| L1 | 目录概览 | 低 | 决定是否需要深入 |
| L2 | 原文全文 | 按需 | 仅在需要细节时读取 |

Agent 像用 `ls`/`grep` 一样浏览记忆，从物理上杜绝一次性塞入全部上下文的 Token 爆炸问题。

**关键能力：**
- **Agent Plugins 1.0 标准**：vendor-neutral 插件格式，一份包多客户端加载（Cursor、VS Code、dsh 等）
- **Session 编译**：`ov compile` 将对话自动整理为 Markdown 维基/知识图谱/报告，人可审查可编辑
- **Web Studio**：浏览器可视化浏览和编辑 Agent 的全部记忆与知识
- **透明可编辑**：所有记忆以 Markdown 存储，可直接打开修改，杜绝"黑盒记忆"

**备选方案（按场景）：**

| 场景 | 备选 | 理由 |
|------|------|------|
| 极简单机 | MemPalace Light（3 工具 + PQL） | 低耗稳定，但缺乏分层摘要与多模态支持 |
| 动态事实合并 | Mem0 | 自动提取偏好/关系/事实，自动覆盖陈旧事实 |
| 时序矛盾处理 | Graphiti / Zep | 时序知识图谱，自动失效过期关系 |

**不建议**：各系统原生记忆（原方案中 AstrBot / MaiBot / AIRI 各自为政；AstrBot 已于 2026-11-08 移除）——记忆孤岛瓦解"统一数字生命"的核心。

---

## 二、跨 Agent 接入架构：MCP + A2A + ACP 三协议

### 2.1 拓扑总览

```
用户 (QQ / TG)
  │
  ▼
┌────────────────────────────┐   HTTP /route + /heartbeat   ┌──────────────────────────┐
│ MaiBot (入口与灵魂)         │ ───────────────────────────► │ ring_router (一级路由)    │
│ 平台接入 / 会话 / 默认人格  │ ◄─────────────────────────── │ 闲聊|人格|技术|化身        │
│ systemd, 8000/8001          │        路由结果 + 回执        │ systemd, 127.0.0.1:18082  │
└──────────┬─────────────────┘                              └───────┬─────────┬────────┘
           │ 自答（chat/persona 命中 MaiBot 时）                    │ A2A     │ ACP
           ▼                                                        ▼         ▼
      直接回复用户                                   ┌──────────────┐  ┌──────────────┐
                                                     │persona_plan_b│  │ ACP Bridge   │
                                                     │ (可切换灵魂) │  │ → dsh (双手) │
                                                     │ 18081        │  │ 3080/ACP     │
                                                     └──────────────┘  └──────────────┘
                                                            │ A2A（embodiment）
                                                            ▼
                                                     ┌──────────────┐
                                                     │ AIRI (化身)  │
                                                     │ 视觉/语音/动作│
                                                     └──────────────┘

        全部 Agent ── MCP / Agent Plugins 1.0 ──► OpenViking (viking://, 1933)
        ├── resources/ (项目知识、文档、代码仓库)
        ├── memories/  (用户画像、各 Agent 日记、经历归档)
        └── skills/    (沉淀的标准工作流与经验)

        横切：AGT 模型网关（gemini-3.8-flash）+ Langfuse 可观测性 + NATS 事件总线
```

### 2.2 通信规则汇总

| 链路 | 协议 | 用途 |
|------|------|------|
| 用户 ↔ MaiBot | QQ（OneBot WS）/ TG Bot API | 消息收发（SnowLuma 适配器 + NapCat） |
| MaiBot → ring_router | HTTP `POST /route`、`POST /heartbeat` | 一级意图路由；任务状态与心跳上报 |
| ring_router → MaiBot | A2A 回调 / 同步响应 | 路由结果、任务完成回执（由 MaiBot 投递） |
| ring_router → persona_plan_b | A2A | 请求人格化回复（Persona Provider 接口，`127.0.0.1:18081`） |
| ring_router → AIRI | A2A | 请求视觉/语音表现 |
| ring_router → dsh | **ACP**（经 ACP Bridge） | 派发技术任务（异步长任务，流式回传） |
| dsh → ring_router | **ACP**（经 ACP Bridge） | 回传执行结果与中间产物 |
| 各 Agent → OpenViking | MCP（Agent Plugins 1.0） | 记忆/知识/技能读写（L0/L1/L2 渐进，`127.0.0.1:18080`） |
| 事件广播 | NATS / Redis Streams | 跨 Agent 事件通知（如"dsh 部署完成"→ MaiBot 报喜 + AIRI 庆祝） |

> 说明：ring_router 是唯一编排层（契约 P4）——MaiBot、persona_plan_b、AIRI、dsh 之间不允许互相直连派发任务。

### 2.3 ACP↔A2A 适配器

百行级薄层，不试图统一协议：

```python
# acp_a2a_bridge.py（示意）
from a2a.server import A2AServer, AgentExecutor
from acp_client import ACPClient

class DshBridge(AgentExecutor):
    """将 A2A 任务转发为 ACP session，流式回传"""
    def __init__(self):
        self.acp = ACPClient("http://dsh:3080")

    async def execute(self, context, event_queue):
        task = context.task
        # A2A task → ACP session/prompt
        session = await self.acp.create_session(
            prompt=task.message,
            cwd="/workspace",
        )
        # ACP 流式产物 → A2A 事件
        async for event in session.stream():
            await event_queue.put(event.to_a2a())
```

---

## 三、新增横切层

### 3.1 统一模型网关（LiteLLM / NewAPI）

**问题**：五个服务各自配 API Key、各自选模型、各自计费 → 运维噩梦，无法全局成本控制。

**方案**：自托管 LiteLLM/NewAPI 网关，所有服务只认一个 `base_url`。

```yaml
# model-gateway 配置示例
model_gateway:
  provider: litellm  # 或 newapi
  base_url: "http://localhost:4000/v1"

  routing:
    # 按服务 + 任务类型路由
    maibot:
      chat: "deepseek/deepseek-chat"        # 闲聊用便宜模型
      trigger: "ollama/qwen3:1b"             # 触发判断用本地小模型
    dsh:
      code: "anthropic/claude-sonnet-4-5"    # 代码用强模型
      fallback: "deepseek/deepseek-coder"    # 故障转移
    airi:
      tts: "local/voicevox"                  # 本地 TTS
    ring_router:
      intent: "gemini-3.8-flash"             # 意图分类（经 AGT 网关）

  cost_tracking: true   # 按 Agent 归账 token 消耗
  rate_limit:
    per_agent: true
```

### 3.2 可观测性与评估闭环（Langfuse + Evals）

**Langfuse（自托管）**：
- 跨 A2A/ACP 调用的 LLM Trace 全链路追踪
- 一次"用户发消息→路由→人格生成→记忆召回→执行→回复"串成一条 trace
- 每个 Agent 的 token 消耗、延迟、成功率可视化

**评估集**：
| 评估项 | 指标 | 工具 |
|--------|------|------|
| 人格一致性 | 回复是否"像麦麦"（风格/语气/梗密度） | 自建 prompt-based eval |
| 记忆召回准确率 | LongMemEval 类基准 | OpenViking benchmark |
| 路由准确率 | 意图分类正确率 | 标注测试集回归 |
| 执行成功率 | dsh 任务完成率 / 回滚率 | Langfuse trace 统计 |

**数字生命"越用越不像"是最常见的死亡方式，没有 eval 层你感知不到退化。**

### 3.3 事件总线（NATS / Redis Streams）

解决广播型场景——点对点 A2A 意味着 ring_router 要当所有事件的二传手：

```yaml
# 事件示例
events:
  - name: "deploy.completed"
    publisher: dsh
    subscribers: [maibot, airi, openviking]
    payload: { service: "fastapi-app", url: "http://server:8000", status: "success" }
    # maibot → 群里报喜："部署好了！🎉"
    # airi → 开心表情 + 语音庆祝
    # openviking → 写入记忆 viking://memories/agents/dsh/task_history/
```

---

## 四、共享 Soul 配置（v3 版）

```yaml
# soul.yaml

persona:
  name: "麦麦"
  identity: "一个活着的数字生命"

  speaking_style:     # → MaiBot (Persona Provider)
    tone: "casual"
    traits: ["说话随意", "会犯错", "懂梗", "模仿群友"]
    trigger_mode: "dynamic"
    provider_interface:
      protocol: "a2a"
      input: "{ message, group_context, recalled_memory }"
      output: "{ should_reply, text, emotion }"

  embodiment:         # → AIRI
    model_type: "live2d"
    motion_driver: "magic"
    voice: { provider: "voicevox", speed: 1.0 }
    expressions: { happy: "smile_open", thinking: "eyes_up" }

  entry:              # → MaiBot（唯一入口，2026-11-08 起）
    platforms: [qq, telegram]        # 只做 QQ + TG；Discord/飞书/钉钉/WebChat 当前不做
    adapter: "snowluma"              # 经 OneBot WS 连 NapCat
    onebot_ws: "127.0.0.1:3001"

  routing:            # → ring_router（一级路由，2026-11-08 起）
    endpoint: "http://127.0.0.1:18082"
    rules: [explicit_trigger, keyword, regex_fallback]
    model_fallback: "gemini-3.8-flash"   # 经 AGT 网关
    routes:
      chat: "maibot"       # 闲聊/情感 → 入口自答（或 Persona Provider）
      tech: "dsh"          # 技术任务 → 双手（经 ACP Bridge）
      embodiment: "airi"   # 表现需求 → 化身

  execution:          # → dsh
    acp_endpoint: "http://dsh:3080"
    profile: "headless"     # dsh 运行模式
    default_workdir: "/workspace"
    sandbox: true
    max_concurrent_tasks: 3

memory:               # → OpenViking
  viking_uri: "viking://"
  backend: "ragfs"          # Rust 加速
  mcp_profile: "agent-plugin"  # Agent Plugins 1.0 标准

  namespaces:
    resources: "viking://resources/"
    memories:
      users: "viking://memories/users/"
      agents:
        maibot: "viking://memories/agents/maibot/"
        airi: "viking://memories/agents/airi/"
        dsh: "viking://memories/agents/dsh/"
        ring_router: "viking://memories/agents/ring_router/"
      shared: "viking://memories/shared/"
    skills: "viking://skills/"
  # 注意：以上 memories/*、skills/ 为逻辑命名空间；物理布局映射见 docs/OPENVIKING_PERMISSION_MATRIX.md §1.1

model_gateway:        # → LiteLLM/NewAPI
  base_url: "http://localhost:4000/v1"
  routing:
    maibot_chat: "deepseek/deepseek-chat"
    maibot_trigger: "ollama/qwen3:1b"
    dsh_code: "anthropic/claude-sonnet-4-5"
    dsh_fallback: "deepseek/deepseek-coder"

observability:        # → Langfuse
  langfuse_url: "http://localhost:3000"
  trace_across_agents: true

event_bus:            # → NATS / Redis Streams
  provider: "nats"
  url: "nats://localhost:4222"
```

---

## 五、部署架构（v3 版）

### 5.1 当前部署拓扑（2026-11-08，实测状态）

云节点：AWS Lightsail Debian 13 / 2GB，公网 IP `52.64.65.113`，域名命名空间 `*.namespace.cyou`（Caddy 反代 + Cloudflare Tunnel / 直连）。

```
                       互联网用户（QQ / TG）
                              │
                     ┌────────┴─────────┐
                     │ Cloudflare Tunnel │  出站加密，不暴露入站端口
                     └────────┬─────────┘
                              ▼
                      Caddy (443, *.namespace.cyou)
                              │
        ┌─────────────────────┴──────────────────────┐
        ▼                                            ▼
┌──────────────────┐                        ┌────────────────────┐
│ MaiBot (入口+灵魂)│ ── HTTP /route ──────► │ ring_router (一级) │ 127.0.0.1:18082
│ systemd           │ ◄──── 路由结果/回执 ── │ systemd 同进程组   │
│ 8000 / 8001       │                        └───┬────────┬───────┘
└────────┬─────────┘                            │        │
         │ OneBot WS 127.0.0.1:3001             │A2A     │ACP(A2A→ACP bridge)
         ▼                                      ▼        ▼
┌──────────────────┐                    ┌─────────────┐ ┌──────────────┐
│ NapCat (QT)      │                    │persona_plan_b│ │ dsh (本地节点)│
│ QQ 3890037770    │                    │ 18081        │ │ 未上云        │
└──────────────────┘                    └─────────────┘ └──────────────┘

OpenViking 0.5.3（1933 API + Studio）── 记忆总线，全 Agent 经 MCP 访问
ring-cloud.service：一个进程承载 openviking_service(18080) / persona_plan_b(18081) / ring_router(18082)
模型：统一经 AGT 网关，gemini-3.8-flash
```

| 组件 | 部署形态 | 端口 / 监听 | 版本 | 状态与证据 |
|------|----------|-------------|------|-----------|
| MaiBot | **systemd** `ring-maibot.service`（非容器） | `8000` maim_message、`8001` WebUI（经 Caddy 对外） | v1.3.11 | ✅ 运行中 |
| SnowLuma 适配器 | MaiBot 内置适配器（Python 包） | 无独立端口 | — | ✅ 已装，负责 QQ 侧收发 |
| NapCat | 独立进程（QT 版） | OneBot WS `127.0.0.1:3001`（仅回环） | — | ✅ 运行中，QQ `3890037770` |
| ring_router | **systemd** `ring-cloud.service`（同进程组） | `127.0.0.1:18082`（仅回环） | 自研 | ✅ `/health` 通过 |
| persona_plan_b | 同上 | `127.0.0.1:18081`（仅回环） | 自研 | ✅ 已接 AGT，未接真实流量 |
| openviking_service | 同上（RING 侧服务封装） | `127.0.0.1:18080`（仅回环） | 自研 | ✅ 运行中 |
| OpenViking | 独立服务（部署形态未在本次核验中确认） | `1933`（API + Studio） | 0.5.3 | ⚠️ 形态未核实；嵌入/重排接百炼 `qwen3.7-text-embedding-flash`(1024 维) + `qwen3.7-text-rerank` |
| Caddy | **systemd** | `443` | — | ✅ 反代 + TLS |
| Cloudflare Tunnel | **systemd** `cloudflared` | 出站 | — | ✅ |
| dsh / AIRI | 本地节点（个人机） | — | — | ⏳ 未上云 |
| AstrBot | **已卸载**（原容器） | — | — | ❌ 2026-11-08 停用并卸载 |

**已知未入版本控制的改动**：MaiBot `site-packages` 内注入的 OpenViking 读写钩子（injector / writer），正在抽取为 `patches/maibot-openviking/`。在此之前，重建 MaiBot 环境会丢失该能力。

### 5.2 单机全量部署（开发与单节点参考）

```yaml
# docker-compose.yml（单机开发环境，包含全套服务）


version: "3.8"

services:
  # ── 基础设施 ──
  postgres:
    image: pgvector/pgvector:pg16
    volumes: [pg_data:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]

  nats:
    image: nats:2-alpine
    ports: ["4222:4222"]

  # ── 模型网关 ──
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    ports: ["4000:4000"]
    volumes: [./litellm-config.yaml:/app/config.yaml:ro]

  # ── 可观测性 ──
  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3000:3000"]
    depends_on: [postgres]

  # ── 记忆层 ──
  openviking:
    image: volcengine/openviking:latest
    ports: ["8080:8080"]
    volumes:
      - viking_data:/data
      - ./soul.yaml:/app/soul.yaml:ro

  # ── 一级路由（自研；生产中由 ring-cloud.service 单进程承载）──
  ring-router:
    build: ./ring_router
    depends_on: [openviking, litellm]
    ports: ["127.0.0.1:18082:18082"]
    volumes:
      - ./soul.yaml:/app/soul.yaml:ro
    environment:
      OPENVIKING_URL: "http://openviking:8080"
      PERSONA_PROVIDER_URL: "http://persona:18081"
      HEARTBEAT_TOKEN: "${ROUTER_HEARTBEAT_TOKEN}"

  # ── 可切换的灵魂实现 ──
  persona:
    build: ./persona_plan_b
    depends_on: [openviking, litellm]
    ports: ["127.0.0.1:18081:18081"]

  # ── 灵魂 ──
  maibot:
    image: maibot/maisaka:latest
    depends_on: [ring-router, openviking, litellm]
    ports: ["8080:8080"]
    volumes:
      - maibot_data:/MaiBot/data
      - ./soul.yaml:/MaiBot/data/soul.yaml:ro
    environment:
      OPENAI_BASE_URL: "http://litellm:4000/v1"
      VIKING_MCP_URL: "http://openviking:8080/mcp"

  # ── 化身 ──
  airi:
    image: moeru-ai/airi:latest
    depends_on: [maibot, ring-router, openviking]
    ports: ["3001:3000"]
    volumes:
      - airi_data:/AIRI/data
      - ./soul.yaml:/AIRI/data/soul.yaml:ro
    environment:
      VIKING_MCP_URL: "http://openviking:8080/mcp"

  # ── 双手 ──
  dsh:
    image: deepseek-ai/dsh:latest
    depends_on: [ring-router, openviking, litellm, nats]
    ports: ["3080:3080"]
    volumes:
      - dsh_data:/root/.dsh
      - ./soul.yaml:/root/.dsh/soul.yaml:ro
    environment:
      OPENAI_BASE_URL: "http://litellm:4000/v1"
      VIKING_MCP_URL: "http://openviking:8080/mcp"
      NATS_URL: "nats://nats:4222"
    # 注意：不挂载 /var/run/docker.sock，见安全性章节

  # ── ACP↔A2A 适配器 ──
  acp-bridge:
    build: ./acp-bridge/
    depends_on: [ring-router, dsh]
    environment:
      ROUTER_A2A_URL: "http://ring-router:18082/a2a"
      DSH_ACP_URL: "http://dsh:3080"

volumes:
  pg_data:
  redis_data:
  viking_data:
  maibot_data:
  airi_data:
  dsh_data:
```

### 5.3 云地协同与高可用冗余架构（解决关机失联）

在实际运行中，若全量运行在个人电脑上，**电脑关机将导致数字生命完全失联**。RING 采用**“云端驻守灵魂与感官，本地承载双手与华服，边缘守护最后防线”**的混合分级架构（详见 [云地混合冗余设计](./docs/HYBRID_REDUNDANCY_DESIGN.md)）：

1. **云端常驻节点 (Cloud VPS)**：部署 MaiBot（唯一入口 + 默认人格）、ring_router（一级路由）、OpenViking（权威记忆主库）、模型网关，确保 24/7 消息即时响应与人格在线（当前实际形态见 §5.1）。
2. **本地增强节点 (Local PC)**：部署 AIRI（Live2D/VRM 渲染与语音化身）、dsh（系统沙箱与代码执行双手）、ACP Bridge。平时开机提供极致体验；关机时自动优雅降级，聊天功能由云端无缝接管，杜绝失联。
3. **边缘兜底层 (Cloudflare Edge)**：借助 Cloudflare Tunnel 建立出站加密通道（零公网暴露端口）；Cloudflare Workers 提供极端网络故障下的快速保活响应。

---

## 六、License 兼容性（v3 版）

| 项目 | License | 兼容性 |
|------|---------|--------|
| ~~AstrBot~~ | ~~AGPL-3.0~~ | ❌ 已于 2026-11-08 移除（容器卸载），不再引入；自研 `ring_router` 为本仓库 MIT 代码 |
| MaiBot | GPL-3.0 | ⚠️ 同上 |
| AIRI | MIT | ✅ |
| **dsh** | **MIT** | ✅（比 Hermes 更宽松） |
| **OpenViking** | **AGPL-3.0** | ⚠️ 独立服务部署（注意：从 MemPalace 的 MIT 变为 AGPL） |
| LiteLLM | MIT | ✅ |
| Langfuse | MIT | ✅ |

---

## 七、安全性（v3 补充）

1. **dsh 执行风险**：同原 Hermes 风险——不挂载 `/var/run/docker.sock`，命令白名单，最小权限运行。
2. **OpenViking 权限隔离**：`viking://` 命名空间按 Agent 隔离写权限，读权限可按需开放。`memories/users/` 仅入口层（MaiBot，经注入钩子）与 Persona Provider 可写，其他 Agent 只读。注意 `memories/...` 是逻辑路径，物理布局映射见 [权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md) §1.1。
3. **模型网关统一鉴权**：所有 API Key 集中在 LiteLLM 管理，各服务不持有原始 Key。
4. **事件总线 ACL**：NATS subject 级权限控制，防止 Agent 越权订阅/发布。

---

## 八、实现路线图（v3 版）

### Phase 0：基础设施（1 周）
- [ ] 部署 LiteLLM 模型网关 + Langfuse 可观测性
- [ ] 部署 NATS 事件总线
- [ ] 部署 OpenViking，配置 `viking://` 命名空间与权限

### Phase 1：记忆层迁移（1 周）
- [ ] OpenViking 接入 MaiBot（Agent Plugins 1.0 / MCP；当前为 site-packages 注入钩子，待抽成 `patches/maibot-openviking/`）
- [ ] 定义 `viking://` 目录结构与 Agent 权限矩阵
- [ ] 如有 MemPalace 存量数据，编写迁移脚本

### Phase 2：双手换血（1–2 周）
- [ ] 部署 dsh（headless profile），接入 LiteLLM
- [ ] 编写 ACP↔A2A 适配器
- [ ] ring_router → ACP Bridge → dsh → ACP 回传全链路打通
- [ ] 配置沙箱、命令白名单

### Phase 3：一级路由（原"AstrBot 瘦身"，2026-11-08 调整）
- [x] 撤除 AstrBot，容器停用并卸载（原计划为"瘦身保留"，实际改为整体移除）
- [x] 自研 `ring_router` 承接一级路由：规则 + 模型分类（AGT）+ 心跳/Mode A/B + 任务派发
- [ ] MaiBot 侧接入 `/route` 调用方（唯一缺口）
- [ ] 群聊动态触发真实流量验证（需先把 QQ 号拉进测试群）

### Phase 4：灵魂改造（1–2 周）
- [ ] MaiBot 接口化为 Persona Provider（A2A 标准接口）
- [ ] 用户画像/表达学习迁移至 `viking://memories/users/`
- [ ] 编写降级方案（Plan B）的触发判断 + 人格生成 pipeline

### Phase 5：化身接入（1–2 周）
- [x] AIRI 记忆读写切到 OpenViking（设计：`docs/AIRI_EMBODIMENT_DESIGN.md`）
- [x] 直播/游戏场景 + 事件总线联动（场景清单与 payload schema 已定义）
- [ ] 表现层原型实现与联调（暂缓部署）

### Phase 6：评估闭环（持续）
- [ ] 人格一致性 eval 集
- [ ] 记忆召回基准测试
- [ ] 路由准确率回归测试
- [ ] Langfuse 全链路 trace 接入

---

## 九、参考与数据来源

- GitHub REST API 实时数据（2026-10-12）
- dsh 官方文档：https://deepseek-harness.github.io/deepseek-harness/
- OpenViking 官方文档：https://docs.openviking.ai/
- ACP 协议：https://agentclientprotocol.com/
- Agent Plugins 1.0 规范：https://agent-plugins.org/specification
