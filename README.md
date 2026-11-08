# RING

> **MaiBot × ring_router × AIRI × dsh × OpenViking — 融合架构 v3**
>
> MaiBot 是入口与灵魂，ring_router 是一级路由，AIRI 是化身，dsh 是双手，OpenViking 是记忆
> —— 创世，让数字生命降临。

## 核心理念

| 维度 | 负责者 | 说明 |
|------|--------|------|
| **怎么说** (Personality) | MaiBot | 人格、语气、情感、氛围感知（可替换 Persona Provider） |
| **怎么表现** (Embodiment) | AIRI | 视觉形象、语音、动画、游戏 |
| **怎么听/说** (Perception) | MaiBot | QQ/TG 接入（SnowLuma 适配器）、消息收发、会话状态与动态触发 |
| **怎么分派** (Routing) | ring_router | 一级意图路由：闲聊 / 人格 / 技术 / 化身，均只监听回环 |
| **怎么做到** (Execution) | dsh | 技术执行、代码、部署、运维、调研、沙箱 |
| **怎么记** (Memory) | OpenViking | 上下文总线（`viking://` 虚拟文件系统）、L0/L1/L2 渐进召回 |

## 上游项目

| 项目 | Star | 语言 | License | 核心能力 |
|------|------|------|---------|----------|
| [dsh](https://github.com/deepseek-ai/deepseek-harness) | 255.6k | TypeScript | MIT | Cordis 微内核执行体，原生 ACP，40+ 插件包 |
| [AIRI](https://github.com/moeru-ai/airi) | 50.5k | TypeScript | MIT | 数字化身，Live2D/VRM，本地 TTS，游戏，多端 |
| [OpenViking](https://github.com/volcengine/OpenViking) | 40.4k | Python+Rust | AGPL-3.0 | 上下文数据库，`viking://` 虚拟文件系统，L0/L1/L2 分层 |
| [MaiBot](https://github.com/Mai-with-u/MaiBot) | 6.3k | Python | GPL-3.0 | 拟人化数字生命，动态触发聊天，可替换 Persona Provider |

> Star 数据为 2026-10-20 核查值；四个上游仓库的 License 已逐一核对。
>
> **2026-11-08 变更**：原方案中的 AstrBot（感知与投递层，AGPL-3.0）已从架构移除，云端容器停用并卸载；其"入口与投递"职责由 MaiBot 承担，"一级路由"职责由自研 `ring_router` 承担。详见 [RING 一级路由服务设计](./docs/RING_ROUTER_DESIGN.md)。

## 架构总览

采用 **MCP + A2A + ACP 三协议**分层：

```
MCP  → Agent ↔ 工具/记忆（OpenViking Agent Plugins 1.0）
HTTP → MaiBot ↔ ring_router（一级路由 /route、心跳 /heartbeat）
A2A  → ring_router ↔ MaiBot / AIRI / persona_plan_b（对等协作）
ACP  → ring_router ↔ dsh（双手执行，经薄适配器）
```

```
用户 (QQ / TG)
  │
  ▼
MaiBot (入口与灵魂) ── 平台接入 / 会话 / 默认人格对话
  │  HTTP /route
  ▼
ring_router (一级路由, 127.0.0.1:18082)
  ├── MaiBot 自答          ── 闲聊 / 人格（默认灵魂）
  ├── persona_plan_b ── A2A ── 可切换的灵魂实现（18081）
  ├── AIRI (化身)     ── A2A ── 视觉/语音/游戏
  └── dsh (双手)      ── ACP ── 技术执行（经 ACP bridge，Headless，沙箱隔离）

OpenViking (记忆, 1933) ── 各 Agent 以 MCP/Agent Plugins 直连
```

> 当前只做 QQ + TG；Discord / 飞书 / 钉钉 / WebChat 明确不在本期范围，未来若需要另立接入层。

**横切层**：LiteLLM 模型网关 + Langfuse 可观测性 + NATS 事件总线

## 当前状态（2026-11-08）

本仓库处于 **代码骨架 + 云端单节点试点** 阶段。四个上游项目以独立服务方式集成，本仓库不 vendor 其代码。**云端已跑通**：MaiBot（systemd）+ NapCat + OpenViking + `ring-cloud.service`（18080/18081/18082 三服务）；**未完成**：MaiBot 侧调用路由、dsh/AIRI 上云、群聊真实流量。

- **可本地验证**（2026-11-08 实测）：根目录 `pytest` 145 passed、`python config/validate.py` 通过；`acp-bridge` 29 passed 与 `scripts/run_evals.py all --baseline` 为 2026-10-20 记录，本次未复跑。
- **评估口径**：离线评估的 predictions 是仓库内构造的 fixture；routing 标签由同一套 `rule_classify` 生成，因此“基线 100%”只证明回归一致，不代表真实模型质量。
- **已知缺口**：ACP Bridge 同步路径拿不到 ACP 执行正文（`session/update` 未接入），dsh 的真实 ACP 传输未核实；OpenViking 文档中的 `viking://memories/...` 是逻辑命名空间，与物理布局的映射见 [权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md)。
- **CI**：最近 9 次 run 连续失败（依赖缺失 + eval gate 矩阵条件），本地等价命令全绿；根因与修复见 [DEVELOPMENT.md](./DEVELOPMENT.md#ci)。
- **License**：本仓库代码为 MIT（见 [LICENSE](./LICENSE)）；`patches/maibot-openviking/` 因衍生自 MaiBot 而按 GPL-3.0 发布；上游组件的许可证与分发义务见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。

完整缺口清单与待办见 [DEVELOPMENT.md](./DEVELOPMENT.md)。

## v2 → v3 变更摘要

| 变更 | 说明 |
|------|------|
| Hermes → **dsh** | Cordis 微内核，原生 ACP，与 OpenViking 官方插件互通 |
| MemPalace → **OpenViking** | `viking://` 虚拟文件系统 + L0/L1/L2 渐进召回，杜绝 Token 爆炸 |
| AstrBot **移除** | 2026-11-08 决议：撤出 AstrBot，容器停用卸载。入口归 MaiBot，一级路由归自研 `ring_router`（18082，仅回环），执行权仍全交 dsh |
| MaiBot **接口化** | 抽象为可替换 Persona Provider，存储下沉至 OpenViking |
| 协议 +**ACP** | 编码执行体事实标准，薄适配器桥接 A2A |
| +**模型网关** | LiteLLM/NewAPI 统一路由、成本控制、故障转移 |
| +**可观测性** | Langfuse 全链路 trace + 人格一致性/记忆召回评估集 |
| +**事件总线** | NATS/Redis Streams 解决广播型场景 |

## 详细设计

👉 [ARCHITECTURE.md](./ARCHITECTURE.md)

## 工程状态与开发流程

👉 [DEVELOPMENT.md](./DEVELOPMENT.md)：仓库结构、ACP↔A2A bridge、配置校验、记忆迁移、CI 与待办清单。

## 设计文档索引

- [架构总览](./ARCHITECTURE.md)
- [开发状态与流程](./DEVELOPMENT.md)
- [Persona Provider 契约](./docs/PERSONA_PROVIDER_CONTRACT.md)
- [OpenViking 权限矩阵](./docs/OPENVIKING_PERMISSION_MATRIX.md)
- [OpenViking 渐进上下文与记忆生命周期策略](./docs/OPENVIKING_CONTEXT_STRATEGY.md)
- [RING 一级路由服务设计](./docs/RING_ROUTER_DESIGN.md)
- [评估集设计](./docs/EVAL_DESIGN.md)
- [ACP 流式事件映射设计](./docs/ACP_STREAMING_DESIGN.md)
- [Persona Plan B 设计](./docs/PERSONA_PLAN_B_DESIGN.md)
- [安全与信任模型](./docs/SECURITY_TRUST_MODEL.md)
- [ACP Bridge Wire Schema](./docs/ACP_BRIDGE_WIRE_SCHEMA.md)
- [AIRI 化身层接入设计](./docs/AIRI_EMBODIMENT_DESIGN.md)
- [开发路线图](./docs/DEVELOPMENT_ROADMAP.md)
- [云地混合冗余与高可用设计](./docs/HYBRID_REDUNDANCY_DESIGN.md)
- [MaiBot 集成研究](./docs/MAIBOT_INTEGRATION_STUDY.md)
- [方案审计报告与缺陷清单](./docs/ARCHITECTURE_AUDIT_AND_DEFECTS_2026.md)
- [评估集说明与运行方式](./evals/README.md)
- [ACP Bridge 运行说明](./acp-bridge/README.md)
- [Persona judge prompt](./evals/persona/judge_prompt.md)
