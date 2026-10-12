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
├── docs/
│   ├── PERSONA_PROVIDER_CONTRACT.md
│   └── OPENVIKING_PERMISSION_MATRIX.md
├── schemas/
│   ├── persona-provider.schema.json
│   └── persona-provider-response.schema.json
├── scripts/
│   └── migrate_mempalace_to_openviking.py
└── tests/               # 仓库级测试（配置、迁移、契约）
```

## 工程状态（2026-10-12）

| 组件 | 状态 | 说明 |
|---|---|---|
| v3 架构文档 | ✅ 已定稿 | 见 `ARCHITECTURE.md` |
| ACP↔A2A bridge | 🟡 参考实现 | 已实现 JSON-RPC handshake / `session/new` / `session/prompt`，暂未接真实 dsh |
| LiteLLM 配置模板 | ✅ 已提供 | `config/litellm.yaml`，覆盖五个路由模型与 fallback |
| Soul 配置模板 | ✅ 已提供 | `config/soul.example.yaml` |
| 配置校验器 | ✅ 可用 | `python config/validate.py` |
| MemPalace → OpenViking 迁移脚本 | ✅ 可用 | 支持 JSON/JSONL，输出 Markdown + front matter |
| CI | ✅ 已配置 | GitHub Actions，矩阵运行根目录与 acp-bridge 测试 |
| Persona Provider 契约 | ✅ 已冻结 | 请求/响应 JSON Schema + 示例 + 不变量 |
| OpenViking 权限矩阵 | ✅ 已文档化 | 写隔离、双写者、Bridge 只读、删除审核 |
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

1. **不模拟流式**：当前实现为同步 request/response。`session/update` 流式事件映射会在接入真实 dsh 后补充，避免凭空定义行为。
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

## CI

`.github/workflows/ci.yml` 在根目录与 `acp-bridge/` 两个矩阵单元分别执行：

- 根目录：安装 `requirements-dev.txt` → 配置校验 → `pytest`
- acp-bridge：安装 `.[dev]` → `pytest`

## 待办（按优先级）

1. 接入真实 dsh ACP endpoint，补齐 `session/update` → A2A streaming event 映射
2. 编写 AstrBot 路由插件设计文档（chat/tech/embodiment 三路由）
3. Persona Provider 的 Plan B 实现与 MaiBot 共用 eval 集
4. 评估集设计：人格一致性 / 记忆召回 / 路由准确率
5. A2A `message/send` 最终规范发布后，冻结 bridge wire schema
6. 部署文档暂缓，待代码骨架稳定后再写

## 贡献约定

- 架构变更先改 `ARCHITECTURE.md`，再落代码或配置
- 新增配置必须加入 `config/validate.py` 的结构校验
- bridge 保持“薄”：业务逻辑放 AstrBot / dsh / OpenViking，协议翻译放 bridge

