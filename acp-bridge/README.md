# ACP ↔ A2A Bridge

薄适配器：把 A2A 任务请求转换为 ACP `initialize` / `session/new` / `session/prompt` JSON-RPC 调用。当前只实现同步路径；`streaming.py` 的 `session/update` → A2A 状态映射是纯函数骨架，尚未接线。

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

## 当前限制（2026-10-20）

- 端点只有 `POST /`，未提供 wire 草案中的 `POST /a2a`。
- 同步路径拿不到执行正文：`acp_client.py` 的 `run_task` 取 `request.params["text"]`（A2A 请求无此字段），`main.py` 回退为 `"ACP execution completed."`；真实正文需监听 `session/update`。
- `streaming.py` 的映射逻辑有 21 个单元测试，但未被 `main.py` 使用。
- 未与真实 dsh 联调，ACP 传输方式（HTTP JSON-RPC / SSE / stdio）尚未核实。
- 与 `docs/ACP_BRIDGE_WIRE_SCHEMA.md` 存在端点、字段名（`type` vs `kind`）、出站结构、错误码偏差，详见该文档 §8。
