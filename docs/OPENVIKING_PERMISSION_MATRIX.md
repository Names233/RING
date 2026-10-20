# OpenViking 权限矩阵

OpenViking 是所有 Agent 的记忆与知识总线。权限规则：**写隔离、读按需**，防止某个 Agent 覆盖其他 Agent 的经历。

## 1. Namespace 总览

| Namespace | 内容 | 归属 |
|---|---|---|
| `viking://resources/` | 项目文档、代码仓库、网页 | 全局只读资源 |
| `viking://memories/users/` | 用户画像、偏好、事实 | Persona Provider 写入 |
| `viking://memories/agents/` | 各 Agent 经历与任务历史 | Agent 各自写 |
| `viking://memories/shared/` | 跨 Agent 共享上下文 | 管理员维护 |
| `viking://skills/` | 沉淀的工作流与经验 | dsh 写，其他读 |

### 1.1 逻辑命名空间 ↔ OpenViking 物理布局

上表与各设计文档中的 `viking://memories/...`、`viking://skills/` 是**逻辑命名空间**，用于表达归属与 ACL 意图；OpenViking 实际可写根为 `viking://resources/`、`viking://user/{user_id}/`、`viking://agent/`，技能安装目录为 `viking://agent/skills/`（账号共享）或 `viking://~/skills/`（个人）。映射建议如下，落地 Phase 1 时需逐条验证：

| 逻辑路径 | 物理布局（建议） | 说明 |
|---|---|---|
| `viking://resources/` | `viking://resources/` 或 `viking://~/resources/` | 全局共享 / 个人资源；默认只读 |
| `viking://memories/users/{user}/` | `viking://user/{user_id}/memories/` | 用户画像；`skills/`、`peers/`、`privacy/`、`sessions/` 为保留子树，勿写入 |
| `viking://memories/agents/{agent}/` | `viking://agent/memories/{agent}/` | Agent 经历，写隔离 |
| `viking://memories/shared/` | `viking://resources/shared/` | 账号共享，写入需 manage 权限 |
| `viking://skills/` | `viking://agent/skills/` 或 `viking://~/skills/` | 技能包；应通过 skill 安装流程写入，而非普通文件写 |

> 当前仓库尚未实现该映射，也没有 ACL 配置文件；本文与代码中的逻辑路径不能直接用于 OpenViking 请求。

## 2. Agent × Namespace × 权限

读（R）/ 写（W）/ 无权限（-）

| Agent | `resources/` | `memories/users/` | `memories/agents/{self}/` | `memories/agents/{other}/` | `memories/shared/` | `skills/` |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| AstrBot | R | R/W | R/W (`astrbot/`) | R | R | R |
| MaiBot | R | R/W | R/W (`maibot/`) | R | R | R |
| AIRI | R | R | R/W (`airi/`) | R | R | R |
| dsh | R | R | R/W (`dsh/`) | R | W | R/W |
| Bridge | R | R | - | - | - | - |

## 3. 规则

1. **P-01 写隔离**：Agent 只能写 `memories/agents/{self}/`，禁止写其他 Agent 目录。
2. **P-02 用户画像双写者**：`memories/users/` 仅 AstrBot 与 Persona Provider 可写；AstrBot 写平台事实（昵称、群角色），Persona Provider 写表达学习成果。
3. **P-03 技能沉淀**：任务工作流由 dsh 写入 `skills/`，格式为 Markdown + front matter，供所有 Agent 复用。
4. **P-04 共享记忆管理员制**：`memories/shared/` 不允许 Agent 自动写入，防止共享区被污染。
5. **P-05 Bridge 只读**：ACP↔A2A bridge 仅读取资源用于上下文，不产生记忆。
6. **P-06 L0/L1/L2 读取**：所有读操作优先 L0，需要时升级到 L1/L2，禁止一次性拉取全文。
7. **P-07 删除策略**：Agent 不能直接删除记忆；删除请求写入 `memories/shared/requests/`，由管理员审核。

## 4. 落地方式

| 阶段 | 动作 |
|---|---|
| Phase 1 | 将本矩阵同步到 OpenViking ACL 配置 |
| Phase 2 | 在集成测试中验证：dsh 写 `memories/users/` 必须失败 |
| Phase 3 | 在 Langfuse 中记录越权拒绝事件 |

## 5. 验收标准

1. 每个 Agent 的 MCP 凭证权限与本矩阵一致。
2. 集成测试覆盖至少 P-01、P-02、P-05 三条规则的拒绝路径。
3. 权限变更必须同时更新本文档和 OpenViking ACL 配置。
