# 云地混合冗余与高可用设计规范

> 版本：v1.0 (2026-10-22)
> 范围：RING 数字生命云端（Cloud VPS）、边缘（Cloudflare Workers / Edge）与本地（Local PC）的三级高可用拓扑、降级状态机、数据一致性与零信任安全规范。
> 约束：**严禁在本文档及任何衍生配置中写入真实 IP、公网域名、API Token、Tunnel Secret 等敏感信息。所有配置均使用通用占位符（如 `<vps-internal-ip>`、`<cf-tunnel-id>`）。**

---

## 1. 痛点与核心目标

### 1.1 单机本地部署的致命缺陷
在传统全量部署于个人电脑（Local PC）的方案中，系统的生命周期严格受限于宿主机电源：
- **物理断电/关机即“死亡”**：当电脑睡眠、重启或下班关机时，数字生命的感官（AstrBot 无法接收外部 IM 消息）、灵魂（MaiBot 无法回应交流）、化身（AIRI 画面消失）和记忆（OpenViking 服务中断）瞬间全部停摆。
- **外部交流被阻断**：好友或群聊中发送给数字生命的消息得不到任何响应，甚至产生网络超时错误，彻底破坏了其作为“伴随型数字生命”的拟真度和心理安全感。
- **算力与常驻的矛盾**：本地电脑具备高性能 GPU 与本地环境（适合实时渲染 Live2D/VRM、低延迟语音合成、执行复杂桌面与代码任务），但要求其 24/7 不关机既不环保也不现实；而普通低成本云服务器（如 2 核 2GB 内存 VPS）算力受限，无法承担高负载 3D/渲染与庞大本地沙箱。

### 1.2 破局理念：云地混合、分级长生
RING 采用**“云端驻守灵魂与感官，本地承载双手与华服，边缘守护最后防线”**的混合分级架构：
1. **云端长生（Cloud-First Core）**：将轻量级但必须 24/7 常驻的核心组件（AstrBot 感知路由、MaiBot 灵魂对话、OpenViking 核心记忆、LiteLLM 模型网关）常驻于高可用云端 VPS，保障数字生命的“心智”永不下线。
2. **本地增强（Local-Enhanced Embodiment & Hands）**：将高算力、与物理设备强绑定的组件（AIRI 渲染与语音化身、dsh 深度桌面与终端执行）部署于本地 PC。本地在线时开启完整全量体验，本地离线时优雅降级。
3. **边缘兜底（Edge Fallback）**：借助 Cloudflare 边缘全球网络（Cloudflare Workers + KV），在云端基础设施遭遇极端故障或网络抖动时，提供无服务器化的超轻量级保活响应，实现高可用可达性。

---

## 2. 三层拓扑架构与角色划分

```text
 +-----------------------------------------------------------------------+
 | 0. 边缘层 (Edge Tier) - Cloudflare Global Network                     |
 |   - Cloudflare DNS / CDN: 统一流量入口与 Webhook 接入                 |
 |   - Cloudflare Tunnel: 零信任安全通道（无公网暴露端口）               |
 |   - Cloudflare Worker (Failover Proxy): 流量分发与极端情况保活聊天    |
 |   - Cloudflare KV: 缓存轻量级用户画像 (L0/L1) 与紧急降级 Prompt       |
 +------------------+----------------------------------------------------+
                    | 动态路由 (Tunnel / Webhook Forward)
                    v
 +-----------------------------------------------------------------------+
 | 1. 云端驻守节点 (Cloud VPS) - 24/7 常驻基础生命体 (Debian / Linux)    |
 |   - AstrBot (Perception): 18+ 平台消息收发与意图一级路由              |
 |   - MaiBot / Persona Provider: 人格对话、情感引擎、Plan B 兜底        |
 |   - OpenViking (Master): viking:// 虚拟文件系统、记忆库、语义检索     |
 |   - LiteLLM / Model Gateway: 统一模型转发与鉴权路由                   |
 |   - NATS / Event Bus: 核心事件总线与心跳发布                          |
 |   - Heartbeat Monitor: 探测 Local PC 连通性，维护节点状态机           |
 +------------------^----------------------------------------------------+
                    |
                    | WireGuard / Cloudflare Zero Trust Tunnel (加密互联)
                    |
 +------------------v----------------------------------------------------+
 | 2. 本地增强节点 (Local PC) - 按需开启的物理执行与呈现宿主 (Win/macOS) |
 |   - AIRI (Embodiment): Live2D / VRM 高性能渲染、本地 TTS 语音、动作驱动|
 |   - dsh (Hands): DeepSeek Harness 代码执行、本地系统文件与沙箱操作    |
 |   - ACP Bridge: A2A <-> ACP 协议转换                                  |
 |   - Local Replica Cache: 本地 OpenViking 增量快照只读缓存             |
 |   - Agent Heartbeat Daemon: 定时向云端汇报本地在线状态与资源负载      |
 +-----------------------------------------------------------------------+
```

### 2.1 各层职责矩阵

| 层次 | 运行载体 | 运行服务 | 硬件需求 | 停机影响 |
|---|---|---|---|---|
| **边缘层 (Edge)** | Cloudflare Workers + KV + Tunnel | Webhook 分流器、健康检查探测器、Edge Fallback Chat | 无服务器 (Serverless) | 全球任一节点故障由 Cloudflare Anycast 自动容灾 |
| **云端核心 (Cloud)** | 云服务器 (如 AWS Lightsail 2C/2GB) | AstrBot, MaiBot, OpenViking (Master), LiteLLM, NATS | 低配置、低功耗、公网稳定 | 若云端宕机，降级至边缘兜底模式 |
| **本地节点 (Local)** | 个人电脑 (Workstation / Laptop) | AIRI (Live2D/VRM/TTS), dsh (桌面双手), ACP Bridge | 依赖 GPU/显示器/本地终端 | **关机仅损失化身表现与本地执行，对话与记忆无损** |

---

## 3. 三级运行模式与优雅降级矩阵

系统根据本地节点和云端节点的存活状态，自动在三个模式间无缝切换：

### 3.1 运行模式定义

- **模式 A：全量化身模式（Full Embodiment Mode）**
  - **触发条件**：Cloud 正常 + Local PC 在线并持续上报心跳。
  - **表现**：全能力解锁。不仅有即时文字聊天，AIRI 可以在本地窗口展示丰富的表情、动作并发出语音；涉及本地文件编辑或环境调试的指令由 dsh 顺利承接并执行。
- **模式 B：云端长生模式（Cloud Companion Mode）**
  - **触发条件**：Cloud 正常 + Local PC 关机或断网（心跳超时）。
  - **表现**：
    - **闲聊/情感 (chat)**：100% 完整可用。依然由 MaiBot 调用全量 OpenViking 记忆生成充满个性的回复。
    - **表现层 (embodiment)**：优雅降级。AstrBot 路由识别到化身请求时，感知到 AIRI 处于离线状态，自动转交 Persona Provider 生成具有拟人感的情感回复（例如：“我现在不在电脑前（在休息），不过我一直在手机/后台陪着你呀~”），绝不抛出任何错误或断连提示。
    - **技术执行 (tech)**：若指令为云端只读查询或通用推导，由云端轻量代理完成；若指令强依赖本地电脑桌面、本地文件或本地执行环境，系统回复：“我的双手（本地环境）目前在休眠，等主人把电脑开机后我立刻为你执行！”并将任务暂存入待办队列。
- **模式 C：边缘兜底模式（Edge Survival Mode）**
  - **触发条件**：Cloud VPS 因系统维护、重启或网络异常不可达。
  - **表现**：由 Cloudflare Worker 接管入站 Webhook，基于 Edge KV 中缓存的精简人设（Persona Plan B prompt）及高可用模型接口生成暖心安抚回复，保障服务永远不出现“连接超时”。

### 3.2 意图路由降级对照表

| 意图分类 | 模式 A (Local + Cloud 均在线) | 模式 B (Local 关机，Cloud 在线) | 模式 C (Cloud 维护，Edge 兜底) |
|---|---|---|---|
| **chat** (日常聊天、情感交流) | 正常回复 + AIRI 表情联动 | 正常回复（纯文字/移动端语音） | 边缘精简人设回复（纯文字） |
| **embodiment** (动作/表情/视觉) | AIRI 驱动 Live2D 动作与 TTS 播放 | 拟人化降级文本回复（“正在休息中”） | 拟人化安抚回复 |
| **tech (本地环境)** (本地文件/编译) | dsh 完整沙箱执行并汇报 | 任务暂存入待办，友好提示开机后执行 | 暂存待办通知 |
| **tech (通用推导)** (代码审查/架构讨论) | dsh 结合工作区分析 | Persona Provider 结合模型生成解答 | 基础模型解答 |

---

## 4. 心跳检测与状态机演进

### 4.1 心跳探测协议
本地 PC 运行一个轻量级的守护进程（Heartbeat Daemon），通过安全通道向云端 NATS 或专用 HTTP 端点发送心跳包：

```json
// POST /api/v1/heartbeat/local
// Authorization: Bearer <heartbeat-token>
{
  "node_id": "local-workstation-01",
  "timestamp": 1774242000,
  "status": "online",
  "capabilities": ["airi.live2d", "airi.tts", "dsh.code_executor"],
  "metrics": {
    "gpu_load": 0.23,
    "battery_state": "ac_connected"
  }
}
```

### 4.2 状态转移状态机

```text
               Local 心跳正常 (每 15s)
          +----------------------------------+
          |                                  |
          v                                  |
   [ 模式 A: 全量化身 ]                      |
          |                                  |
          | 心跳丢失 > 45s (连续 3 次失败)   | 恢复心跳 (首次成功即唤醒)
          v                                  |
   [ 模式 B: 云端长生 ] ---------------------+
          |
          | Cloud VPS 探针失效 (边缘 Worker 探测超时 > 5s)
          v
   [ 模式 C: 边缘兜底 ]
          |
          | VPS 探针恢复 HTTP 200
          v
   [ 模式 B: 云端长生 ]
```

### 4.3 状态切换时的上下文平滑过渡
1. **本地关机前（主动感知）**：若操作系统触发关机事件，本地守护程序可在关机前发送 `status: "shutting_down"` 的注销心跳，云端即刻将状态机切换为模式 B，无感知等待 45 秒。
2. **本地开机时（无缝回升）**：本地 AIRI 与 dsh 启动就绪后首个心跳到达云端，云端立即向 NATS 发布 `node.local.online` 事件。AstrBot 自动恢复化身与桌面执行路由，并可在下一次对话中自然触发一句：“我回到电脑前啦，现在化身和双手都就绪了！”

---

## 5. 数据一致性与记忆同步设计

为了防止云端与本地出现“记忆分裂”，必须严格坚持**“云端为权威主库（Single Source of Truth），本地为按需投射”**的原则：

### 5.1 记忆分层存储策略

| 数据类别 | 权威节点 | 存储路径 / 形式 | 同步方式 |
|---|---|---|---|
| **长期记忆 (L0/L1/L2)** | 云端 OpenViking | `viking://memories/users/`, `viking://memories/agents/` | 权威持久化在云端挂载磁盘 |
| **短期上下文 (Context Window)** | 云端 AstrBot / MaiBot | Redis 缓存 / 会话窗口 | 内存维持，会话结束后结晶至 OpenViking |
| **化身表现资产 (Assets)** | 本地 PC | Live2D 模型、VRM 文件、语音包、动画缓存 | 静态保存在本地，无需频繁同步 |
| **执行工作区代码 (Worktree)** | 本地 PC (dsh 主场) | 本地工作区目录 | 本地 Git 提交，按需推送至远端托管仓 |

### 5.2 离线期间的记忆补齐流水线
当本地电脑关机、用户在移动端通过云端与数字生命互动后：
1. 产生的所有新对话、情感变化、提取的画像碎片均实时写入**云端 OpenViking** 主库。
2. 当本地电脑重新开机时，本地 dsh 或 AIRI 若需要上下文，通过统一的 OpenViking MCP 客户端直接向云端发起检索或读取最新版本，杜绝本地维护私有数据导致的双向冲突。

---

## 6. 网络互联与零信任安全架构

云地混合架构跨越公网与局域网，必须严格执行零信任原则，**严禁向公网开放危险端口（如数据库、Docker、SSH、ACP 接口）**。

### 6.1 安全连接通道选型
- **方案一：Cloudflare Tunnel（强烈推荐，出站单向建立）**：
  - 云端与本地均通过运行轻量级 `cloudflared` 客户端与 Cloudflare Edge 建立出站 TLS 隧道。
  - **优势**：本地电脑即使处于家庭宽带无公网 IP、多层 NAT 甚至防火墙环境，也能顺畅与边缘和云端互通；云服务器也无需开放任何公网入站端口（关闭所有非必要入站端口）。
- **方案二：WireGuard / Tailscale 内网虚拟局域网**：
  - 在云端 VPS 与本地 PC 之间组建端到端加密的点对点虚拟专网（Overlay Network）。
  - 所有 A2A、ACP 及 MCP 流量严格走内网 IP（如 `10.x.x.x` 或 `100.x.x.x`），公网完全不可见。

### 6.2 敏感信息与凭据管理红线
1. **零硬编码原则**：文档、源码、Compose 模板中绝不允许出现真实的公网 IP、域名、密码、API Key。
2. **环境变量注入**：所有凭据统一由宿主机环境或安全 Secret Manager（如 Cloudflare Secrets, `.env.local`）注入：
   - `MODEL_GATEWAY_KEY`: LiteLLM 主密钥
   - `CF_TUNNEL_TOKEN`: Cloudflare Tunnel 建立凭据
   - `HEARTBEAT_SECRET`: 云地心跳鉴权 Token
3. **最小权限沙箱**：
   - 处于云端的组件无权调用本地执行环境（dsh 不在云端赋予本地 root 权限）。
   - ACP Bridge 仅在本地回环（`127.0.0.1`）或加密隧道中监听，禁止公网访问。

---

## 7. 部署实施与运维指引（脱敏模板）

### 7.1 云端节点部署配置草案（`docker-compose.cloud.yml`）

```yaml
# 运行于云端服务器 (Debian/Linux, 24/7 常驻)
version: "3.8"

services:
  # 统一模型网关
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    restart: always
    environment:
      - MASTER_KEY=${LITELLM_MASTER_KEY}
    volumes:
      - ./config/litellm.yaml:/app/config.yaml:ro

  # 权威记忆主库
  openviking:
    image: volcengine/openviking:latest
    restart: always
    volumes:
      - viking_cloud_data:/data
      - ./config/soul.example.yaml:/app/soul.yaml:ro
    environment:
      - STORAGE_MODE=persistent

  # 感知与一级路由
  astrbot:
    image: soulter/astrbot:latest
    restart: always
    depends_on: [openviking, litellm]
    volumes:
      - astrbot_data:/AstrBot/data
    environment:
      - OPENAI_BASE_URL=http://litellm:4000/v1
      - VIKING_MCP_URL=http://openviking:8080/mcp

  # 灵魂拟人内核
  maibot:
    image: maibot/maisaka:latest
    restart: always
    depends_on: [astrbot, openviking, litellm]
    environment:
      - OPENAI_BASE_URL=http://litellm:4000/v1
      - VIKING_MCP_URL=http://openviking:8080/mcp

  # 零信任隧道连接（避免对外暴露端口）
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: always
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CF_TUNNEL_TOKEN_CLOUD}

volumes:
  viking_cloud_data:
  astrbot_data:
```

### 7.2 本地节点部署配置草案（`docker-compose.local.yml`）

```yaml
# 运行于本地工作站 (按需开机，关机不影响云端)
version: "3.8"

services:
  # 化身层 (Live2D/VRM/TTS)
  airi:
    image: moeru-ai/airi:latest
    ports: ["3000:3000"]
    volumes:
      - ./assets:/AIRI/assets:ro
    environment:
      - VIKING_MCP_URL=${CLOUD_VIKING_TUNNEL_URL}

  # 桌面双手与代码执行
  dsh:
    image: deepseek-ai/dsh:latest
    volumes:
      - /local/workspace:/workspace
    environment:
      - OPENAI_BASE_URL=${CLOUD_LITELLM_TUNNEL_URL}
      - VIKING_MCP_URL=${CLOUD_VIKING_TUNNEL_URL}

  # 协议桥接
  acp-bridge:
    build: ./acp-bridge/
    environment:
      - DSH_ACP_URL=http://dsh:3080

  # 本地心跳上报服务
  heartbeat-daemon:
    build: ./scripts/heartbeat/
    environment:
      - CLOUD_HEARTBEAT_ENDPOINT=${CLOUD_HEARTBEAT_TUNNEL_URL}
      - HEARTBEAT_INTERVAL=15
```

---

## 8. 验收标准与测试用例

1. **心跳失联自动降级测试**：
   - 场景：在系统全量运行（模式 A）时，人为停止本地 PC 的 `heartbeat-daemon`（模拟关机）。
   - 预期结果：45 秒内云端状态机切换为模式 B；向 AstrBot 发送 chat 消息依然秒级返回符合人设的回复；发送 embodiment 请求收到温和的情感文本提示，无 502/超时错误。
2. **心跳唤醒自动恢复测试**：
   - 场景：重启本地 PC 并启动服务。
   - 预期结果：15 秒内首个心跳到达云端，系统升迁为模式 A；后续发送 embodiment 请求能即时触发本地 AIRI 动作与语音。
3. **敏感信息合规性扫描**：
   - 场景：运行敏感信息检测脚本扫描本设计规范及代码库。
   - 预期结果：不包含任何公网 IPv4/IPv6、特定私有凭证字符串、未打码的真实子域名。
