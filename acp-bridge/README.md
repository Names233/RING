# ACP ↔ A2A Bridge

薄适配器：把 A2A 任务请求转换为 ACP `initialize` / `session/new` / `session/prompt` JSON-RPC 调用，并把 `session/update` 流中的 `agent_message_chunk` / `plan` / `tool_call` 映射为 A2A 状态事件。

## 运行

```bash
pip install -e ".[dev]"
uvicorn digital_genesis_acp_bridge.main:app --host 0.0.0.0 --port 8090
```

## 配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ACP_ENDPOINT` | `http://dsh:3080` | dsh ACP JSON-RPC endpoint |
| `ACP_PROTOCOL_VERSION` | `1` | ACP 协议版本 |
| `ACP_SESSION_CWD` | `/workspace` | 新会话默认工作目录 |
| `ACP_TIMEOUT_SECONDS` | `300` | 单次 RPC 超时 |
| `BRIDGE_TIMEOUT_SECONDS` | `3600` | 单个 A2A 任务总超时 |

> 当前 A2A 侧采用与 Google A2A `message/send` 兼容的最小请求/响应结构；A2A 标准化仍在推进，落地时以最终规范冻结字段。
