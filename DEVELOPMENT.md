# Digital Genesis 开发文档

本仓库当前处于 **v3 架构已定稿、Phase 0–2 工程件开始落地** 的阶段。本文描述仓库结构、可运行组件、开发与验证流程，以及尚未完成的事项。

## 仓库结构

```text
digital-genesis/
├── ARCHITECTURE.md      # v3 架构设计（权威文档）
├── DEVELOPMENT.md       # 本文档：工程状态、开发流程、验收标准
├── README.md            # 项目入口与摘要
├── acp-bridge/          # ACP ↔ A2A 薄适配器（FastAPI）
├── config/
│   ├── litellm.yaml     # 模型网关配置模板
│   ├── soul.example.yaml# 共享 Soul 配置模板
│   └── validate.py      # 配置结构校验器
├── docs/              # 设计文档索引（见下方文档链接章节）
│   ├── PERSONA_PROVIDER_CONTRACT.md
│   ├── OPENVIKING_PERMISSION_MATRIX.md
│   ├── OPENVIKING_CONTEXT_STRATEGY.md
│   ├── ASTRBOT_ROUTER_DESIGN.md
│   ├── EVAL_DESIGN.md
│   ├── ACP_STREAMING_DESIGN.md
│   ├── PERSONA_PLAN_B_DESIGN.md
│   ├── SECURITY_TRUST_MODEL.md
│   ├── ACP_BRIDGE_WIRE_SCHEMA.md
│   ├── AIRI_EMBODIMENT_DESIGN.md
│   └── DEVELOPMENT_ROADMAP.md
├── persona_plan_b/     # Persona Plan B 纯函数原型（两段式流水线）
├── astrbot_router/      # AstrBot 一级路由纯函数原型（规则 + 模型降级）
├── airi_embodiment/     # AIRI 化身表现层纯函数原型（emotion 映射 + 降级）
├── evals/
│   ├── routing/cases.jsonl
│   ├── persona/
│   │   ├── cases.jsonl
│   │   └── judge_prompt.md
│   └── memory/cases.jsonl
├── schemas/
│   ├── persona-provider.schema.json
│   └── persona-provider-response.schema.json
├── scripts/
│   └── migrate_mempalace_to_openviking.py
└── tests/               # 仓库级测试（配置、迁移、契约、文档索引）
```

## 工程状态（2026-10-12）

| 组件 | 状态 | 说明 |
|---|---|---|
| v3 架构文档 | ✅ 已定稿 | 见 `ARCHITECTURE.md` |
| ACP↔A2A bridge | 🟡 参考实现 | 已实现 JSON-RPC handshake / `session/new` / `session/prompt` / `session/cancel`；流式映射见 `acp-bridge/.../streaming.py`，暂未接真实 dsh |
| LiteLLM 配置模板 | ✅ 已提供 | `config/litellm.yaml`，覆盖五个路由模型与 fallback |
| Soul 配置模板 | ✅ 已提供 | `config/soul.example.yaml` |
| 配置校验器 | ✅ 可用 | `python config/validate.py` |
| MemPalace → OpenViking 迁移脚本 | ✅ 可用 | 支持 JSON/JSONL，输出 Markdown + front matter |
| CI | ✅ 已配置 | GitHub Actions，矩阵运行根目录与 acp-bridge 测试 |
| Persona Provider 契约 | ✅ 已冻结 | 请求/响应 JSON Schema + 示例 + 不变量 |
| OpenViking 权限矩阵 | ✅ 已文档化 | 写隔离、双写者、Bridge 只读、删除审核 |
| OpenViking 上下文与生命周期策略 | ✅ 已文档化 | L0/L1/L2 预算、渐进召回流水线、置信度时间衰减、Agent Plugins 1.0 配置 |
| AstrBot 路由设计 | ✅ 已文档化 | 三路由决策树、意图分类器 I/O、五类故障降级 |
| 评估集设计 | ✅ 已文档化 | 人格/记忆/路由三类指标与阈值 |
| 路由评估初始集 | ✅ 50 条 | `evals/routing/cases.jsonl`，三类全覆盖，easy/medium/hard 混合 |
| Persona 评估初始集 | ✅ 50 条 | `evals/persona/cases.jsonl`，easy/medium/hard 全覆盖 |
| ACP 流式映射设计 | ✅ 已文档化 | 全部 `sessionUpdate` 类型映射、错误处理、Langfuse 关联 |
| Persona Plan B 设计 | ✅ 已文档化 | 两段式流水线、降级策略、与 MaiBot 对比 |
| 安全与信任模型 | ✅ 已文档化 | 信任分级、6 类威胁、密钥与数据分级、验收清单 |
| ACP Bridge Wire Schema | ✅ 已文档化 | v1 冻结草案、错误映射、7 条验收用例 |
| 开发路线图 | ✅ 已文档化 | Phase 0–6 状态、剩余工作、风险登记表 |
| AIRI 接入设计 | ✅ 已文档化 | A2A 契约、emotion 映射、OpenViking 读写、事件 payload、降级矩阵 |
| AIRI 表现层原型 | ✅ 纯函数骨架 | 8 种 emotion 映射、缺失资源降级至表情/idle、A2A 响应序列化、NATS 事件生成 |
| Memory 评估初始集 | ✅ 50 条 | `evals/memory/cases.jsonl`，覆盖全部 namespace 类型，L0 ≥ 12 条 |
| 评估 runner | ✅ 可用 | `scripts/run_evals.py`，routing/memory/persona 指标 + 阈值门禁 |
| Persona Plan B 原型与服务 | ✅ A2A 服务化 | `persona_plan_b/`，Stage 1/2 prompt、FastAPI A2A 端点、Schema 校验、契约不变量测试 |
| eval-all 聚合入口 | ✅ 可用 | `python scripts/run_evals.py all --baseline`，缺失预测自动跳过 |
| ACP 流式映射原型 | ✅ 纯函数骨架 | 9 种 `sessionUpdate` 映射、terminal 一次性语义、thought/usage 仅入 Langfuse、未知事件忽略 |
| AstrBot 路由引擎原型 | ✅ 纯函数骨架 | 显式触发词、confidence < 0.6 回落 chat、模型不可用规则降级；eval baseline 复用同一实现 |
| 本地部署 | ⏸ 暂缓 | 按当前目标，先完善开发文档与代码骨架 |

## ACP ↔ A2A Bridge

### 职责边界

bridge 只做协议翻译，不承载业务：

```text
AstrBot (A2A message/send)
  ↓
ACP Bridge
  ├─ initialize             # 协议握手
  ├─ session/new            # cwd=/workspace, mcpServers=[]
  └─ session/prompt         # 文本块
  ↓
dsh (ACP JSON-RPC)
```

### 设计约束

1. **流式映射已定义，传输层未接**：`streaming.py` 提供纯函数映射与 terminal 语义；HTTP/SSE 传输会在接入真实 dsh 后补充，避免凭空定义行为。
2. **每个 A2A task 一个 ACP session**：简单可靠；session 复用策略待真实压测后决定。
3. **错误语义**：ACP/RPC 错误映射为 A2A task `failed`，而不是 HTTP 500，便于上游重试与追踪。
4. **安全**：bridge 不挂载 Docker socket，不持有模型 Key；模型调用由 dsh 经 LiteLLM 完成。

### 本地测试（不启动服务）

```bash
cd acp-bridge
pip install -e ".[dev]"
pytest -q
```

## 配置校验

```bash
pip install -r requirements-dev.txt
python config/validate.py
```

当前强制项：

- `litellm.yaml` 必须声明 `persona-chat`、`persona-trigger`、`coding-primary`、`coding-fallback`、`intent-router`
- fallback 的 source/target 必须已声明
- `soul.example.yaml` 必须包含 `persona` / `perception` / `execution` / `memory` / `model_gateway`
- 路由必须覆盖 `chat` / `tech` / `embodiment`
- 所有 memory namespace 必须是 `viking://` URI（递归校验嵌套 namespace）

## 记忆迁移

```bash
python scripts/migrate_mempalace_to_openviking.py input.jsonl --output ./viking-memories/memories
```

输入支持 JSON array 或 JSONL。输出规则：

- 有 `user_id` → `users/{user}/`
- 无 `user_id` → `agents/shared/`
- 类型不在 `preference/fact/episode/relationship` 中时归一化为 `fact`
- 文件名由 `id` slug 化生成，重复执行幂等

## 离线评估

```bash
# routing 基线（无需模型）
python scripts/run_evals.py routing --baseline --enforce-thresholds

# memory / persona 使用预测文件
python scripts/run_evals.py memory --predictions predictions.jsonl --enforce-thresholds
python scripts/run_evals.py persona --predictions responses.jsonl --enforce-thresholds

# 聚合三类报告（routing 用 baseline；缺失预测的维度自动跳过）
python scripts/run_evals.py all --baseline
```

- 阈值集中在 `evals/thresholds.yaml`，与 `docs/EVAL_DESIGN.md` 对齐
- `--enforce-thresholds` 失败时非零退出，可作为合并门禁
- 输出支持 Markdown 与 JSON，`--output` 可指定报告文件

## CI

`.github/workflows/ci.yml` 在根目录与 `acp-bridge/` 两个矩阵单元分别执行：

- 根目录：安装 `requirements-dev.txt` → 配置校验 → `pytest`
- acp-bridge：安装 `.[dev]` → `pytest`

## 待办（按优先级）

1. ACP notification 传输层接入（`StreamMapper` 已就绪，待接真实 dsh）
2. AstrBot 路由意图分类器接入（`intent-router` 模型主路径，规则已就绪）
3. 跨 Agent 事件总线 Payload Schema 冻结（NATS / Redis Streams）
4. A2A `message/send` 最终规范发布后，冻结 bridge wire schema
5. 跨 Agent 事件总线 Payload Schema 冻结（NATS / Redis Streams）
6. A2A `message/send` 最终规范发布后，冻结 bridge wire schema
7. 部署文档暂缓，待代码骨架稳定后再写

## 贡献约定

- 架构变更先改 `ARCHITECTURE.md`，再落代码或配置
- 新增配置必须加入 `config/validate.py` 的结构校验
- bridge 保持“薄”：业务逻辑放 AstrBot / dsh / OpenViking，协议翻译放 bridge


## 设计文档索引

- `docs/PERSONA_PROVIDER_CONTRACT.md`：Persona Provider 请求/响应契约与不变量
- `docs/OPENVIKING_PERMISSION_MATRIX.md`：Agent × Namespace 权限矩阵
- `docs/OPENVIKING_CONTEXT_STRATEGY.md`：L0/L1/L2 渐进召回与生命周期衰减策略
- `docs/ASTRBOT_ROUTER_DESIGN.md`：三路由决策树与降级策略
- `docs/EVAL_DESIGN.md`：人格 / 记忆 / 路由评估指标与阈值
- `docs/ACP_STREAMING_DESIGN.md`：ACP sessionUpdate → A2A 流式事件映射
- `docs/PERSONA_PLAN_B_DESIGN.md`：两段式自研 Persona 流水线
- `docs/SECURITY_TRUST_MODEL.md`：信任分级、威胁模型与安全验收清单
- `docs/ACP_BRIDGE_WIRE_SCHEMA.md`：Bridge v1 wire 冻结草案与错误映射
- `docs/AIRI_EMBODIMENT_DESIGN.md`：AIRI 化身层接入设计
- `docs/DEVELOPMENT_ROADMAP.md`：Phase 0–6 当前状态、剩余工作与风险登记表
