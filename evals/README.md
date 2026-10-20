# Digital Genesis 评估集

本目录存放离线评估集、评估阈值与评估 runner。设计目标与指标解释见 [`docs/EVAL_DESIGN.md`](../docs/EVAL_DESIGN.md)。

## 当前状态

| 维度 | 状态 | 样本数 | 说明 |
|---|---|---:|---|
| routing | 🟡 完整集 + runner（标签同源） | 50 | tech 43 / chat 4 / embodiment 3；baseline 用同一 `rule_classify` 生成标签，仅证明回归一致 |
| persona | 🟡 回归 fixture（非真实模型） | 50 | predictions 为手写响应，P1/P2/forbidden 规则可执行；judge_score 统一为 4.5，不是真实评分 |
| memory | 🟡 构造 fixture | 50 | 正确 URI 被人工放在第 1 位，hit@5 100% 是构造结果，不是真实召回 |

## 预测文件口径（重要）

仓库内的 `evals/*/predictions.jsonl` 是**构造的回归 fixture**，不是真实模型调用结果：

| 维度 | 当前预测来源 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| routing | 与 labels 同一套 `rule_classify` 生成 | 规则改动未破坏原有回归 | 真实意图分类准确率 |
| memory | 按 expected URI 人工构造，正确项恒排第一 | runner 指标计算正确 | 真实召回质量 |
| persona | 手写响应 + 统一 `judge_score: 4.5` | P1/P2/forbidden 规则可执行 | 真实人格一致性与模型评分 |

接入真实系统后，应改用模型输出重跑，并区分 fixture 与 model 两种口径。

## 阈值配置

所有阈值集中在 [`thresholds.yaml`](./thresholds.yaml)，文档与代码引用同一份配置：

```yaml
routing:
  accuracy: 0.90
  macro_f1: 0.85
  chat_to_tech_rate: 0.05
memory:
  hit_at_5: 0.85
  level_match: 0.70
persona:
  minimum_average_judge_score: 3.0
```

## 运行评估

### Routing 基线（无需模型）

```bash
python scripts/run_evals.py routing --baseline
```

输出 accuracy、macro-F1、chat→tech 误路由率、混淆矩阵与 badcase。

### Routing 真实预测

```bash
python scripts/run_evals.py routing --predictions path/to/predictions.jsonl
```

预测格式：

```json
{"id": "route-001", "route": "tech"}
```

### Memory 召回

```bash
python scripts/run_evals.py memory --predictions path/to/predictions.jsonl
```

预测格式（最多 5 条，按相关性排序）：

```json
{
  "id": "memory-001",
  "retrieved": [
    {"uri": "viking://memories/users/names/preferences.md", "level": "L1"}
  ]
}
```

输出 hit@1、hit@5、MRR、level_match 与 badcase。

> 示例中的 `viking://memories/...` 是逻辑命名空间；与 OpenViking 物理布局的映射见 [`docs/OPENVIKING_PERMISSION_MATRIX.md`](../docs/OPENVIKING_PERMISSION_MATRIX.md) §1.1。

### Persona 规则检查

```bash
python scripts/run_evals.py persona --predictions path/to/responses.jsonl
```

响应格式：

```json
{
  "id": "persona-001",
  "response": {"should_reply": true, "text": "抱抱，先歇会儿~", "emotion": "happy"},
  "judge_score": 4.5
}
```

输出 P1/P2 契约违规率、forbidden 命中与平均 judge 分。`judge_score` 可省略；省略时平均分显示为 pending，不阻塞规则检查。

### 阈值门禁

加 `--enforce-thresholds` 后，任何阈值失败以非零退出，可直接接入 CI 或合并门禁：

```bash
python scripts/run_evals.py routing --baseline --enforce-thresholds
```

### 聚合报告（eval-all）

一条命令聚合 routing / memory / persona 三类报告：

```bash
python scripts/run_evals.py all --baseline
```

预测文件查找顺序：

1. `--predictions` 显式指定
2. `--output` 报告文件的同目录同名前缀（`report.json` → `report.memory.jsonl` / `report.persona.jsonl`）
3. `evals/{kind}/predictions.jsonl`

某个维度的预测 id 集合与 cases 不完全匹配时会跳过该维度，输出 `skipped`，避免误报。

### 报告输出

- `--format json`：机器可读 JSON
- `--format markdown`：默认，人类可读 Markdown
- `--output path/to/report.md`：写入文件（自动创建目录）

## 格式

所有测试集统一为 JSONL，每行一个独立样本。字段必须包含 `id`，且全目录唯一。

## 添加样本

1. 按 `docs/EVAL_DESIGN.md` 中的格式添加样本
2. 运行测试：`pytest -q`
3. badcase 回流时保留原 `id`，追加 `difficulty: hard`
4. runner 对 `id` 重复、非法枚举值、缺失 text part 直接报错，避免静默通过
