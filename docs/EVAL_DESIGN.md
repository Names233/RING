# 评估集设计

评估集的目标：**防止数字生命“越用越不像”**。没有评估层，人格漂移、记忆召回退化、路由错误都不可感知。

## 1. 三类核心评估

| 评估 | 指标 | 目标 | 频率 |
|---|---|---|---|
| 人格一致性 | 风格得分、语气偏移、梗密度 | 无回归下降 | 每次改 prompt/换模型 |
| 记忆召回准确率 | hit@1, hit@5, MRR | ≥ 85% | 每次改记忆配置 |
| 路由准确率 | accuracy, macro-F1 | ≥ 90% | 每次改路由规则/模型 |

## 1.1 当前实现状态（2026-10-20）

- 三类各 50 条用例，但 routing 类别严重不均衡：tech 43 / chat 4 / embodiment 3，未达到“每类 ≥20”。
- 仓库内 `predictions.jsonl` 是构造 fixture：routing 标签由 `rule_classify` 生成，memory 正确项固定排第一，persona judge_score 全为 4.5。
- 因此下文“判定/阈值”描述的是目标口径；当前 `--baseline` 全绿只能证明 runner 可用，不能证明模型质量。真实评估需接入模型输出与独立标注。

## 2. 人格一致性

### 测试集格式

```json
{
  "id": "persona-001",
  "input": {
    "message": { "role": "user", "parts": [{ "type": "text", "text": "今天好累啊" }] },
    "group_context": { "platform": "qq", "conversation_id": "group:123", "at_me": false }
  },
  "expected_traits": ["empathy", "casual", "no-formality"],
  "forbidden": ["客服腔", "长篇说教", "过度道歉"],
  "difficulty": "easy"
}
```

### 评分方式

1. **规则检查**：forbidden 词命中直接 0 分
2. **LLM-as-judge**：用固定 judge prompt 给 1–5 分，评估语气、风格、自然度
3. **梗密度**：统计回复中的梗/口语标记数量，偏离设定区间扣分

### 判定

- 每条样本 1–5 分
- 全集平均分下降 > 0.5 → 阻断合并
- 单条样本连续 3 次低于 3 分 → 进 badcase 清单

## 3. 记忆召回

### 测试集格式

```json
{
  "id": "memory-001",
  "query": "用户对部署通知有什么偏好？",
  "expected_uris": [
    "viking://memories/users/names/preferences.md"
  ],
  "expected_level": "L1",
  "difficulty": "easy"
}
```

> `expected_uris` 中的 `viking://memories/...` 是逻辑命名空间；与 OpenViking 物理布局的映射见 [`OPENVIKING_PERMISSION_MATRIX.md`](./OPENVIKING_PERMISSION_MATRIX.md) §1.1。

### 指标

- `hit@1`：第一条召回即为正确 URI
- `hit@5`：前五条包含正确 URI
- `MRR`：正确 URI 排名倒数
- `level_match`：召回层级是否与 `expected_level` 一致

### 判定

- `hit@5 < 0.85` → 阻断合并
- `level_match < 0.7` 说明 L0/L1 摘要质量退化，需重新生成目录摘要

## 4. 路由准确率

### 测试集格式

```json
{
  "id": "route-001",
  "text": "帮我部署一下服务",
  "expected_route": "tech",
  "difficulty": "easy"
}
```

### 指标

- 总体 accuracy ≥ 90%
- 每条路由 macro-F1 ≥ 0.85
- 混淆矩阵中 `chat→tech`（人格消息误判为技术）单独跟踪，阈值 ≤ 5%

### 判定

- 任何指标低于阈值 → 阻断合并
- badcase 必须回流到测试集

## 5. 目录结构（建议）

```text
evals/
├── thresholds.yaml          # 指标阈值（文档与代码共用）
├── persona/
│   ├── cases.jsonl
│   ├── predictions.jsonl    # 构造 fixture，非真实模型输出
│   └── judge_prompt.md
├── memory/
│   ├── cases.jsonl
│   └── predictions.jsonl    # 构造 fixture
├── routing/
│   └── cases.jsonl
└── README.md
```

## 6. Langfuse 集成

- 每个 eval run 生成独立 trace
- `trace_id` 与测试样本 `id` 关联
- 失败样本自动打 `eval:failed` tag
- 人格、记忆、路由三个维度分别建 Langfuse dataset

## 7. Runner 与阈值

实现：`scripts/run_evals.py`

```bash
python scripts/run_evals.py routing --baseline --enforce-thresholds
```

- 阈值唯一来源：`evals/thresholds.yaml`
- 支持输出 Markdown / JSON 与 `--output` 报告文件
- `--enforce-thresholds` 失败时非零退出
- persona 支持 P1/P2 契约规则检查；LLM judge 分数可选，缺失时不阻塞
- 使用方式与 fixture 口径详见 `evals/README.md`

## 8. 验收标准

1. 三类测试集各有 ≥ 50 条样本（路由每类 ≥ 20 条）。当前：各 50 条已达成，但 routing 每类 ≥20 未达成（tech 43 / chat 4 / embodiment 3）
2. CI 中可运行离线部分（规则检查、路由正则）
3. LLM judge 部分支持手动/定时触发，不阻塞普通 PR
4. 所有阈值在本文档中定义，代码引用同一份配置
