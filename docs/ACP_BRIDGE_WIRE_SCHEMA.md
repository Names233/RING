# ACP Bridge Wire Schema

> 版本：v1（2026-10-20 核对实现）
> 状态：草案。当前实现与本文件存在若干偏差（见 §8），A2A `message/send` 最终规范发布后升级为 v2 并重新冻结。
> 实现：`acp-bridge/digital_genesis_acp_bridge/`

## 1. 边界与原则

```text
AstrBot ──A2A HTTP──► ACP Bridge ──ACP JSON-RPC──► dsh
```

Bridge 是无状态协议翻译层，遵循四条不变量：

1. **无密钥**：不持有任何模型 Key，只透传 ACP session。
2. **无业务**：不做意图判断、不修改 prompt 语义。
3. **一对一 session**：每个 A2A task 对应一个 ACP session。
4. **错误语义化**：ACP/RPC 错误映射为 A2A task `failed`，而非 HTTP 500。

## 2. 入站：A2A `message/send`

```http
POST /
Content-Type: application/json
```

> 实现 `main.py:35` 只注册了 `POST /`；本文早期草案写作 `/a2a`。`persona_plan_b/service.py` 同时注册了 `/` 与 `/a2a`，bridge 尚未跟进。

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        { "kind": "text", "text": "帮我部署 FastAPI 服务" }
      ]
    }
  }
}
```

约束：
- `params.message.role` 必须为 `user`。
- `parts` 至少一个 `text` part；其他 kind 忽略并记录 warning。
- 字段名在本文件用 A2A 规范的 `kind`，实现 `models.py` 用 `type`（默认 `"text"`）。入站时 pydantic 忽略未知的 `kind`、`text` 仍被解析，故当前可工作；出站 artifact 使用 `type`，与真实 A2A 客户端可能不兼容。
- 多个 text part 按顺序拼接为 ACP prompt。

## 3. 出站：A2A task

实际返回的是 JSON-RPC 包装的 A2A task（`models.py: A2AResponse`）：

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "id": "task-7f2c",
    "context_id": "req-001",
    "status": { "state": "completed", "message": null },
    "artifacts": [
      {
        "type": "text",
        "text": "ACP execution completed.",
        "metadata": { "acpSessionId": "sess-abc", "stopReason": "end_turn", "elapsedSeconds": 0.42 }
      }
    ]
  }
}
```

> 注意 `text` 当前恒为占位符：`acp_client.py:106` 从 `request.params["text"]` 取值，而 A2A 请求没有该字段；真实正文需监听 `session/update`（§6，未实现）。

状态映射：

| A2A state | 触发条件 |
|---|---|
| `completed` | ACP `session/prompt` 正常返回 stop |
| `failed` | ACP/RPC 错误、超时、非法输入 |

## 4. ACP 调用序列（当前同步实现）

```text
initialize
  ├─ clientInfo: { name: "digital-genesis-acp-bridge", version: "1.0" }
  ├─ protocolVersion: 1
  └─ capabilities: {}
        ↓
session/new
  ├─ cwd: "/workspace"
  └─ mcpServers: []
        ↓
session/prompt
  ├─ sessionId
  └─ prompt: [{ type: "text", "text": "..." }]
```

### 4.1 `initialize`

```json
{ "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": { "protocolVersion": 1, "clientInfo": { "name": "digital-genesis-acp-bridge", "version": "1.0" } } }
```

### 4.2 `session/new`

```json
{ "jsonrpc": "2.0", "id": 2, "method": "session/new", "params": { "cwd": "/workspace", "mcpServers": [] } }
```

### 4.3 `session/prompt`

```json
{ "jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": { "sessionId": "sess-abc", "prompt": [ { "type": "text", "text": "帮我部署 FastAPI 服务" } ] } }
```

## 5. 错误映射

| 来源 | ACP/RPC error | A2A 映射 | HTTP |
|---|---|---|---|
| AstrBot 请求 | 缺少 text part | task `failed` + error `invalid_input` | 200 |
| ACP 握手 | `initialize` 错误 | task `failed` + error `acp_handshake_failed` | 200 |
| 会话创建 | `session/new` 错误 | task `failed` + error `acp_session_failed` | 200 |
| 执行 | `session/prompt` 错误 | task `failed` + error `acp_prompt_failed` | 200 |
| Bridge 内部 | 未捕获异常 | task `failed` + error `internal_error` | 200 |

设计理由：上游 AstrBot 依赖 A2A task 状态做重试与追踪；把协议错误伪装成 HTTP 500 会破坏其状态机。

> 偏差：实现只返回 `status.message`，没有返回上表的 error code 字段；`invalid_input` 由 pydantic 校验返回 HTTP 422，而非 task failed。

## 6. 流式扩展（已设计，未实现）

按 `ACP_STREAMING_DESIGN.md`，v2 将引入：

1. `session/update` notification 监听。
2. 9 种 `sessionUpdate` → A2A streaming event 的映射。
3. `thought` / `usage` 只入 Langfuse，不外发 A2A。
4. 客户端断开时发送 `session/cancel`。

v1 与 v2 共存策略：v2 引入 `stream=true` 请求参数，默认 false，保持 v1 客户端兼容。

## 7. 验收用例

| 用例 | 期望 |
|---|---|
| 单 text part | prompt 原样透传，task `completed` |
| 多 text part | 按顺序拼接 |
| 无 text part | task `failed` + `invalid_input` |
| initialize 被拒 | task `failed` + `acp_handshake_failed` |
| session/new 被拒 | task `failed` + `acp_session_failed` |
| prompt 被拒 | task `failed` + `acp_prompt_failed` |
| dsh 不可达 | task `failed`，不抛 HTTP 5xx |

当前测试覆盖情况（`acp-bridge/tests/`，29 passed）：

- 已覆盖：单/多 text part、无 text part（经 pydantic 校验返回 422）；
- 未覆盖：`initialize` / `session/new` / `session/prompt` 被拒、dsh 不可达、`/a2a` 端点。`test_api.py` 用 monkeypatch 替换 `_build_client().run_task`，不经过真实 ACP 调用；`test_acp_client.py` 将 `text: ""` 固化为预期结果。

## 8. 当前实现偏差（2026-10-20）

1. **端点**：实现为 `POST /`，草案写作 `POST /a2a`。
2. **字段名**：文档 `kind`，实现 `type`。
3. **出站结构**：文档为裸 task，实现为 `A2AResponse{jsonrpc,id,result}`，且字段为 `context_id`（snake_case）。
4. **错误码**：文档定义 5 类 error code，实现只填 `status.message`。
5. **正文**：同步路径恒返回 `"ACP execution completed."`，未接 `session/update`。
6. **测试**：7 条验收用例仅覆盖约 3 条，且核心路径被 mock。
