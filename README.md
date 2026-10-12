# Digital Genesis

> **AstrBot × MaiBot × AIRI × dsh × OpenViking — 五合一融合架构 v3**
>
> MaiBot 是灵魂，AIRI 是化身，AstrBot 是耳目，dsh 是双手，OpenViking 是记忆
> —— 创世，让数字生命降临。

## 核心理念

| 维度 | 负责者 | 说明 |
|------|--------|------|
| **怎么说** (Personality) | MaiBot | 人格、语气、情感、氛围感知（可替换 Persona Provider） |
| **怎么表现** (Embodiment) | AIRI | 视觉形象、语音、动画、游戏 |
| **怎么听/说** (Perception) | AstrBot | 18+ 平台接入、意图路由、消息收发（瘦身后） |
| **怎么做到** (Execution) | dsh | 技术执行、代码、部署、运维、调研、沙箱 |
| **怎么记** (Memory) | OpenViking | 上下文总线（`viking://` 虚拟文件系统）、L0/L1/L2 渐进召回 |

## 五大项目

| 项目 | Star | 语言 | License | 核心能力 |
|------|------|------|---------|----------|
| [dsh](https://github.com/deepseek-ai/deepseek-harness) | 247.8k | TypeScript | MIT | Cordis 微内核执行体，原生 ACP，40+ 插件包 |
| [AIRI](https://github.com/moeru-ai/airi) | 50.0k | TypeScript | MIT | 数字化身，Live2D/VRM，本地 TTS，游戏，多端 |
| [AstrBot](https://github.com/AstrBotDevs/AstrBot) | 41.4k | Python | AGPL-3.0 | 感知与投递层，18+ 平台，意图路由，消息增强插件 |
| [OpenViking](https://github.com/volcengine/OpenViking) | 39.7k | Python+Rust | AGPL-3.0 | 上下文数据库，`viking://` 虚拟文件系统，L0/L1/L2 分层 |
| [MaiBot](https://github.com/Mai-with-u/MaiBot) | 6.1k | Python | GPL-3.0 | 拟人化数字生命，动态触发聊天，可替换 Persona Provider |

> Star 数据为 2026-10-12 实时核查值。

## 架构总览

采用 **MCP + A2A + ACP 三协议**分层：

```
MCP  → Agent ↔ 工具/记忆（OpenViking Agent Plugins 1.0）
A2A  → AstrBot ↔ MaiBot / AIRI（对等协作）
ACP  → AstrBot ↔ dsh（双手执行，经薄适配器）
```

```
用户 (QQ/微信/TG/Discord/直播/Web)
  │
  ▼
AstrBot (耳目) ── 平台接入 / 意图路由 / 消息收发
  ├── MaiBot (灵魂)  ── A2A ── 人格化回复（Persona Provider）
  ├── AIRI (化身)    ── A2A ── 视觉/语音/游戏
  ├── dsh (双手)     ── ACP ── 技术执行（Headless，沙箱隔离）
  └── OpenViking (记忆) ── 各 Agent 以 MCP/Agent Plugins 直连
```

**横切层**：LiteLLM 模型网关 + Langfuse 可观测性 + NATS 事件总线

## v2 → v3 变更摘要

| 变更 | 说明 |
|------|------|
| Hermes → **dsh** | Cordis 微内核，原生 ACP，与 OpenViking 官方插件互通 |
| MemPalace → **OpenViking** | `viking://` 虚拟文件系统 + L0/L1/L2 渐进召回，杜绝 Token 爆炸 |
| AstrBot **瘦身** | 退守感知与投递层，执行权全交 dsh，杜绝双调度器 |
| MaiBot **接口化** | 抽象为可替换 Persona Provider，存储下沉至 OpenViking |
| 协议 +**ACP** | 编码执行体事实标准，薄适配器桥接 A2A |
| +**模型网关** | LiteLLM/NewAPI 统一路由、成本控制、故障转移 |
| +**可观测性** | Langfuse 全链路 trace + 人格一致性/记忆召回评估集 |
| +**事件总线** | NATS/Redis Streams 解决广播型场景 |

## 详细设计

👉 [ARCHITECTURE.md](./ARCHITECTURE.md)
