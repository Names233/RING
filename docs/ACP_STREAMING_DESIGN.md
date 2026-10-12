# ACP 流式事件映射设计

本文档定义 ACP `session/update` 通知如何映射为 A2A 流式事件。当前 bridge 实现为同步 request/response；本设计为后续接入真实 dsh 后的流式扩展提供规范，避免凭空实现。

## 1. 目标

1. AstrBot 能实时展示 dsh 的执行进度（“正在读文件”、“正在跑测试”）
2. 保持 bridge 薄层定位：只做事件转换，不缓存、不重排、不产生业务语义
3. 每个事件可追溯到 ACP session 与 A2A task

## 2. ACP 事件分类与映射

| ACP `sessionUpdate` | A2A 事件映射 | 说明 |
|---|---|---|
| `agent_message_chunk` | `status-update: working` + text delta | Agent 输出流 |
| `agent_thought_chunk` | 内部事件，不上报 A2A | 推理过程，仅入 Langfuse |
| `user_message_chunk` | 不映射 | bridge 自身产生的回显 |
| `tool_call` | `status-update: working` + tool 开始事件 | 工具调用开始 |
| `tool_call_update` | `status-update: working` + tool 状态事件 | 工具调用进度/结果 |
| `plan` | `status-update: working` + plan 快照 | 执行计划全量替换 |
| `usage_update` | 内部事件，仅入 Langfuse | token/成本统计 |
| `notice` | `status-update: input-required` 或 warning | 按 severity 分流 |
| `compaction_update` | 内部事件 | 上下文压缩，不影响 A2A |

## 3. 事件结构

```json
{
  "type": "status-update",
  "task_id": "a2a-task-123",
  "context_id": "acp-session-456",
  "status": "working",
  "message": "正在运行测试",
  "metadata": {
    "acp_session_id": "acp-session-456",
    "event_kind": "tool_call",
    "tool_call_id": "tc-001",
    "langfuse_trace_id": "lf_01hx"
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | 固定为 `status-update` |
| `task_id` | 是 | A2A task ID，bridge 生成 |
| `context_id` | 是 | 使用 ACP session ID，便于跨事件关联 |
| `status` | 是 | `working` / `input-required` / `completed` / `failed` |
| `message` | 否 | 人类可读的进度描述 |
| `metadata.event_kind` | 是 | 原始 ACP `sessionUpdate` 类型 |
| `metadata.langfuse_trace_id` | 否 | 全链路追踪 ID |

## 4. 映射规则

1. **顺序保持**：ACP 通知到达顺序即 A2A 事件发送顺序，bridge 不重排。
2. **plan 全量替换**：`plan` 事件总是携带完整计划快照，消费方直接替换本地状态。
3. **text delta 追加**：`agent_message_chunk` 的 content 追加到当前回复缓冲区。
4. **thought 不外发**：`agent_thought_chunk` 仅写入 Langfuse，防止内部推理泄露到 IM。
5. **usage 不外发**：成本数据入 Langfuse，不作为用户可见事件。
6. **terminal 一次性**：`completed` / `failed` 只发送一次，之后关闭流。
7. **未知事件忽略**：新版本 ACP 新增的 `sessionUpdate` 类型记 warning 日志但不中断。

## 5. 错误处理

| 场景 | 行为 |
|---|---|
| ACP 连接中断 | 发送 `failed` 事件，message 说明连接中断 |
| ACP 返回 error response | 发送 `failed` 事件，附 RPC error message |
| bridge 超时 | 发送 `failed` 事件，标记 timeout |
| 客户端断开 | 停止转发，向 ACP 发送 `session/cancel` |
| 未知 sessionUpdate | 忽略 + warning 日志 |

## 6. 与 Langfuse 的关联

每个流式任务创建一个 Langfuse trace：

- trace metadata 包含 `task_id`、`acp_session_id`
- 每个映射后的事件生成一个 span
- `agent_thought_chunk` 与 `usage_update` 虽不外发，但生成 span 保留完整执行历史

## 7. 实现路线

| 阶段 | 内容 |
|---|---|
| Step 1 | ACP client 支持 JSON-RPC notification 监听 |
| Step 2 | bridge 内部事件总线：ACP notification → 映射函数 → A2A emitter |
| Step 3 | 单元测试：每种 `sessionUpdate` 类型至少一个用例 |
| Step 4 | 集成真实 dsh，验证事件顺序与 terminal 语义 |
| Step 5 | Langfuse span 接入 |

## 8. 验收标准

1. 映射表覆盖 ACP v1 全部 `sessionUpdate` 类型，未知类型有忽略策略
2. 顺序性测试：乱序注入事件，输出顺序与输入一致
3. terminal 语义测试：`completed` / `failed` 后不再发送任何事件
4. `agent_thought_chunk` 不出现在 A2A 输出中
5. 客户端断开时调用 `session/cancel`
