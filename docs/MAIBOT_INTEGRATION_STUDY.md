# MaiBot 集成研究（原「MaiBot 剔除与人格层重构探究」）

> 版本：v2（2026-11-08 修订）
> 原文件名 `MAIBOT_REPLACEMENT_STUDY.md`（2026-10-22）已更名为 `MAIBOT_INTEGRATION_STUDY.md`：MaiBot 没有被剔除，反而成了系统的唯一入口。
> **2026-11-08 决议**：AstrBot 已从方案移除（云端容器停用并卸载）。本文中出现的 AstrBot 字样**仅作为历史记录保留**，每处均标注其移除状态。
> 本文分两部分：§2–§4 是**历史决策记录**（当初为什么想剔除 MaiBot、当时的评估与调研）；§5–§8 是**当前现实**（MaiBot 保留为入口、persona_plan_b 作为可切换的灵魂实现）。

## 1. 结论先行

| 问题 | 当前答案 |
|---|---|
| MaiBot 还剔除吗？ | **不剔除**。MaiBot 是唯一消息入口（QQ via SnowLuma/OneBot + NapCat）与对话主体 |
| 谁做一级路由？ | **ring_router**（自研，`127.0.0.1:18082`），由 MaiBot 以 HTTP 调用 |
| persona_plan_b 还有用吗？ | **有**。保留为可切换的灵魂实现（A2A Persona Provider，`127.0.0.1:18081`），可直接替换"人格生成"这一段而不动入口 |
| AstrBot 呢？ | **已移除**（2026-11-08 停用并卸载容器），其"感知与投递"职责由 MaiBot 承担，"一级路由"职责由 ring_router 承担 |
| 平台范围 | **QQ + TG**。Discord / 飞书 / 钉钉 / WebChat 当前不做，需要时另立接入层 |

一句话：**入口归 MaiBot，路由归 ring_router，灵魂可换（MaiBot 原生人格 ↔ persona_plan_b），双手归 dsh（ACP bridge），化身归 AIRI，记忆归 OpenViking。**

## 2. 历史决策记录（2026-10-22）

> 本节保留原调研的判定与论据，供追溯决策链。**其中的结论已被 2026-11-08 决议部分推翻**，原因是原判定低估了 MaiBot 作为"入口"的不可替代性，也高估了自研灵魂替换的成熟度。

### 2.1 历史选型背景

在 RING v1/v2 早期（"五合一"体系：感知层 × MaiBot × AIRI × dsh/Hermes × OpenViking；其中感知层组件 AstrBot **已于 2026-11-08 移除**），MaiBot 被定性为"灵魂层（Persona Provider）"。当时选型 MaiBot 的核心价值在于：

1. **群聊动态插话（Passive Triggering）**：在不被显式 `@` 或带指令前缀的情况下，通过内置启发式/语义规则自主判断"这句话该不该接、什么时候插话"。
2. **群聊表达习惯学习（Expression Learning）**：从目标群聊中持续学习口癖、黑话和用词风格。
3. **社交好感度**：维系与不同成员的社交关系与情感倾向。

### 2.2 当时的痛点判定

随着架构向 v3 演进，当时判定 MaiBot 从"不可替代的灵魂"变成整个系统中最薄弱、摩擦最大的短板：

| 痛点维度 | 当时的判定 | 影响程度 |
|---|---|---|
| **开源许可证冲突** | GPL-3.0 强传染性：dsh 为 MIT，OpenViking 为 AGPL-3.0，MaiBot 的 GPL-3.0 给商业友好度、下游分发与模块集成带来法律摩擦 | 致命 |
| **社区活跃度与停更风险** | MaiBot 全网体量最小（~6.1k★），核心维护停滞，迭代周期不可控 | 高危 |
| **架构冗余与资源浪费** | 独立 Python 进程 + 独立 Web 服务 + 私有 SQLite，占 300MB~500MB 内存，对 2C/2GB VPS 是浪费 | 严重 |
| **违背"无状态灵魂"原则** | 自带私有表达库导致数据分散，阻碍记忆与画像的全局统一检索 | 架构不符 |
| **能力稀释与技术代差** | 早期学习算法是弱算力时期的妥协；主流 LLM + Few-shot + 角色卡已可超越其拟真度 | 质变 |

> **审计更正（见 `ARCHITECTURE_AUDIT_AND_DEFECTS_2026.md` §5 P2-1）**：上表的法律定性（"致命传染"）与内存占用（"300MB~500MB"）缺乏法理与实测依据，应修正为"降低单一依赖组件的许可证合规管理成本"。本节保留原文以记录决策链，不作为当前结论。

### 2.3 当时的结论与其后的反转

当时结论：*"剔除 MaiBot 不仅完全可行，而且是系统轻量化、去 GPL 化和架构归一化的必然选择"*，并推荐"方案 B：自研 persona_plan_b 无缝替换 maibot 容器"。

**2026-11-08 反转的原因**：

1. **入口价值被低估**：MaiBot 自带成熟适配器（SnowLuma/OneBot → NapCat）、会话管理、主动插话与表达学习。剔除它意味着要自研一整套 IM 接入与拟人调度，成本远高于替换"人格生成"这一段。
2. **替换粒度错了**：真正该抽象的是**灵魂生成**（Persona Provider 契约），而不是整个 MaiBot 进程。persona_plan_b 恰恰只实现了前者。
3. **资源账算反了**：把"少一个进程"当成收益，但入口进程是刚需——省不掉，还要新写。
4. **合规可以隔离**：GPL-3.0 组件以独立进程 + 网络协议（HTTP/OneBot）交互，不链接、不内联，即可与 MIT 自研代码分层管理。

## 3. 历史附录：已移除的感知层方案（AstrBot）人格能力评测

> 本节是 2026-10-22 对被评估对象"感知层框架自身能不能承载人格"的评测记录。**该对象已于 2026-11-08 从方案移除并卸载容器**，因此本节的方法论可借鉴（如何评估一个人格载体），但对象本身不再参与选型。

### 3.1 原生人格管理机制（历史）

被评估对象内部具备一套角色预设引擎：`prompt`（System Prompt 注入）、`name`（角色标识）、`begin_dialogs`（开场白）、`tools/skills`（人格级工具权限）、`custom_error_message`（人格化异常回复）；支持按平台/群/私聊绑定人格预设（UMO 路由）与指令切换人格；在消息流水线的 `process_stage` 中拼装 LLM 对话模板。

### 3.2 生态插件对人格塑造的赋能（历史）

当时列举的代表插件：自主学习插件（黑话挖掘、Few-shot 审查、好感度）、主动对话插件（上下文感知破冰、动态情绪）、拟人化生活伴侣插件（作息表、虚拟日记）。**这些插件能力至今未被移植**——它们对应的能力现在要么由 MaiBot 原生提供，要么由 OpenViking 记忆 + persona_plan_b 的 prompt 侧近似。

### 3.3 当时的唯一差距与解决路径（历史）

差距：原生"唤醒检查阶段"只支持显式唤醒（被 `@`、引用回复、`wake_prefix` 前缀、私聊白名单），不含"小模型判断该不该插话"的动态唤醒流水线。当时给的两条路径（插件拦截全局消息 / 两段式 `should_reply` 判定）**均未落地**，随对象移除而作废。

## 4. 业界优秀开源人格与角色扮演项目调研

本节结论**仍然有效**，是 persona_plan_b 后续演进与人格资产化的输入。

| 项目 | Star / 活跃度 | 核心特长 | 适合在 RING 中的定位 | 引入成本 |
|---|---|---|---|---|
| **SillyTavern Character Card V2 规范** | 极高（AI 角色扮演事实标准） | 二次元/拟人角色卡生态（Chub.ai 等）；标准化 `char_persona`、`world_scenario`、`mes_example` | **数字生命人设的通用资产包格式**（免手写 prompt，直接导入角色卡） | 极低（仅需 JSON/PNG 规范解析器） |
| **ElizaOS (ai16z/eliza)** | 15k+★ | 工业级 `Characterfile` 规范（bio, lore, messageExamples, style, adjectives）；自驱叙事与社交人格一致性 | 人格规范设计范式 | 中高（TS 运行时，不建议双引擎并行） |
| **ChatHaruhi（凉宫春日）** | 2.5k+★ | 基于剧本/经典台词抽取的 RAG 角色拟真，台词召回还原傲娇/温柔/毒舌 | **OpenViking 中的语料库检索模板**（台词存入 `viking://memories/persona/examples/`） | 极低（与 OpenViking 契合） |
| **Mem0 / Letta (MemGPT)** | 25k+★ | 自主自省式记忆演化（Self-Editing Persona Memory） | 动态演化策略参考 | 极低（OpenViking 已具备等价能力） |
| **RING 自研 `persona_plan_b`** | 本地代码库已内置 | 满足 `PERSONA_PROVIDER_CONTRACT.md` 契约，两段式（触发判断 + 主模型生成），纯 Python、MIT | **可切换的灵魂实现**（见 §6） | 零（现成代码） |

## 5. 当前现实：MaiBot 作为唯一入口与对话主体

### 5.1 部署形态

| 项 | 事实 |
|---|---|
| 进程形态 | systemd unit `ring-maibot.service`（非容器） |
| 端口 | `8000` maim_message（消息总线）/ `8001` WebUI |
| QQ 适配 | 已装 **SnowLuma** 适配器，连 NapCat（QT QQ `3890037770`，OneBot WS `127.0.0.1:3001`） |
| 平台范围 | QQ + TG（TG 待接）；Discord / 飞书 / 钉钉 / WebChat 当前不做 |
| 记忆钩子 | site-packages 注入的 OpenViking 读写钩子：**injector**（回复前召回）+ **writer**（边聊边记）。该修改**未入版本控制**，正在抽成 `patches/maibot-openviking/`（含 `install.py`、两个钩子模块与 3 个 mount patch） |
| 真实流量 | **尚无群聊流量**：QQ 号不在任何群，仅 2 个好友（2026-11-08 现状） |
| 路由调用 | 尚未在消息链路调用 ring_router `/route`（待接，见 `RING_ROUTER_DESIGN.md` §7） |

### 5.2 为什么保留（取舍）

| 维度 | 保留 MaiBot 的收益 | 代价 / 风险 | 结论 |
|---|---|---|---|
| IM 接入 | SnowLuma/OneBot 适配器开箱即用，含重连、群/私聊区分、@ 与引用解析 | 需随 NapCat 协议变动维护 | 入口刚需，保留 |
| 拟人调度 | 原生动态插话、表达学习、沉默判定 | 具体行为**未经真实群聊验证**（无群流量） | 保留并验证 |
| 人格生成 | 已成型，且可用 OpenViking 钩子注入记忆 | 人格资产与 MaiBot 的 prompt 结构绑定 | 保留，但**生成段可通过 Persona Provider 契约替换** |
| 许可与合规 | 独立进程、网络协议调用，GPL-3.0 不污染 MIT 自研代码 | 分发形态需守住"进程隔离"边界 | 可接受 |
| 数据留存 | OpenViking 为权威记忆，MaiBot 私有库降级为运行时缓存 | 私有 SQLite 与 OpenViking 存在双写不一致风险 | 需治理（见 §5.3） |

### 5.3 风险与缓解

| 风险 | 缓解 | 状态 |
|---|---|---|
| 停更导致人格能力无法维护 | Persona Provider 契约 + persona_plan_b 可切换（§6） | 🟢 契约已冻结，Plan B 可运行 |
| GPL-3.0 传染 | 独立进程 + HTTP/OneBot 交互，不链接、不内联；`LICENSE` 分发边界待补 | 🟡 仓库仍缺 LICENSE |
| 记忆双写不一致 | OpenViking 为权威源；MaiBot 侧钩子写入需带 `source`/`writer_agent`/`confidence` front matter | 🔴 钩子未入版本控制，一致性未验证 |
| 钩子随 site-packages 漂移 | 抽成 `patches/maibot-openviking/`（三个 mount patch + 安装脚本），可重放 | 🟡 抽取中 |
| 无真实群流量 | 先以好友私聊 + 自建测试群验证动态插话与 @ 唤醒 | ⏳ 未开始 |

## 6. persona_plan_b 的定位与取舍

### 6.1 两者对照

| 维度 | MaiBot（默认灵魂） | persona_plan_b（可切换灵魂） |
|---|---|---|
| 入口能力 | ✅ 自带适配器与会话 | ❌ 只有 A2A 端点，需由 ring_router/MaiBot 转发 |
| 人格生成 | ✅ 成熟 prompt 体系 + 表达学习 | 🟡 两段式：Stage 1 触发判断 → Stage 2 主模型生成 |
| 记忆 | OpenViking 钩子（injector/writer） | 走 MCP 渐进召回（L0/L1），不落本地 |
| 许可 | GPL-3.0 | MIT（自研） |
| 模型接入 | 走 AGT 网关 | 走 AGT 网关（`ring_common.llm_client.AGTClient`，`gemini-3.8-flash`） |
| 契约 | 需适配 Persona Provider 契约 | ✅ 原生实现 `PERSONA_PROVIDER_CONTRACT.md` |
| 成熟度 | 高（真实可用，已部署） | 中（服务化 + 单测通过；**未在真实流量下试跑**） |

### 6.2 切换判据

1. **默认走 MaiBot**：入口、会话、投递都在 MaiBot，人格生成用它最省事。
2. **切到 persona_plan_b 的条件**：MaiBot 停更/不可用，或需要"契约化、可观测、可评测"的人格生成（A2A + JSON Schema + eval 门禁）。
3. **切换成本**：ring_router 的 `chat` 下游地址一条环境变量（`PERSONA_PROVIDER_URL`），不改入口、不改协议。
4. **不建议现在切换**：真实流量为零，替换后无法对比效果；审计建议先做**影子运行**（Shadow Mode）对比两者输出，再决定是否切主。

## 7. 三套演进方案的现状

| 原方案 | 内容 | 2026-11-08 状态 |
|---|---|---|
| **方案 A** | 由已移除的感知层框架内部承载人格 + 插件生态 | ❌ **作废**：该对象已从方案移除并卸载，插件路径不可用 |
| **方案 B** | 自研 `persona_plan_b` 无缝替换 MaiBot 容器 | 🟡 **部分采纳**：作为可切换的灵魂实现保留，**不再替换入口**；已服务化（A2A）并接 AGT 网关 |
| **方案 C** | SillyTavern Character Card V2 + OpenViking 台词 RAG | ⏳ **暂缓**：在人格生成段稳定、有真实流量前不引入额外检索组件（审计 ADR 第 3 条） |

## 8. 综合决策与当前路线

**决策（2026-11-08）**：MaiBot 保留为唯一入口与对话主体；persona_plan_b 保留为可切换的灵魂实现；一级路由独立为 ring_router；被移除的感知层方案不再回归。

当前路线：

1. **入口打通**：MaiBot 在消息链路上调用 ring_router `/route`，把 `chat/tech/embodiment` 判定真正接进流量（当前最大缺口）。
2. **记忆归一**：把 `patches/maibot-openviking/` 固化为可重放安装流程，确保 MaiBot 写入带 front matter，并与权限矩阵对齐。
3. **真实流量**：先自建测试群跑通 @ 唤醒与动态插话，再谈拟真度调优。
4. **灵魂可换**：用影子模式对比 MaiBot 与 persona_plan_b 的输出，达标后再讨论主备切换。
5. **人格资产化**：需要更强表现力时，按方案 C 引入 Character Card V2 + 台词 RAG，但以"生成段可替换"为前提。
