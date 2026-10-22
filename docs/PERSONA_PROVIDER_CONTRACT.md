# Persona Provider A2A 契约

Persona Provider 是 RING 中可替换的“灵魂层”。MaiBot 是当前实现，但接口层面不绑定 MaiBot：任何满足本契约的服务都可以替换它。

- 请求 Schema：[`schemas/persona-provider.schema.json`](../schemas/persona-provider.schema.json)
- 响应 Schema：[`schemas/persona-provider-response.schema.json`](../schemas/persona-provider-response.schema.json)

## 1. 设计原则

1. **无状态服务**：Provider 不保存用户画像、表达学习成果或会话历史；持久化全部下沉到 OpenViking。
2. **单回合决策**：一次调用完成“是否回复 + 回复内容 + 情绪标签”的完整决策。
3. **可替换性**：MaiBot、自研 Plan B（小模型触发 + 主模型生成）、未来人格服务均实现同一契约。
4. **可追踪性**：可选 `trace_id` 贯穿 Langfuse 全链路 trace。

## 2. 请求结构

```json
{
  "message": {
    "role": "user",
    "parts": [{ "type": "text", "text": "今天有什么新部署吗？" }]
  },
  "group_context": {
    "platform": "qq",
    "conversation_id": "group:123456",
    "speaker_id": "u:names",
    "speaker_name": "Names",
    "at_me": false,
    "recent_messages": []
  },
  "recalled_memory": {
    "fragments": [
      {
        "uri": "viking://memories/users/names/preferences.md",
        "summary": "偏好简洁回复",
        "level": "L1"
      }
    ]
  }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `message.role` | 是 | 固定为 `user`；Provider 不接受 agent 自回消息 |
| `message.parts[]` | 是 | A2A text part；多段文本由 Provider 合并 |
| `group_context.platform` | 是 | `qq` / `telegram` / `discord` / ... |
| `group_context.conversation_id` | 是 | 平台无关会话 ID，例如 `group:123456` |
| `group_context.at_me` | 否 | 是否 @ 机器人；默认 false |
| `recalled_memory.fragments[]` | 是 | 可为空数组，但字段本身必须存在 |
| `fragments[].uri` | 是 | 必须是 `viking://` URI |
| `fragments[].level` | 是 | OpenViking L0/L1/L2 渐进上下文层级 |

> 示例 URI 为逻辑命名空间；OpenViking 物理布局映射见 [`OPENVIKING_PERMISSION_MATRIX.md`](./OPENVIKING_PERMISSION_MATRIX.md) §1.1。

## 3. 响应结构

```json
{
  "should_reply": true,
  "text": "刚把文档骨架推上去了，CI 已经绿了～",
  "emotion": "happy",
  "trace_id": "lf_01hx"
}
```

### 不变量

| 编号 | 不变量 | 违反后果 |
|---|---|---|
| P1 | `should_reply=false` 时 `text` 必须为空字符串 | 调用方拒绝响应 |
| P2 | `emotion` 只能取枚举值 | 调用方拒绝响应 |
| P3 | Provider 不写 OpenViking | 违反架构分层 |
| P4 | Provider 不直接调用 dsh/AIRI | 由 AstrBot 负责编排 |
| P5 | 响应延迟 P95 ≤ 3s；超时按 `should_reply=false` 降级 | 调用方超时静默 |

## 4. Plan B 降级实现

当 MaiBot 停更或不可用时，用两个 LiteLLM 路由替代：

| 步骤 | 模型路由 | 输出 |
|---|---|---|
| 触发判断 | `persona-trigger`（1B 级本地模型） | `{should_reply, emotion}` |
| 人格生成 | `persona-chat`（主对话模型） | `{text}`，仅当 should_reply=true |

两个步骤均实现同一 JSON 契约，测试集可直接复用。

## 5. 验收标准

1. 两个 JSON Schema 通过 `jsonschema` 校验。
2. 所有契约示例与 Schema 完全一致。
3. Plan B 实现能通过 MaiBot 相同的 eval 集。
4. Langfuse 能用 `trace_id` 追踪到 Persona Provider span。
