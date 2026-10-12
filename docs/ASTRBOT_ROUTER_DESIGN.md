# AstrBot 路由插件设计

AstrBot 瘦身后只承担“感知与投递”职责，其中最关键的决策点是**一级路由**：判断一条消息应交给 Persona Provider（灵魂）、dsh（双手）还是 AIRI（化身）。

## 1. 设计原则

1. **AstrBot 不执行任务**：只做意图分类、路由派发与结果投递，不产生业务结果。
2. **一级路由优先**：复杂任务拆解由 dsh 完成；AstrBot 只决定“交给谁”，不决定“怎么做”。
3. **人设一致性优先于路由准确性**：拿不准时宁可走 Persona Provider 闲聊兜底，不要把人格消息错误路由到 dsh 造成机器人感。
4. **失败降级**：下游不可用时必须降级到本地回复，不允许消息被静默吞掉。

## 2. 路由决策树

```text
入站消息
  │
  ├─ 1. 显式触发词? ─────────────► dsh
  │     (deploy/build/fix/run/debug/research)
  │
  ├─ 2. 表现层关键词? ──────────► AIRI
  │     (表情/语音/动画/形象)
  │
  ├─ 3. 技术动作意图? ───────────► dsh
  │     (改代码/部署/跑命令/查日志/装依赖)
  │
  ├─ 4. 情感/闲聊/人格消息? ─────► Persona Provider
  │     (问候/吐槽/接梗/情绪)
  │
  └─ 5. 兜底 ────────────────────► Persona Provider
        (Persona 判断 should_reply)
```

## 3. 路由分类定义

| 路由 | 触发目标 | 典型输入 | 明确不触发 |
|---|---|---|---|
| `chat` | Persona Provider | “早上好”、“这个梗好好笑”、“有点累了” | 技术任务、表演动作 |
| `tech` | dsh（经 ACP bridge） | “帮我部署一下”、“修这个报错”、“跑下测试” | 闲聊、情绪表达 |
| `embodiment` | AIRI | “笑一下”、“做个开心表情”、“用语音说” | 技术执行、文本回复本身 |

## 4. 意图分类器

### 4.1 输入

```json
{
  "text": "帮我部署一下服务",
  "platform": "qq",
  "conversation_id": "group:123",
  "at_me": true,
  "has_attachment": false,
  "recent_messages": []
}
```

### 4.2 输出

```json
{
  "route": "tech",
  "confidence": 0.92,
  "reason": "deploy verb + service object",
  "fallback": "chat"
}
```

### 4.3 规则

- `route` 只能是 `chat` / `tech` / `embodiment` 之一
- `confidence < 0.6` 时走 `fallback`（默认 `chat`）
- 显式触发词优先级高于模型分类，可绕过低置信度降级
- `at_me=false` 且非触发词时，默认走 `chat` 并由 Persona Provider 决定是否回复

## 5. 降级策略

| 故障 | 行为 |
|---|---|
| 意图模型不可用 | 走规则路由（关键词 + 正则），日志记录降级事件 |
| Persona Provider 超时/失败 | AstrBot 发送固定兜底文案“我刚才走神了，再说一遍？” |
| ACP bridge 超时/失败 | 返回“这个任务我暂时处理不了，已记录失败” + Langfuse 记录 |
| AIRI 失败 | 忽略表现层动作，仅文本回复降级 |
| OpenViking 不可用 | 路由照常，仅无记忆召回，记录 warning |

## 6. 与 OpenViking 的交互

路由前 AstrBot 召回一次记忆（L0 优先）：

| 召回时机 | 内容 | 用途 |
|---|---|---|
| 路由前 | 用户偏好、近期上下文（L0/L1） | 帮助意图判断 |
| 派发 Persona 前 | 用户画像、表达偏好（L1） | 填充 `recalled_memory.fragments` |
| 派发 dsh 前 | 项目资源摘要（L0） | 提供给 ACP prompt 上下文 |

召回失败不阻塞路由；降级为无记忆模式并记录。

## 7. 实现状态

| 能力 | 状态 | 证据 |
|---|---|---|
| 规则路由（关键词 + 正则） | ✅ | `astrbot_router/core.py::rule_classify` |
| 显式触发词优先 | ✅ | `_explicit_trigger`，可绕过 confidence 门禁 |
| confidence < 0.6 回落 chat | ✅ | `classify()`，阈值可配置 |
| 模型不可用降级 | ✅ | `model_route=None` 时走规则并标记 `degraded=True` |
| 下游映射 | ✅ | `decide_downstream()`：persona / bridge / AIRI |
| eval baseline 复用 | ✅ | `scripts/run_evals.py` 调用同一 `rule_classify`，routing 12/12 通过 |
| 意图分类器主路径 | ⏳ | 待接 `intent-router` 模型（LiteLLM） |
| AstrBot 插件接入 | ⏳ | 待真实 AstrBot 环境 |

## 8. 验收标准

1. 路由准确率 eval 集 ≥ 90%（`intent-router` 模型）
2. 三条路由每条至少有 20 条标注样本
3. 故障降级路径全部有测试：模型挂、Persona 挂、bridge 挂、AIRI 挂、OpenViking 挂
4. Langfuse 能按 `trace_id` 串联：入站消息 → 意图分类 → 路由 → 下游调用
5. 路由插件本身无持久化状态；任何状态写入 OpenViking

## 9. 路由测试集初始样本

以下样本作为 `evals/routing/cases.jsonl` 的初始集，可直接复制使用：

```jsonl
{"id":"route-001","text":"帮我部署一下服务","expected_route":"tech","difficulty":"easy"}
{"id":"route-002","text":"今天好累啊","expected_route":"chat","difficulty":"easy"}
{"id":"route-003","text":"笑一下","expected_route":"embodiment","difficulty":"easy"}
{"id":"route-004","text":"修一下这个报错","expected_route":"tech","difficulty":"easy"}
{"id":"route-005","text":"这个梗好好笑","expected_route":"chat","difficulty":"easy"}
{"id":"route-006","text":"用语音说一遍","expected_route":"embodiment","difficulty":"medium"}
{"id":"route-007","text":"查一下昨天部署的日志","expected_route":"tech","difficulty":"medium"}
{"id":"route-008","text":"有点想你了","expected_route":"chat","difficulty":"medium"}
{"id":"route-009","text":"换个开心点的表情","expected_route":"embodiment","difficulty":"easy"}
{"id":"route-010","text":"跑下测试然后告诉我结果","expected_route":"tech","difficulty":"medium"}
{"id":"route-011","text":"早上好","expected_route":"chat","difficulty":"easy"}
{"id":"route-012","text":"帮我看看这个仓库","expected_route":"tech","difficulty":"medium"}
```
