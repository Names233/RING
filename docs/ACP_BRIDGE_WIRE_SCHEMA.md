# ACP Bridge Wire Schema

> 版本：v1（2026-10-12）
> 状态：当前同步实现的 wire 冻结草案；A2A `message/send` 最终规范发布后升级为 v2 并重新冻结。
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
POST /a2a
Content-Type: application/json
```

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
- 多个 text part 按顺序拼接为 ACP prompt。

## 3. 出站：A2A task

```json
{
  "id": "task-7f2c",
  "state": "completed",
  "artifacts": [
    {
      "name": "result",
      "parts": [
        { "kind": "text", "text": "部署完成：..." }
      ]
    }
  ]
}
```

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

以上用例由 `acp-bridge/tests/` 覆盖。
