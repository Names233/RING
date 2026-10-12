# Persona Provider Plan B 设计

Plan B 是 MaiBot 的替代实现：**小模型触发判断 + 主模型人格生成**。两者均实现同一 Persona Provider A2A 契约（见 `PERSONA_PROVIDER_CONTRACT.md`），测试集与 eval 完全复用。

## 1. 动机

- MaiBot 体量最小、GPL-3.0 license、停更风险最高
- 核心不可替代能力是“群聊动态触发”，可用两段式模型流水线近似
- 接口已抽象，替换成本应控制在部署层而非架构层

## 2. 架构

```text
AstrBot (A2A)
  ↓
Plan B Persona Provider
  ├─ Stage 1: 触发判断 (persona-trigger, 1B 本地模型)
  │   输入: message + group_context + recalled_memory(L0)
  │   输出: {should_reply, emotion}
  │
  ├─ Stage 2: 人格生成 (persona-chat, 主模型)
  │   输入: message + group_context + recalled_memory(L1) + Stage1 emotion
  │   输出: {text}
  │
  └─ 合并输出: {should_reply, text, emotion}
```

## 3. Stage 1: 触发判断

### 模型

`persona-trigger` → LiteLLM 路由到本地 1B 模型（如 qwen3:1b）

### Prompt 策略

```text
你是一个群聊触发判断器。判断数字生命“麦麦”是否应该回复这条消息。

规则：
- 被 @ 时必须回复
- 直接对话时必须回复
- 情感浓度高的消息倾向回复
- 纯技术问题倾向不回复（由路由层处理）
- 群聊闲聊但不相关时倾向不回复
- 拿不准时不回复

输出严格 JSON: {"should_reply": bool, "emotion": "..."}
```

### 约束

- 输出必须是合法 JSON，解析失败视为 `should_reply=false`
- 延迟预算 P95 ≤ 500ms（本地小模型）
- 不生成文本，只做判断

## 4. Stage 2: 人格生成

### 模型

`persona-chat` → LiteLLM 路由到主对话模型

### Prompt 组成

1. 人格设定（来自 `soul.yaml` 的 `persona.speaking_style`）
2. 群聊上下文（最近 N 条消息）
3. 召回记忆（L1 层用户画像）
4. Stage 1 的 emotion 标签

### 约束

- `should_reply=false` 时跳过 Stage 2，直接返回空文本
- 输出长度约束：IM 场景通常 ≤ 100 字
- 延迟预算 P95 ≤ 2.5s

## 5. 失败降级

| 故障 | 行为 |
|---|---|
| Stage 1 JSON 解析失败 | `should_reply=false`，静默 |
| Stage 1 超时 | `should_reply=false`，记 warning |
| Stage 2 失败 | 返回 `should_reply=true` + 兜底文案“我卡住了…” + `emotion: thinking` |
| LiteLLM 不可用 | 整体降级 `should_reply=false` |
| OpenViking 不可用 | 正常运行，recalled_memory 为空 |

## 6. 与 MaiBot 的对比

| 维度 | MaiBot | Plan B |
|---|---|---|
| 部署复杂度 | 高（完整服务） | 低（两个 LiteLLM 路由） |
| 触发判断 | 内置学习机制 | 静态 prompt + 小模型 |
| 表达学习 | 内置 | 依赖 OpenViking 记忆 + 定期 prompt 迭代 |
| 停更风险 | 存在 | 自控 |
| License | GPL-3.0 | 自研 |
| 评估复用 | 同一套 eval | 同一套 eval |

## 7. 实现路线

| 阶段 | 内容 |
|---|---|
| Step 1 | 实现 Stage 1 JSON 输出解析 + 失败降级 |
| Step 2 | 实现 Stage 2 prompt 组装 + 长度约束 |
| Step 3 | 接入 Persona Provider 契约层 |
| Step 4 | 跑 `evals/persona/cases.jsonl` 全集 |
| Step 5 | 与 MaiBot 输出对比，选优部署 |

## 8. 验收标准

1. 输出满足 `persona-provider-response.schema.json`
2. `should_reply=false` 时 `text` 为空（不变量 P1）
3. Stage 1 解析失败静默降级，不抛异常
4. Stage 2 失败返回兜底文案而非空响应
5. 人格一致性 eval 得分不低于 MaiBot 的 90%
