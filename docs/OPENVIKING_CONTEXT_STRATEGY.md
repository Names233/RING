# OpenViking 渐进上下文与记忆生命周期策略

> 文档版本：v1（2026-10-20 核查）  
> 归属：Phase 1（记忆层）核心规范  
> 关联文档：[`ARCHITECTURE.md`](../ARCHITECTURE.md), [`OPENVIKING_PERMISSION_MATRIX.md`](./OPENVIKING_PERMISSION_MATRIX.md)

OpenViking 作为 Digital Genesis 的统一上下文总线，承载全局资源（`resources/`）、用户画像（`users/`）、各 Agent 经历（`agents/`）、共享上下文（`shared/`）与工程技能（`skills/`）。

> 命名空间说明：上述 `resources/`、`users/`、`agents/`、`shared/`、`skills/` 是逻辑视图；OpenViking 物理根为 `resources/`、`user/{id}/`、`agent/`，映射见 [`OPENVIKING_PERMISSION_MATRIX.md`](./OPENVIKING_PERMISSION_MATRIX.md) §1.1。L0/L1/L2 是本项目的 front matter 约定，不是 OpenViking 原生分层。

为了杜绝大模型在长期交互下的 **Token 爆炸** 与 **记忆幻觉**，系统严格实施 **L0 / L1 / L2 渐进式召回（Progressive Context Recall）** 与 **记忆生命周期置信度衰减** 机制。

---

## 1. L0 / L1 / L2 分层定义与 Token 预算

| 分层 | 粒度 | 内容结构 | 适用阶段 | 单项 Token 预算 | 批量总上限 |
|---|---|---|---|---|---|
| **L0 (Overview)** | 目录/文件极简摘要 | 核心主题、关键实体标签、时间范围、重要度评级 | 意图路由初筛、感知启动、全局概览 | ≤ 80 tokens | ≤ 400 tokens |
| **L1 (Key Fragments)** | 结构化事实与偏好片段 | 用户习惯、项目配置结论、关键交互经验、情绪偏好 | 常规闲聊、单任务执行、提示词上下文装载 | ≤ 250 tokens | ≤ 1,200 tokens |
| **L2 (Raw Document)** | 原始完整记录与沉淀原文 | 完整日志、对话流水、代码全文、完整技术方案 | 深度调试、长文重构、复杂审查（按需显式升级） | 按需挂载 | 单次会话严格隔离 |

### 不变量约束

1. **L0 First（强制）**：任何 Agent 在初次查询 OpenViking 时，默认必须且仅能拉取 L0 索引，禁止默认全量拉取 L1/L2。
2. **升阶需凭据**：只有当 L0 摘要与当前交互 query 的相关度阈值达标（相关度 ≥ 0.65），或用户显式提及具体上下文时，才允许升阶至对应条目的 L1。
3. **L2 严格受限**：L2 全文读取仅限 dsh（双手）在排查长报错或代码时调用；IM 对话与闲聊层禁止将 L2 原文灌入 prompt。

---

## 2. 渐进召回状态转移流水线

```text
入站 Query / 事件
      │
      ▼
┌─────────────────────────────────┐
│ Step 1: L0 向量 + 关键词混合初筛 │  → 检索目标 namespace 的目录/文档 L0 索引
└────────────────┬────────────────┘
                 │
      相关度得分 ≥ 0.65?
        ├── 否 ──► 忽略或降级为无背景知识，避免无关上下文干扰
        └── 是
                 │
                 ▼
┌─────────────────────────────────┐
│ Step 2: L1 结构化摘要装载       │  → 注入 Agent Prompt (System Prompt / Context)
└────────────────┬────────────────┘
                 │
      是否为复杂深度技术任务?
        ├── 否 ──► 结束，执行生成（保持上下文精简）
        └── 是 (dsh 需要读取完整源码/日志)
                 │
                 ▼
┌─────────────────────────────────┐
│ Step 3: L2 原始文件按需显式读取 │  → 读取目标 URI 完整内容并放入隔离工作区
└─────────────────────────────────┘
```

---

## 3. L0/L1 摘要生成与维护机制

所有沉淀在 OpenViking 的 Markdown 文件统一采用带 YAML Front Matter 的自包含结构：

```markdown
---
id: pref-001
namespace: viking://memories/users/names/preferences.md
type: preference
owner: maibot
created_at: "2026-10-12T08:00:00Z"
updated_at: "2026-10-12T10:30:00Z"
confidence: 0.95
access_count: 14
tags: ["reply_style", "concise", "notification"]
l0_summary: "用户偏好简短直接的回复风格，讨厌长篇说教与客服腔；部署通知要求格式化简报。"
l1_highlights:
  - "偏好：回复控制在 100 字内，口吻自然亲切。"
  - "禁忌：禁止过度道歉、避免说教与格式化客套。"
  - "运维习惯：要求包含服务名、端口与状态的 Markdown 表格。"
---

# 用户偏好详情 (L2 原始内容)

用户多次在群聊中指出：“不要长篇大论，直接说结论就好”。
在 2026-10-10 的部署任务中，用户对详细步骤日志表示冗长，希望仅保留最终 URL 和状态。
...
```

### 自动化生成流

1. **写时提取（Write-time extraction）**：Agent 在写入记忆条目时，必须提供或由 OpenViking 后台管道自动补齐 `l0_summary` 与 `l1_highlights`。
2. **异步合并（Rollup Compaction）**：当目录下的细碎事实文件超过阈值（如单用户单分类文件 > 30 个），OpenViking 后台触发轻量总结任务，重写目录级 `_summary.md`。

---

## 4. 记忆生命周期与置信度衰减 (Lifecycle & Decay)

长周期记忆不是永久静态的，必须引入**时间衰减**与**强化机制**，防止历史陈旧信息干扰最新决策。

### 4.1 置信度计算模型

条目即时置信度 $C(t)$ 定义为：

$$C(t) = \min\left(1.0, \, C_0 \cdot e^{-\lambda \cdot \Delta t} + \alpha \cdot \log(1 + N_{\text{access}})\right)$$

其中：
- $C_0$：初始置信度（系统默认 0.85；用户显式声明或强调的事实为 1.0）。
- $\Delta t$：距离上次确认或更新的天数。
- $\lambda$：衰减因子（按信息类别不同划分）：
  - **静态事实**（姓名、生日、账号）：$\lambda = 0.001$（几乎不衰减）。
  - **习惯偏好**（代码风格、聊天喜好）：$\lambda = 0.01$（半年半衰）。
  - **临时状态与情绪**（疲劳、短期项目关注点）：$\lambda = 0.15$（约 5 天半衰）。
- $N_{\text{access}}$：近期被成功召回并被用户正向确认的次数（强化反馈）。

### 4.2 冲突解决与时序覆盖

当新旧记忆发生矛盾时（例如用户从“喜欢吃辣”变更为“最近戒辣”）：

1. **Recency Overrides History**：时间戳更近且置信度 $C \ge 0.75$ 的条目优先。
2. **软性沉淀而非物理硬删**：旧条目标记 `superseded_by: new-id`，置信度降至 0.2，归档至历史版本区，保留演化轨迹。

### 4.3 遗忘与删除策略（P-07 落实）

- **归档水线（Cold Archive）**：当条目 $C(t) < 0.3$ 且 90 天内无访问，自动移出活跃索引池，仅保留冷存储备份。
- **删除审核流程**：任何 Agent 发起的显式遗忘/清除请求，必须写入 `viking://memories/shared/requests/`，由管理员审核，杜绝 Prompt Injection 诱导 Agent 擦除关键记忆。

---

## 5. OpenViking 接入配置与 Agent Plugins 1.0 片段

各 Agent 统一通过 MCP 协议挂载 OpenViking。以下为标准的 Agent Plugins 1.0 声明片段：

```yaml
# OpenViking Client Configuration for Digital Genesis Agents
mcp_client:
  endpoint: "http://openviking:8080/mcp"
  timeout_seconds: 15
  progressive_context:
    enabled: true
    default_read_level: "L0"
    relevance_threshold_l1: 0.65
    auto_upgrade_l1: true
    allow_l2_upgrade: false   # 仅 dsh 设为 true

tools_exported:
  - name: "openviking_recall"
    description: "从 OpenViking 渐进检索记忆与知识。返回 L0/L1 摘要。"
    parameters:
      query: { type: "string", description: "检索关键词或语义提问" }
      namespaces: { type: "array", items: { type: "string" }, description: "限定的 viking:// 路径" }
      max_level: { type: "string", enum: ["L0", "L1"], default: "L1" }

  - name: "openviking_store"
    description: "向允许写的 OpenViking 命名空间写入或追加记忆。"
    parameters:
      uri: { type: "string", description: "目标 viking:// URI" }
      content: { type: "string", description: "Markdown 格式记忆内容" }
      metadata: { type: "object", description: "tags, type, confidence" }
```

---

## 6. 验收与合规清单

1. **测试集达标**：`evals/memory/cases.jsonl` 中的 50 条测试用例全部符合 L0 优先与命名空间匹配原则。

   > 口径：当前 `evals/memory/predictions.jsonl` 为构造 fixture（正确 URI 固定排第一），上述结论只说明用例与 runner 可运行，不代表真实召回质量。
2. **读权限校验**：所有 Agent 在初筛时未显式指定级别时，默认仅收到 L0 摘要。
3. **元数据完整**：所有沉淀记忆必须携带 `confidence`、`created_at`、`updated_at` 字段。
4. **越权阻断**：禁止任何 Agent 在未经审批的情况下直接物理删除记忆。
