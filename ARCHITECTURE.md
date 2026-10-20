# Digital Genesis — v3 架构修订（2026-10-12）

> MaiBot 是灵魂，AIRI 是化身，AstrBot 是耳目，dsh 是双手，OpenViking 是记忆
> —— 创世，让数字生命降临。

**文档版本：v3（2026-10-12 修订）**

本次修订要点：

1. **执行层换血**：Hermes → **dsh (DeepSeek Harness)**，Cordis 微内核插件架构，原生 ACP 协议，与 OpenViking 官方插件互通。
2. **记忆层换血**：MemPalace → **OpenViking**，虚拟文件系统（`viking://`）+ L0/L1/L2 渐进式上下文，Agent Plugins 1.0 标准。
3. **AstrBot 瘦身**：从"全栈大脑"退守为**感知与投递层**（平台接入 + 意图路由 + 消息收发），任务执行权全交 dsh，杜绝双调度器。
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
| **怎么听/怎么说** (Perception & Delivery) | AstrBot | 18+ 平台接入、意图分类与一级路由、消息收发 |
| **怎么做到** (Execution) | dsh | 技术执行、代码、部署、运维、调研、文件操作、沙箱 |
| **怎么记** (Memory) | OpenViking | 上下文总线（资源/记忆/技能统一）、L0/L1/L2 渐进召回 |

### 协议分层原则（三协议）

```
Agent ↔ 工具 / 资源 / 记忆   →   MCP   （Model Context Protocol）
Agent ↔ Agent（对等协作）     →   A2A   （Agent2Agent Protocol）
AstrBot ↔ dsh（双手执行）     →   ACP   （Agent Client Protocol，经薄适配器）
```

- **MCP**：不变，管"Agent 如何使用工具与记忆"。
- **A2A**：不变，管"AstrBot ↔ MaiBot / AIRI"的对等协作。
- **ACP**：2026 年编码类执行体的事实标准（dsh、grok-build 原生支持），管"AstrBot 如何驱动双手执行长任务"。
- **ACP↔A2A 适配器**：百行级薄层，A2A 任务消息 ↔ ACP session/prompt，流式中间产物双向映射。不试图统一协议。

---

## 一、五个项目各自的能力（v3 版）

> Star / 版本为 2026-10-20 核查值；Star 取上游仓库约数。

### 1.1 AstrBot — 感知与投递层（Perception & Delivery）

- 仓库：https://github.com/AstrBotDevs/AstrBot
- Star：42.4k+ | Python 3.10+ | License: AGPL-3.0

**v3 关键变化：从"全栈大脑"瘦身为"感知与投递层"**

| 保留职责（独占） | 移交职责（给 dsh） |
|------------------|-------------------|
| IM 平台接入（QQ/微信/TG/Discord/飞书/钉钉等 18+） | 任务拆解、多步执行、子任务调度 |
| 消息收发与会话管理 | 沙箱执行（Computer Use） |
| 意图分类与一级路由（闲聊→MaiBot / 技术→dsh / 表现→AIRI） | 计划任务的执行（AstrBot 只管触发） |
| 消息增强类插件（签到、词库、群管理） | 任务执行类插件 |

**原则：AstrBot 管"听到了什么、把话送到哪"，dsh 管"事情怎么办"。** 两边不重叠，杜绝双调度器打架。

### 1.2 MaiBot — 灵魂层（Persona Provider，可替换）

- 仓库：https://github.com/Mai-with-u/MaiBot
- Star：6.3k | Python 3.10+ | License: GPL-3.0 | 版本：v1.3.11

**v3 关键变化：抽象为可替换的 Persona Provider**

风险：MaiBot 是五件套中体量最小（6.1k★）、License 传染性最强（GPL-3.0）的组件，且其核心能力（人格保持、表达学习）正被大模型原生能力与记忆层稀释。

**应对策略：**

1. **接口化**：定义标准 A2A 接口，任何实现都可接入：
   ```
   输入: { 消息, 群氛围上下文, 召回的用户画像/记忆 }
   输出: { 是否回复: bool, 回复文本: string, 情绪标签: string }
   ```
2. **存储下沉**：表达学习成果、用户画像全部写入 OpenViking（逻辑路径 `viking://memories/users/`；物理布局映射见 [权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md) §1.1），MaiBot 只保留"判断与生成"逻辑。换掉 MaiBot 不丢失学到的东西。
3. **降级方案（Plan B）**：若 MaiBot 停更，用"小模型触发判断 + 主模型人格生成"两段式自研替代，触发判断可用 1B 级本地模型。

MaiBot 当前仍不可替代的能力：**群聊动态触发**（判断"这句话该不该接、什么时候接"），这是"像人"和"像客服"的分水岭。

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
│   │   └── astrbot/conversations/
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

**不建议**：各系统原生记忆（AstrBot/MaiBot/AIRI 各自为政）——记忆孤岛瓦解"统一数字生命"的核心。

---

## 二、跨 Agent 接入架构：MCP + A2A + ACP 三协议

### 2.1 拓扑总览

```
                    ┌────────────────────────────────────────────────────────┐
                    │      OpenViking (viking:// 上下文与记忆总线)             │
                    │  ├── resources/ (项目知识、文档、代码仓库)             │
                    │  ├── memories/  (用户画像、多Agent共享日记、经历归档) │
                    │  └── skills/    (沉淀的标准工作流与经验)               │
                    └─────────────────────────┬──────────────────────────────┘
                                              │  Agent Plugins 1.0 / MCP (L0/L1/L2)
       ┌──────────────────────┬───────────────┴───────────────┬──────────────────────┐
       ▼                      ▼                               ▼                      ▼
┌───────────────┐      ┌───────────────┐               ┌───────────────┐      ┌───────────────┐
│ AstrBot (耳目) │      │  MaiBot (灵魂) │               │   AIRI (化身) │      │   dsh (双手)  │
│ 平台接入/路由  │      │ 语气/氛围/画像│               │ 动作/视觉/TTS │      │ 执行/编码/运维│
└───────┬───────┘      └───────┬───────┘               └───────┬───────┘      └───────┬───────┘
        │                      │                               │                      │
        │                      │                               │                      │
        └──────────────────────┴───────────────┬───────────────┴──────────────────────┘
                                               │ A2A / ACP 协议总线
                                               ▼
                                      用户感知（统一数字生命）
```

### 2.2 通信规则汇总

| 链路 | 协议 | 用途 |
|------|------|------|
| 用户 ↔ AstrBot | 各 IM 平台 SDK | 消息收发 |
| AstrBot → MaiBot | A2A | 请求人格化回复（Persona Provider 接口） |
| AstrBot → AIRI | A2A | 请求视觉/语音表现 |
| AstrBot → dsh | **ACP**（经适配器） | 派发技术任务（异步长任务，流式回传） |
| dsh → AstrBot | **ACP**（经适配器） | 回传执行结果与中间产物 |
| 各 Agent → OpenViking | MCP（Agent Plugins 1.0） | 记忆/知识/技能读写（L0/L1/L2 渐进） |
| 事件广播 | NATS / Redis Streams | 跨 Agent 事件通知（如"dsh 部署完成"→ MaiBot 报喜 + AIRI 庆祝） |

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
    astrbot:
      intent: "deepseek/deepseek-chat"       # 意图分类

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

解决广播型场景——点对点 A2A 意味着 AstrBot 要当所有事件的二传手：

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

  perception:         # → AstrBot（瘦身后）
    platforms: [qq, telegram, discord]
    plugins: { message_enhancement_only: true }  # 只做消息增强
    routing:
      chat: "maibot"       # 闲聊/情感 → Persona Provider
      tech: "dsh"          # 技术任务 → 双手
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
        astrbot: "viking://memories/agents/astrbot/"
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

```yaml
# docker-compose.yml

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

  # ── 感知与投递 ──
  astrbot:
    image: soulter/astrbot:latest
    depends_on: [redis, openviking, litellm]
    ports: ["6185:6185", "6196:6196"]
    volumes:
      - astrbot_data:/AstrBot/data
      - ./soul.yaml:/AstrBot/data/soul.yaml:ro
    environment:
      OPENAI_BASE_URL: "http://litellm:4000/v1"
      VIKING_MCP_URL: "http://openviking:8080/mcp"

  # ── 灵魂 ──
  maibot:
    image: maibot/maisaka:latest
    depends_on: [astrbot, openviking, litellm]
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
    depends_on: [maibot, astrbot, openviking]
    ports: ["3001:3000"]
    volumes:
      - airi_data:/AIRI/data
      - ./soul.yaml:/AIRI/data/soul.yaml:ro
    environment:
      VIKING_MCP_URL: "http://openviking:8080/mcp"

  # ── 双手 ──
  dsh:
    image: deepseek-ai/dsh:latest
    depends_on: [astrbot, openviking, litellm, nats]
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
    depends_on: [astrbot, dsh]
    environment:
      ASTRBOT_A2A_URL: "http://astrbot:6196/a2a"
      DSH_ACP_URL: "http://dsh:3080"

volumes:
  pg_data:
  redis_data:
  viking_data:
  astrbot_data:
  maibot_data:
  airi_data:
  dsh_data:
```

---

## 六、License 兼容性（v3 版）

| 项目 | License | 兼容性 |
|------|---------|--------|
| AstrBot | AGPL-3.0 | ⚠️ 独立服务部署，网络协议交互 |
| MaiBot | GPL-3.0 | ⚠️ 同上 |
| AIRI | MIT | ✅ |
| **dsh** | **MIT** | ✅（比 Hermes 更宽松） |
| **OpenViking** | **AGPL-3.0** | ⚠️ 独立服务部署（注意：从 MemPalace 的 MIT 变为 AGPL） |
| LiteLLM | MIT | ✅ |
| Langfuse | MIT | ✅ |

---

## 七、安全性（v3 补充）

1. **dsh 执行风险**：同原 Hermes 风险——不挂载 `/var/run/docker.sock`，命令白名单，最小权限运行。
2. **OpenViking 权限隔离**：`viking://` 命名空间按 Agent 隔离写权限，读权限可按需开放。`memories/users/` 仅 MaiBot/AstrBot 可写，其他 Agent 只读。注意 `memories/...` 是逻辑路径，物理布局映射见 [权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md) §1.1。
3. **模型网关统一鉴权**：所有 API Key 集中在 LiteLLM 管理，各服务不持有原始 Key。
4. **事件总线 ACL**：NATS subject 级权限控制，防止 Agent 越权订阅/发布。

---

## 八、实现路线图（v3 版）

### Phase 0：基础设施（1 周）
- [ ] 部署 LiteLLM 模型网关 + Langfuse 可观测性
- [ ] 部署 NATS 事件总线
- [ ] 部署 OpenViking，配置 `viking://` 命名空间与权限

### Phase 1：记忆层迁移（1 周）
- [ ] OpenViking 接入 AstrBot（Agent Plugins 1.0 / MCP）
- [ ] 定义 `viking://` 目录结构与 Agent 权限矩阵
- [ ] 如有 MemPalace 存量数据，编写迁移脚本

### Phase 2：双手换血（1–2 周）
- [ ] 部署 dsh（headless profile），接入 LiteLLM
- [ ] 编写 ACP↔A2A 适配器
- [ ] AstrBot → ACP → dsh → ACP 回传全链路打通
- [ ] 配置沙箱、命令白名单

### Phase 3：AstrBot 瘦身（1 周）
- [ ] AstrBot 路由逻辑改造：技术任务 → ACP 派发 dsh
- [ ] 移除 AstrBot 侧的执行类插件/Sub-Agent 调度
- [ ] 保留平台接入 + 消息增强插件

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
