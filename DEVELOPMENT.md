# RING 开发文档

本仓库当前处于 **v3 架构已定稿、Phase 0 文档与代码骨架** 阶段，尚未完成任何真实系统联调。本文描述仓库结构、可运行组件、开发与验证流程、当前 CI 状态与已知缺口。最后更新：2026-10-20。

## 仓库结构

```text
RING/
├── ARCHITECTURE.md      # v3 架构设计（权威文档）
├── DEVELOPMENT.md       # 本文档：工程状态、开发流程、验收标准
├── README.md            # 项目入口与摘要
├── pyproject.toml       # 根项目元数据（name/version/requires-python）
├── requirements-dev.txt # 根目录开发依赖（pytest/PyYAML/jsonschema）
├── .github/workflows/
│   └── ci.yml           # 矩阵 CI：根目录 + acp-bridge + eval gate
├── acp-bridge/          # ACP ↔ A2A 薄适配器（FastAPI）
│   └── README.md        # 运行方式与当前限制
├── config/
│   ├── litellm.yaml     # 模型网关配置模板
│   ├── soul.example.yaml# 共享 Soul 配置模板
│   └── validate.py      # 配置结构校验器
├── docs/                # 设计文档索引（见下方文档链接章节）
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
├── persona_plan_b/      # Persona Plan B 纯函数原型（两段式流水线）
├── astrbot_router/      # AstrBot 一级路由纯函数原型（规则 + 模型降级）
├── airi_embodiment/     # AIRI 化身表现层纯函数原型（emotion 映射 + 降级）
├── evals/
│   ├── thresholds.yaml  # 指标阈值（文档与代码共用）
│   ├── routing/cases.jsonl
│   ├── persona/
│   │   ├── cases.jsonl
│   │   ├── predictions.jsonl   # 构造 fixture，非真实模型输出
│   │   └── judge_prompt.md
│   └── memory/
│       ├── cases.jsonl
│       └── predictions.jsonl   # 构造 fixture
├── schemas/
│   ├── persona-provider.schema.json
│   ├── persona-provider-response.schema.json
│   └── event-bus-events.schema.json
├── scripts/
│   ├── run_evals.py     # 离线评估 runner（routing/memory/persona/all）
│   └── migrate_mempalace_to_openviking.py
└── tests/               # 仓库级测试（配置、迁移、契约、文档索引、评估 runner）
```

## 工程状态（2026-10-20）

| 组件 | 状态 | 说明 |
|---|---|---|
| v3 架构文档 | ✅ 已定稿 | 见 `ARCHITECTURE.md` |
| 根目录测试 | ✅ 本地通过 | 136 passed（Python 3.14.7；需 pytest/PyYAML/jsonschema/fastapi） |
| ACP↔A2A bridge | 🟡 参考实现（未联调） | 同步 JSON-RPC 流程 + 29 个单元测试；未接真实 dsh；同步路径拿不到执行正文（见“已知缺口”） |
| CI | 🔴 当前失败 | 最近 9 次 run 连续失败；根因见 `## CI`，本地等价命令全绿 |
| LiteLLM 配置模板 | ✅ 已提供 | `config/litellm.yaml`，覆盖五个路由模型与 fallback |
| Soul 配置模板 | ✅ 已提供 | `config/soul.example.yaml` |
| 配置校验器 | ✅ 可用 | `python config/validate.py` |
| MemPalace → OpenViking 迁移脚本 | ✅ 可用 | 支持 JSON/JSONL，输出 Markdown + front matter |
| Persona Provider 契约 | ✅ 已冻结 | 请求/响应 JSON Schema + 示例 + 不变量 |
| 跨 Agent 事件总线 Schema | ✅ 已冻结 | `schemas/event-bus-events.schema.json`，覆盖 7 类核心协同事件 |
| OpenViking 权限矩阵 | 🟡 设计完成、待映射 | 写隔离、双写者、Bridge 只读、删除审核；逻辑命名空间与物理布局映射待落地（§1.1） |
| OpenViking 上下文与生命周期策略 | ✅ 已文档化 | L0/L1/L2 预算、渐进召回流水线、置信度时间衰减、Agent Plugins 1.0 配置 |
| AstrBot 路由设计 | ✅ 已文档化 | 三路由决策树、意图分类器 I/O、五类故障降级 |
| 评估集设计 | ✅ 已文档化 | 人格/记忆/路由三类指标与阈值 |
| 路由评估初始集 | 🟡 50 条但不均衡 | tech 43 / chat 4 / embodiment 3；未满足“每类 ≥20” |
| Persona 评估初始集 | ✅ 50 条 | `evals/persona/cases.jsonl`，easy/medium/hard 混合 |
| ACP 流式映射设计 | ✅ 已文档化 | 全部 `sessionUpdate` 类型映射、错误处理、Langfuse 关联 |
| Persona Plan B 设计 | ✅ 已文档化 | 两段式流水线、降级策略、与 MaiBot 对比 |
| 安全与信任模型 | ✅ 已文档化 | 信任分级、6 类威胁、密钥与数据分级、验收清单 |
| ACP Bridge Wire Schema | 🟡 草案与实现有偏差 | v1 草案；`POST /` vs `/a2a`、`type` vs `kind`、响应结构详见该文档 §8 |
| 开发路线图 | ✅ 已文档化 | Phase 0–6 状态、剩余工作、风险登记表 |
| AIRI 接入设计 | ✅ 已文档化 | A2A 契约、emotion 映射、OpenViking 读写、事件 payload、降级矩阵 |
| AIRI 表现层原型 | ✅ 纯函数骨架 | 8 种 emotion 映射、缺失资源降级至表情/idle、A2A 响应序列化、NATS 事件生成 |
| Memory 评估初始集 | ✅ 50 条 | `evals/memory/cases.jsonl`，覆盖全部 namespace 类型，L0 18 条 |
| 评估 runner | ✅ 可用（fixture 口径） | `scripts/run_evals.py`，routing/memory/persona 指标 + 阈值门禁；当前 predictions 为构造 fixture |
| Persona Plan B 原型与服务 | ✅ A2A 服务化 | `persona_plan_b/`，Stage 1/2 prompt、FastAPI A2A 端点、Schema 校验、契约不变量测试 |
| eval-all 聚合入口 | ✅ 可用 | `python scripts/run_evals.py all --baseline`，缺失预测自动跳过 |
| ACP 流式映射原型 | ✅ 纯函数骨架 | 9 种 `sessionUpdate` 映射、terminal 一次性语义、thought/usage 仅入 Langfuse、未知事件忽略 |
| AstrBot 路由引擎原型 | ✅ 纯函数骨架 | 显式触发词、confidence < 0.6 回落 chat、模型不可用规则降级；关键词表偏宽，tech 易过触发 |
| 真实系统联调 | ⏸ 未开始 | AstrBot/MaiBot/AIRI/dsh/OpenViking 均未接入 |
| 本地部署 | ⏸ 暂缓 | 按当前目标，先完善开发文档与代码骨架 |
| 仓库自身 License | ⚠️ 缺失 | 上游 license 见 README；本仓库尚未选择 license |

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
5. **同步路径不返回正文**：`acp_client.py` 的 `run_task` 取 `request.params["text"]`（A2A 请求没有该字段），结果恒为空；`main.py` 回退为 `"ACP execution completed."`。真实正文需监听 `session/update`，见“已知缺口”。

### 本地测试（不启动服务）

```bash
cd acp-bridge
pip install -e ".[dev]"
pytest -q
```

2026-10-20 本地结果（Python 3.14.7）：

- 根目录 `pytest -q`：136 passed
- `acp-bridge` 目录 `pytest -q`：29 passed
- `python config/validate.py`：All configuration checks passed
- `python scripts/run_evals.py all --baseline --enforce-thresholds`：全阈值通过（fixture 口径，见 `evals/README.md`）

## 已知缺口（2026-10-20）

1. **Bridge 拿不到执行正文**：`acp_client.py:106` 的 `text` 取自 `request.params.get("text", "")`，A2A 请求中没有该字段，恒为空；`main.py:50` 回退为 `"ACP execution completed."`。真实正文应来自 `session/update` 的 `agent_message_chunk`，但同步路径未监听 notification。
2. **真实联调为零**：dsh 的 ACP 传输方式（HTTP/SSE/stdio）未经核实；AstrBot、MaiBot、AIRI、OpenViking 均未接入。
3. **评估是 fixture 自证**：routing 标签由 `rule_classify` 生成，memory/persona 的 predictions 为构造数据；“基线全绿”不代表真实模型质量。
4. **命名空间未对齐**：文档中的 `viking://memories/...`、`viking://skills/` 是逻辑路径，OpenViking 物理布局映射见 `docs/OPENVIKING_PERMISSION_MATRIX.md` §1.1。
5. **CI 当前为红**：见下节；两处根因均已定位。

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

`.github/workflows/ci.yml` 在 `push` 到 master 与 PR 时运行，矩阵 `directory = [".", "acp-bridge"]`：

- 根目录：安装 `requirements-dev.txt` → `python config/validate.py` → `pytest -q` → `Offline eval gate`
- acp-bridge：安装 `.[dev]` → `pytest -q`

### 当前失败原因（2026-10-20）

最近一次成功是 2026-10-12T09:25:03Z 的 `0832f34d`，之后连续 9 次 run 全部 failure：

1. **根目录 job 收集失败**：`tests/test_persona_service.py` 与 `tests/test_persona_plan_b.py` 导入 `fastapi`，但 `requirements-dev.txt` 未声明该依赖，报 `ModuleNotFoundError: No module named 'fastapi'`。
2. **eval gate 矩阵条件缺失**：`Offline eval gate` 步骤没有 `if: matrix.directory == '.'`，在 `acp-bridge/` 单元执行时找不到 `scripts/run_evals.py`，报 `python: can't open file '.../acp-bridge/scripts/run_evals.py': [Errno 2] No such file or directory`。

由于 job 使用 fail-fast，`test (.)` 被取消、`test (acp-bridge)` 失败，页面上表现为一 cancelled 一 failure。修复这两处即可恢复；本地等价命令已验证全绿。

## 待办（按优先级）

1. 修复 CI：`requirements-dev.txt` 增加 `fastapi`；`Offline eval gate` 加 `if: matrix.directory == '.'`
2. ACP notification 传输层接入（`StreamMapper` 已就绪，待接真实 dsh），让 bridge 返回真实正文
3. AstrBot 路由意图分类器接入（`intent-router` 模型主路径，规则已就绪）
4. 用真实模型输出重跑 routing / memory / persona 评估，替换构造 fixture；补齐 routing 每类样本
5. OpenViking 逻辑命名空间 → 物理布局 / ACL 映射
6. A2A `message/send` 最终规范发布后，冻结 bridge wire schema 并同步实现端点与字段
7. 跨 Agent 事件总线 Payload Schema 冻结（NATS / Redis Streams）
8. 部署文档暂缓，待代码骨架稳定后再写

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
- `docs/HYBRID_REDUNDANCY_DESIGN.md`：云端常驻、本地化身与边缘兜底的三级高可用设计与降级状态机
- `evals/README.md`：评估集口径、阈值、fixture 与真实模型输出的区别
- `acp-bridge/README.md`：bridge 运行方式与当前限制
- `evals/persona/judge_prompt.md`：人格 judge prompt（1–5 分五维评分）
