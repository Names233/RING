# Digital Genesis 开发路线图

> 版本：v1（2026-10-12）
> 当前策略：**先文档与代码骨架，后部署**。本文是 `ARCHITECTURE.md` 第八章在工程视角的细化与当前状态追踪。

## 1. 当前位置

```text
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
 (基础设施)  (记忆迁移)   (dsh 换血)   (AstrBot瘦身) (Persona接口化) (化身接入)  (评估闭环)
   ▲
   └ 当前处于 Phase 0 文档与骨架阶段
```

截至 2026-10-12：

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 | 🟡 进行中 | 文档、契约、评估集、测试已就绪；本地部署暂缓 |
| Phase 1 | 🟢 文档先行 | 权限矩阵、迁移脚本、memory eval 已完成 |
| Phase 2 | 🟢 文档先行 | ACP Bridge 参考实现 + 流式映射设计已完成 |
| Phase 3 | 🟢 原型落地 | 路由设计 + 纯函数路由原型 + routing eval 已完成 |
| Phase 4 | 🟢 原型落地 | Persona 契约 + Plan B 设计 + 纯函数原型 + eval 已完成 |
| Phase 5 | 🟢 原型落地 | AIRI 接入设计文档 + 表现层纯函数原型已完成 |
| Phase 6 | 🟡 持续进行 | 三类评估集已建，runner 与 eval-all 聚合入口已实现 |

## 2. Phase 0：基础设施与文档基线

**目标**：在部署前，把所有跨组件接口冻结为文档 + Schema + 测试，避免带病部署。

### 交付物

| 项 | 状态 | 证据 |
|---|---|---|
| v3 架构文档 | ✅ | `ARCHITECTURE.md` |
| 开发流程文档 | ✅ | `DEVELOPMENT.md` |
| 安全与信任模型 | ✅ | `docs/SECURITY_TRUST_MODEL.md` |
| ACP wire schema | ✅ | `docs/ACP_BRIDGE_WIRE_SCHEMA.md` |
| 配置模板与校验 | ✅ | `config/` + `tests/test_config_validation.py` |
| CI | ✅ | `.github/workflows/ci.yml` |
| 文档索引测试 | ✅ | `tests/test_docs.py` |
| 评估 runner | ✅ | `scripts/run_evals.py` + `tests/test_eval_runner.py` |

### 退出标准

1. 所有设计文档进入 README 索引且链接可达。
2. 根目录 + acp-bridge 测试全绿。
3. 所有新增配置字段有校验。
4. 安全模型覆盖 6 类威胁与验收清单。

## 3. Phase 1：记忆层（OpenViking）

### 已完成
- `docs/OPENVIKING_PERMISSION_MATRIX.md`：权限矩阵与 7 条规则。
- `scripts/migrate_mempalace_to_openviking.py`：MemPalace → Markdown 迁移。
- `evals/memory/cases.jsonl`：50 条，覆盖全部 namespace，L0 ≥ 12 条。

### 剩余
- [ ] OpenViking 接入示例（Agent Plugins 1.0 / MCP 配置片段）
- [ ] L0/L1/L2 摘要生成策略文档
- [ ] 记忆生命周期（置信度衰减、删除审核）细化
- [ ] 真实部署联调（暂缓）

### 退出标准
- 权限矩阵可直接转成 OpenViking ACL 配置。
- 迁移脚本幂等且有失败回滚说明。
- Memory eval hit@5 ≥ 85%（接真实系统后）。

## 4. Phase 2：双手（dsh + ACP Bridge）

### 已完成
- ACP Bridge 同步参考实现（FastAPI + JSON-RPC client）。
- `docs/ACP_STREAMING_DESIGN.md`：9 种 sessionUpdate 映射。
- `docs/ACP_BRIDGE_WIRE_SCHEMA.md`：v1 wire 冻结草案。
- 7 个 bridge 测试。
- `streaming.py`：9 种 `sessionUpdate` 纯函数映射 + terminal 一次性语义。
- `session/cancel` RPC 方法与 mock 传输测试。

### 已完成（代码骨架）
- [x] ACP notification 解析（`parse_notification`）
- [x] 9 种 `sessionUpdate` 映射（顺序保持、thought/usage 仅内部）
- [x] terminal 一次性语义测试
- [x] `session/cancel` RPC 方法

### 剩余
- [ ] notification 传输层监听（HTTP/SSE，待真实 dsh）
- [ ] 客户端断开时自动调用 `session/cancel` 的端到端路径
- [ ] dsh 沙箱与命令白名单配置文档
- [ ] 真实 dsh 联调（暂缓）

### 退出标准
- 全部 9 种 `sessionUpdate` 有测试覆盖（已实现：`acp-bridge/tests/test_streaming.py`）。
- 断连后 5 秒内发出 `session/cancel`。
- Bridge 代码不超过"薄层"边界（无业务逻辑、无密钥）。

## 5. Phase 3：AstrBot 路由

### 已完成
- `docs/ASTRBOT_ROUTER_DESIGN.md`：三路由决策树 + 故障降级。
- `evals/routing/cases.jsonl`：12 条初始集。

### 已完成（代码骨架）
- [x] 纯函数路由引擎原型（关键词 + 正则降级路径，`astrbot_router/`）
- [x] confidence < 0.6 降级测试
- [x] eval baseline 与部署降级路径共用同一实现

### 剩余
- [ ] `intent-router` 模型主路径接入
- [x] routing eval 扩展到 ≥ 50 条（已完成：50 条）

### 退出标准
- accuracy ≥ 90%，macro-F1 ≥ 0.85。
- 意图分类器不可用时可完整降级，且降级倾向 `chat`（规则路径已实现并测试）。

## 6. Phase 4：Persona Provider（MaiBot / Plan B）

### 已完成
- `docs/PERSONA_PROVIDER_CONTRACT.md` + 双 Schema + 5 不变量。
- `docs/PERSONA_PLAN_B_DESIGN.md`：两段式流水线。
- `evals/persona/cases.jsonl`：20 条 + judge prompt。

### 已完成（代码骨架）
- [x] Stage 1 JSON 解析 + 静默降级纯函数（`persona_plan_b/core.py`）
- [x] Stage 2 prompt 组装 + 长度约束
- [x] Plan B 输出契约校验（P1/P2 不变量测试覆盖）

### 剩余
- [ ] Plan B 接入 Persona Provider 契约层（A2A 服务化）
- [ ] Plan B 跑 `evals/persona/cases.jsonl` 全集
- [x] persona eval ≥ 50 条（已完成：50 条）

### 退出标准
- Plan B 输出 100% 满足 `persona-provider-response.schema.json`。
- P1 不变量（`should_reply=false` 时 text 为空）有自动化测试。
- 平均分下降 > 0.5 阻断合并的 CI 门禁。

## 7. Phase 5：化身（AIRI）

**已完成（文档）**：
- [x] AIRI ↔ OpenViking 记忆读写设计（`docs/AIRI_EMBODIMENT_DESIGN.md` 第 5 节）
- [x] 事件总线联动场景清单（直播 / 游戏 / 日常，第 7 节）
- [x] MCP 接入配置片段（第 8 节）
- [x] 表现层与 Persona 输出（emotion）映射设计（第 4 节）
- [x] 事件 payload schema（第 6 节）
- [x] 失败降级矩阵（第 9 节）

**已完成（代码骨架）**：
- [x] 表现层纯函数原型（`airi_embodiment/`，emotion 映射 + 资源缺失降级测试）
- [x] A2A embodiment 请求/响应序列化与 NATS 事件生成

**剩余**：
- [ ] 事件 payload JSON Schema 冻结
- [ ] AIRI MCP 凭证与 ACL 配置（暂缓部署）
- [ ] 本地记忆迁移脚本适配 AIRI 目录结构

### 退出标准
- AIRI 不再落本地私有记忆。
- `persona.*` / `embodiment.*` 事件有明确 payload schema。

## 8. Phase 6：评估闭环（持续）

### 已完成
- `docs/EVAL_DESIGN.md`：三类指标与阈值。
- routing 50 / persona 50 / memory 50 初始集（目标 150/150 已达成）。

### 已完成（代码骨架）
- [x] routing accuracy / macro-F1
- [x] memory hit@1 / hit@5 / MRR
- [x] persona 规则检查 + judge prompt 占位
- [x] CI 中运行规则检查，LLM judge 保持本地手动
- [x] eval-all 聚合入口（`run_evals.py all --baseline`）

### 剩余
- [ ] 接真实系统后的阈值达标验证
- [ ] 引入 judge score 离线样例（本地手动跑 LLM judge 后回填）

### 退出标准
- 一条命令产出单维度评估报告（已实现：`scripts/run_evals.py`）。
- 一条命令聚合三类报告（已实现：`python scripts/run_evals.py all --baseline`）。
- 阈值失败时非零退出码，可作合并门禁。

## 9. 风险登记表

| 风险 | 影响 | 缓解 | 当前状态 |
|---|---|---|---|
| A2A 规范变化 | bridge 返工 | wire schema 标注"冻结草案"，v2 预留 stream 参数 | 🟡 受控 |
| dsh API 变化 | Phase 2 阻塞 | 契约集中在 wire schema，单一改动点 | 🟢 低 |
| MaiBot 停更 | 人格能力退化 | Persona Provider 接口 + Plan B | 🟢 已缓解 |
| 评估集过小 | 指标不稳定 | 目标各 50 条；当前已完成 150/150 | 🟢 已缓解 |
| AGPL/GPL 边界 | 合规风险 | 独立进程 + 网络协议交互，不链接代码 | 🟢 已隔离 |
| Prompt injection | 执行安全 | 安全模型 T1 防线 + 沙箱 | 🟡 文档已定，实现待做 |

## 10. 里程碑口径

本文所有"已完成"均指：**文档 / 契约 / 代码骨架 / 测试在仓库中存在且可验证**，不包含本地部署验证。涉及真实系统联调的项均显式标注"暂缓"。
