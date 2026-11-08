# RING 一级路由服务设计

> 版本：v2（2026-11-08 修订）
> 实现：`ring_router/`（v1 中的 `astrbot_router` 包已于 2026-11-08 更名为 `ring_router`）
> 部署：`ring-cloud.service` 内的第三个进程，监听 `127.0.0.1:18082`（仅回环）
> v1 → v2 变更：一级路由从"AstrBot 插件"改为**独立 HTTP 服务**；调用方从 AstrBot 改为 **MaiBot**；AstrBot 已从方案移除（2026-11-08 决议）。

## 0. 角色定位与调用关系

RING 的入口是 **MaiBot**：它自带 SnowLuma/OneBot 适配器接 QQ（NapCat），负责消息收发、对话生成与人格表现。MaiBot 在生成回复**之前**先把消息交给 **ring_router** 做一级意图路由，由 ring_router 判定这条消息该走哪条下游链路：

```text
QQ / TG 用户
   │  OneBot（NapCat，WS 127.0.0.1:3001）/ Telegram Bot API
   ▼
MaiBot（唯一入口：适配器 + 会话 + 人格生成）
   │  HTTP POST /route
   ▼
ring_router（127.0.0.1:18082，一级路由）
   ├─ chat       → persona_plan_b（灵魂，A2A，127.0.0.1:18081）
   ├─ tech       → ACP bridge → dsh（双手）
   └─ embodiment → AIRI（化身）
```

三条约束：

1. **ring_router 不执行任务**：只做意图分类、路由派发与结果回传，不产生业务结果。
2. **ring_router 是唯一编排层**：Persona / dsh / AIRI 三方互不直接调用，跨组件调度一律经 ring_router（对应 `PERSONA_PROVIDER_CONTRACT.md` 的 P4）。
3. **MaiBot 不被 ring_router 反向驱动**：路由结果只用于决定"这一段对话交给谁"，MaiBot 始终持有消息通道与最终投递权。

### 0.1 调用契约（MaiBot → ring_router）

| 端点 | 方法 | 用途 | 备注 |
|---|---|---|---|
| `/route` | POST | 一级路由判定（可选 `dispatch=true` 直接转发下游） | 入参见 §4.1，出参见 §4.2 |
| `/health` | GET | 存活探针，附带当前运行模式 | `{\"status\": \"ok\", \"service\": \"ring-router\", \"mode\": ...}` |
| `/mode` | GET | 查询 Mode A/B 状态与待办任务数 | 见 `HYBRID_REDUNDANCY_DESIGN.md` §3 |
| `/heartbeat` | POST | 本地节点心跳上报（`X-Heartbeat-Token` + nonce + seq） | 由本地 `scripts/run_local_node.py` 调用 |
| `/tasks/pending` | GET | 列出 Mode B 期间暂存的任务 | 本地恢复后回放 |
| `/tasks/{task_id}/complete` | POST | 回填任务结果 | — |

> 服务只监听回环地址，不对外暴露；MaiBot 与 ring_router 同处云端同一台主机，走 `127.0.0.1`。

## 1. 设计原则

1. **ring_router 不执行任务**：只做意图分类、路由派发与结果投递，不产生业务结果。
2. **一级路由优先**：复杂任务拆解由 dsh 完成；ring_router 只决定"交给谁"，不决定"怎么做"。
3. **人设一致性优先于路由准确性**：拿不准时宁可走 Persona Provider 闲聊兜底，不要把人格消息错误路由到 dsh 造成机器人感。
4. **失败降级**：下游不可用时必须降级到本地回复，不允许消息被静默吞掉。
5. **无持久化状态**：路由判定不落盘；需要留存的状态一律写 OpenViking。

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
| `chat` | Persona Provider | "早上好"、"这个梗好好笑"、"有点累了" | 技术任务、表演动作 |
| `tech` | dsh（经 ACP bridge） | "帮我部署一下"、"修这个报错"、"跑下测试" | 闲聊、情绪表达 |
| `embodiment` | AIRI | "笑一下"、"做个开心表情"、"用语音说" | 技术执行、文本回复本身 |

平台口径（2026-11-08 起）：仅 **QQ** 与 **Telegram**。路由分类与平台无关，但二者之外的平台（Discord / 飞书 / 钉钉 / WebChat）当前不接，未来若需要另立接入层。

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
| Persona Provider 超时/失败 | ring_router 返回固定兜底文案"我刚才走神了，再说一遍？"，由 MaiBot 投递 |
| ACP bridge 超时/失败 | 返回"这个任务我暂时处理不了，已记录失败" + Langfuse 记录 |
| AIRI 失败 | 忽略表现层动作，仅文本回复降级 |
| OpenViking 不可用 | 路由照常，仅无记忆召回，记录 warning |

## 6. 与 OpenViking 的交互

路由前 ring_router 召回一次记忆（L0 优先）：

| 召回时机 | 内容 | 用途 |
|---|---|---|
| 路由前 | 用户偏好、近期上下文（L0/L1） | 帮助意图判断 |
| 派发 Persona 前 | 用户画像、表达偏好（L1） | 填充 `recalled_memory.fragments` |
| 派发 dsh 前 | 项目资源摘要（L0） | 提供给 ACP prompt 上下文 |

召回失败不阻塞路由；降级为无记忆模式并记录。ring_router 的记忆命名空间为 `viking://memories/agents/ring_router/`（逻辑路径，物理映射见 `OPENVIKING_PERMISSION_MATRIX.md` §1.1）。

## 7. 实现状态

| 能力 | 状态 | 证据 |
|---|---|---|
| 规则路由（关键词 + 正则） | ✅ | `ring_router/core.py::rule_classify` |
| 显式触发词优先 | ✅ | `_explicit_trigger`，可绕过 confidence 门禁 |
| confidence < 0.6 回落 chat | ✅ | `classify()`，阈值可配置 |
| 模型不可用降级 | ✅ | `model_route=None` 时走规则并标记 `degraded=True` |
| 模型分类（主路径） | ✅ 已接 AGT | `classify_with_agt()` 经 `ring_common.llm_client.AGTClient` 调用 AGT 网关 `gemini-3.8-flash`，解析失败回落规则路径 |
| 下游映射 | ✅ | `decide_downstream()`：persona / bridge / AIRI |
| 路由服务化（HTTP） | ✅ | `ring_router/service.py`：`POST /route`、`GET /health`、`GET /mode`；`tests/test_new_services.py::test_router_service` |
| 心跳与 Mode A/B | ✅ 已实测 | `HeartbeatRegistry`：token 校验 + nonce 去重 + seq 单调 + 45s 超时；`POST /heartbeat`、`GET /mode`、`/tasks/pending`；本地 `scripts/run_local_node.py` 与云端 `scripts/run_cloud_node.py` 已按此联调（A ↔ B 切换实测） |
| dispatch 到 persona | ✅ | `POST /route` 的 `dispatch=true` 分支转发 `127.0.0.1:18081/a2a` |
| dispatch 到 dsh（ACP bridge） | 🟡 代码就位，未联调 | 转发逻辑存在；真实 dsh 的 ACP 传输仍未核实，见 `DEVELOPMENT.md` 已知缺口 |
| eval baseline 复用 | ✅（口径受限） | `scripts/run_evals.py` 调用同一 `rule_classify`，routing 50/50 回归通过；标签与规则同源，只证明回归一致，不代表真实准确率 |
| MaiBot 侧调用方 | ⏳ 待接 | MaiBot 尚未在真实消息链路上调用 `/route`；QQ 当前只有 2 个好友、不在任何群，尚无群聊真实流量 |
| 意图分类器主路径的离线准确率 | ⏳ 未验证 | 已接 AGT，但未用真实模型输出重跑 routing eval（当前 predictions 仍为构造 fixture） |

## 8. 验收标准

1. 路由准确率 eval 集 ≥ 90%（`intent-router` 模型）
2. 三条路由每条至少有 20 条标注样本（当前 tech 43 / chat 4 / embodiment 3，chat 与 embodiment 未达标）
3. 故障降级路径全部有测试：模型挂、Persona 挂、bridge 挂、AIRI 挂、OpenViking 挂
4. Langfuse 能按 `trace_id` 串联：入站消息 → 意图分类 → 路由 → 下游调用
5. 路由插件本身无持久化状态；任何状态写入 OpenViking

## 9. 路由测试集初始样本

以下 12 条是初始样本（现已扩充为 50 条，见 `evals/routing/cases.jsonl`；扩充后仍不均衡，需继续补 chat 与 embodiment）：

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
