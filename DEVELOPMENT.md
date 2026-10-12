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
│   ├── ASTRBOT_ROUTER_DESIGN.md
│   ├── EVAL_DESIGN.md
│   ├── ACP_STREAMING_DESIGN.md
│   ├── PERSONA_PLAN_B_DESIGN.md
│   ├── SECURITY_TRUST_MODEL.md
│   ├── ACP_BRIDGE_WIRE_SCHEMA.md
│   └── DEVELOPMENT_ROADMAP.md
├── persona_plan_b/     # Persona Plan B 纯函数原型（两段式流水线）
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
| AstrBot 路由设计 | ✅ 已文档化 | 三路由决策树、意图分类器 I/O、五类故障降级 |
| 评估集设计 | ✅ 已文档化 | 人格/记忆/路由三类指标与阈值 |
| 路由评估初始集 | ✅ 12 条 | `evals/routing/cases.jsonl`，三类全覆盖 |
| Persona 评估初始集 | ✅ 20 条 | `evals/persona/cases.jsonl`，easy/medium/hard 全覆盖 |
| ACP 流式映射设计 | ✅ 已文档化 | 全部 `sessionUpdate` 类型映射、错误处理、Langfuse 关联 |
| Persona Plan B 设计 | ✅ 已文档化 | 两段式流水线、降级策略、与 MaiBot 对比 |
| 安全与信任模型 | ✅ 已文档化 | 信任分级、6 类威胁、密钥与数据分级、验收清单 |
| ACP Bridge Wire Schema | ✅ 已文档化 | v1 冻结草案、错误映射、7 条验收用例 |
| 开发路线图 | ✅ 已文档化 | Phase 0–6 状态、剩余工作、风险登记表 |
| Memory 评估初始集 | ✅ 20 条 | `evals/memory/cases.jsonl`，覆盖全部 namespace 类型 |
| 评估 runner | ✅ 可用 | `scripts/run_evals.py`，routing/memory/persona 指标 + 阈值门禁 |
| Persona Plan B 原型 | ✅ 纯函数骨架 | `persona_plan_b/`，Stage 1/2 prompt、解析、降级、契约校验、长度约束 |
| eval-all 聚合入口 | ✅ 可用 | `python scripts/run_evals.py all --baseline`，缺失预测自动跳过 |
| ACP 流式映射原型 | ✅ 纯函数骨架 | 9 种 `sessionUpdate` 映射、terminal 一次性语义、thought/usage 仅入 Langfuse、未知事件忽略 |
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
2. AstrBot 纯函数路由引擎原型（关键词 + 正则降级路径）
3. Persona Plan B 接入 Persona Provider 契约层并跑 persona eval 全集
4. 评估集扩容至各 50 条（routing/persona/memory）
5. AIRI 接入设计文档（记忆读写、事件 payload、emotion 映射）
6. A2A `message/send` 最终规范发布后，冻结 bridge wire schema
7. 部署文档暂缓，待代码骨架稳定后再写

## 贡献约定

- 架构变更先改 `ARCHITECTURE.md`，再落代码或配置
- 新增配置必须加入 `config/validate.py` 的结构校验
- bridge 保持“薄”：业务逻辑放 AstrBot / dsh / OpenViking，协议翻译放 bridge


## 设计文档索引

- `docs/PERSONA_PROVIDER_CONTRACT.md`：Persona Provider 请求/响应契约与不变量
- `docs/OPENVIKING_PERMISSION_MATRIX.md`：Agent × Namespace 权限矩阵
- `docs/ASTRBOT_ROUTER_DESIGN.md`：三路由决策树与降级策略
- `docs/EVAL_DESIGN.md`：人格 / 记忆 / 路由评估指标与阈值
- `docs/ACP_STREAMING_DESIGN.md`：ACP sessionUpdate → A2A 流式事件映射
- `docs/PERSONA_PLAN_B_DESIGN.md`：两段式自研 Persona 流水线
- `docs/SECURITY_TRUST_MODEL.md`：信任分级、威胁模型与安全验收清单
- `docs/ACP_BRIDGE_WIRE_SCHEMA.md`：Bridge v1 wire 冻结草案与错误映射
- `docs/DEVELOPMENT_ROADMAP.md`：Phase 0–6 当前状态、剩余工作与风险登记表
