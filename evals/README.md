# Digital Genesis 评估集

本目录存放离线评估集。设计目标与指标阈值见 [`docs/EVAL_DESIGN.md`](../docs/EVAL_DESIGN.md)。

## 当前状态

| 维度 | 状态 | 样本数 | 说明 |
|---|---|---:|---|
| routing | ✅ 初始集 | 12 | 三类路由全覆盖，easy/medium 混合 |
| persona | ✅ 初始集 | 20 | 含 judge prompt，easy/medium/hard 全覆盖 |
| memory | 🟡 待扩充 | 0 | 需要真实 OpenViking URI 后补充 |

## 格式

所有测试集统一为 JSONL，每行一个独立样本。字段必须包含 `id`，且全目录唯一。

## 添加样本

1. 按 `docs/EVAL_DESIGN.md` 中的格式添加样本
2. 运行测试：`pytest -q tests/test_evals.py`
3. badcase 回流时保留原 `id`，追加 `difficulty: hard`
