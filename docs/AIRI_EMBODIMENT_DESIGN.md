# AIRI 化身层接入设计

AIRI 是 v3 架构中的**化身层**：视觉形象、语音、动画与游戏 Agent。本文定义它如何接入 AstrBot 路由、OpenViking 记忆与 NATS 事件总线，并把误差控制在"表现失败只损失表现，不损失对话"的范围内。

## 1. 定位与边界

| AIRI 负责 | AIRI 不负责 |
|---|---|
| Live2D/VRM 形象渲染与动作 | 意图分类与一级路由（AstrBot） |
| 本地/云端 TTS 语音合成 | 人格文本生成（Persona Provider） |
| 表情/动作/动画驱动（MAGIC） | 技术任务执行（dsh） |
| 游戏内 Agent 行为 | 记忆存储与索引（OpenViking） |
| 表现状态上报（当前动作/场景） | 平台消息收发（AstrBot） |

核心边界：**AIRI 只把"情绪/意图"翻译成"表现"，永远不生成业务文本。**

## 2. 接入拓扑

```text
AstrBot (A2A)
  │ embodiment 请求 {emotion, action, text?, voice?}
  ▼
AIRI Embodiment Provider
  ├─ MCP → OpenViking（只读写 viking://memories/agents/airi/）
  ├─ MAGIC motion driver → Live2D/VRM 动作
  └─ TTS（VOICEVOX / 本地）→ 语音输出
NATS 事件总线
  ├─ persona.* 事件 → AIRI 触发表情
  └─ embodiment.* 事件 → AIRI 上报表现状态
```

## 3. A2A 请求契约

AstrBot 路由判定为 `embodiment` 时，向 AIRI 发送 A2A 任务消息：

```json
{
  "jsonrpc": "2.0",
  "id": 101,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "笑一下"}]
    },
    "metadata": {
      "route": "embodiment",
      "emotion": "happy",
      "requested_action": "laugh",
      "voice": {"enabled": true, "text": "嘿嘿，好呀"},
      "trace_id": "lf_01hx..."
    }
  }
}
```

AIRI 响应（A2A task）：

```json
{
  "jsonrpc": "2.0",
  "id": 101,
  "result": {
    "id": "task-uuid",
    "status": {"state": "completed", "message": "played motion laugh"},
    "artifacts": [
      {
        "type": "text",
        "text": "laugh",
        "metadata": {
          "motion": "smile_open",
          "expression": "happy",
          "duration_ms": 1800,
          "voice_played": true
        }
      }
    ]
  }
}
```

约束：

1. `emotion` 枚举与 Persona Provider Response Schema 完全一致（8 值）
2. `requested_action` 允许为空；为空时 AIRI 按 `emotion` 自动选默认动作
3. AIRI 不改写、不扩展文本内容；TTS 只朗读 `voice.text`
4. `voice.enabled=false` 时 TTS 不得触发

## 4. emotion → 表现映射

默认映射（可通过 `soul.yaml` 覆盖）：

| Persona emotion | Live2D expression | MAGIC motion | TTS 语速 |
|---|---|---|---|
| `happy` | `smile_open` | `happy_wave` | 1.1 |
| `excited` | `smile_open` | `celebrate` | 1.2 |
| `sad` | `sad_down` | `sad_head` | 0.9 |
| `angry` | `angry_brow` | `shake_head` | 1.0 |
| `thinking` | `eyes_up` | `thinking_pose` | 0.95 |
| `shy` | `blush` | `cover_face` | 0.9 |
| `sleepy` | `eyes_half` | `yawn` | 0.85 |
| `neutral` | `default` | `idle` | 1.0 |

映射规则：

1. **未知 emotion 降级到 `neutral`**，记 warning，不报错
2. **动作缺失降级到表情**：motion 不可用时只切表情
3. **表情也缺失降级到 idle**：保证 AIRI 不因资源缺失而崩溃
4. 映射表是**纯数据**，放 `soul.yaml`，不写死在代码里

## 5. OpenViking 记忆读写

| 操作 | Namespace | 级别 | 触发时机 |
|---|---|---|---|
| 读用户偏好 | `viking://memories/users/` | L1 | 表现个性化（如用户喜欢短动画） |
| 读自身状态 | `viking://memories/agents/airi/` | L0→L1 | 启动时恢复上下文、游戏进度 |
| 写表现历史 | `viking://memories/agents/airi/embodiment_history/` | L1 | 每次表现完成后 |
| 写游戏进度 | `viking://memories/agents/airi/game_progress/` | L1 | 游戏状态变更 |
| 写关系状态 | `viking://memories/agents/airi/relationship.md` | L1 | 互动关系变化 |

权限遵循 `OPENVIKING_PERMISSION_MATRIX.md`：

- AIRI 对 `memories/users/` **只读**（P-02）
- AIRI 只写 `memories/agents/airi/`（P-01）
- AIRI 不写 `skills/`、`memories/shared/`（P-03/P-04）
- 读取优先 L0 摘要，按需升级 L1（P-06）

**本地状态迁移**：AIRI 原生本地记忆（游戏进度、互动历史）一次性迁入 `viking://memories/agents/airi/`，之后本地目录只作为运行时缓存，崩溃恢复时以 OpenViking 为权威源。

## 6. 事件总线联动

### 6.1 事件分类

| 事件 | 发布者 | 订阅者 | 触发 |
|---|---|---|---|
| `persona.emotion.changed` | Persona Provider | AIRI、OpenViking | emotion 变化 |
| `persona.response.completed` | Persona Provider | AIRI、AstrBot | 人格回复完成 |
| `embodiment.motion.requested` | AstrBot | AIRI | 路由到 embodiment |
| `embodiment.motion.completed` | AIRI | Persona Provider、OpenViking | 动作播放完成 |
| `embodiment.motion.failed` | AIRI | Persona Provider、AstrBot | 表现失败 |
| `deploy.completed` | dsh | AIRI、Persona Provider、OpenViking | 部署成功 |
| `deploy.failed` | dsh | AIRI、Persona Provider、OpenViking | 部署失败 |

### 6.2 payload schema

`persona.emotion.changed`：

```json
{
  "event": "persona.emotion.changed",
  "trace_id": "lf_01hx...",
  "session_id": "group:123",
  "user_id": "names",
  "from": "neutral",
  "to": "happy",
  "reason": "user celebration"
}
```

`embodiment.motion.requested`：

```json
{
  "event": "embodiment.motion.requested",
  "trace_id": "lf_01hx...",
  "task_id": "a2a-task-123",
  "emotion": "happy",
  "requested_action": "laugh",
  "voice": {"enabled": true, "text": "部署好了！"},
  "source": "astrbot"
}
```

`embodiment.motion.completed`：

```json
{
  "event": "embodiment.motion.completed",
  "trace_id": "lf_01hx...",
  "task_id": "a2a-task-123",
  "motion": "happy_wave",
  "expression": "smile_open",
  "duration_ms": 1800,
  "voice_played": true
}
```

`embodiment.motion.failed`：

```json
{
  "event": "embodiment.motion.failed",
  "trace_id": "lf_01hx...",
  "task_id": "a2a-task-123",
  "requested_action": "laugh",
  "emotion": "happy",
  "error": "motion_asset_missing",
  "degraded_to": "expression_only"
}
```

规则：

1. 每个事件必须携带 `trace_id`（Langfuse 关联）与来源标识
2. `embodiment.motion.failed` 必须携带 `degraded_to`（`expression_only` / `idle` / `none`）
3. AIRI 不发布技术执行类事件（`deploy.*` 由 dsh 发布）
4. 事件 payload 以本文为 schema 基准，后续可加 JSON Schema 冻结

## 7. 场景联动清单

| 场景 | 触发 | AIRI 行为 | 失败降级 |
|---|---|---|---|
| 日常闲聊 | `persona.emotion.changed` | 按映射切表情/动作 | idle |
| 用户报喜 | `deploy.completed` 或用户文本 | `celebrate` + 可选 TTS | 只切 happy 表情 |
| 用户低落 | Persona emotion=`sad` | `sad_head`、语速降低 | neutral idle |
| 技术任务执行中 | `embodiment.motion.requested` | `thinking_pose` | 保持 idle |
| 部署失败 | `deploy.failed` | `sad_down` + 安慰语气 TTS | 只文本回复 |
| 游戏陪伴 | 用户进入游戏场景 | 游戏内 Agent 行为 + 进度写 OpenViking | 退出游戏，仅 IM |
| 直播互动 | 弹幕/连麦事件 | 实时表情 + TTS | 降级为静态表情 |

## 8. MCP 接入配置片段

```yaml
mcp_servers:
  openviking:
    url: "http://openviking:8080/mcp"
    auth:
      agent_id: "airi"
      credential_env: "VIKING_MCP_TOKEN"
    scopes:
      read:
        - "viking://resources/"
        - "viking://memories/users/"
        - "viking://memories/agents/{self}/"
        - "viking://memories/agents/{other}/"  # 只读其他 Agent 经历
        - "viking://memories/shared/"
        - "viking://skills/"
      write:
        - "viking://memories/agents/airi/"
```

> 上述 `viking://memories/...`、`viking://skills/` 是逻辑命名空间；OpenViking 物理布局映射见 [`OPENVIKING_PERMISSION_MATRIX.md`](./OPENVIKING_PERMISSION_MATRIX.md) §1.1。

## 9. 失败降级矩阵

| 故障 | 行为 | 对用户影响 |
|---|---|---|
| 动作资源缺失 | 只切表情，发 `motion.failed` + `degraded_to=expression_only` | 无动作，有表情 |
| 表情资源缺失 | 保持 idle，`degraded_to=idle` | 无表现，对话正常 |
| TTS 失败 | 跳过语音，`voice_played=false` | 只有动作/表情 |
| OpenViking 不可用 | 正常表现，无记忆读写，记 warning | 无个性化，不中断 |
| 事件总线断开 | AIRI 内部继续，状态不广播 | 联动暂停，单机可用 |
| AIRI 整体不可用 | AstrBot 返回纯文本回复 | 损失表现层，不损失对话 |

## 10. 实现路线

| 阶段 | 内容 |
|---|---|
| Step 1 | emotion→表情/动作映射表冻结（本文第 4 节） |
| Step 2 | A2A embodiment 请求/响应契约冻结（可加 JSON Schema） |
| Step 3 | 事件 payload JSON Schema 化 |
| Step 4 | AIRI MCP 凭证按权限矩阵配置 |
| Step 5 | 本地记忆迁移到 `viking://memories/agents/airi/` |
| Step 6 | 事件总线联调（NATS） |
| Step 7 | 表现 eval：映射正确率 + 降级成功率 |

## 11. 验收标准

1. AIRI 不再落本地私有记忆（运行时缓存除外）
2. `persona.*` / `embodiment.*` 事件 payload 与本文 schema 一致
3. 8 种 emotion 全部有默认映射，未知 emotion 降级 `neutral` 有测试
4. 表现失败不阻塞文本对话（AIRI 挂掉时 AstrBot 仍可回复）
5. MCP 权限与权限矩阵一致：`memories/users/` 只读，只写 `agents/airi/`
6. 每个事件可由 `trace_id` 关联到 Langfuse
