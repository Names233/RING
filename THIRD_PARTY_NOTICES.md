# 第三方组件与许可证声明（THIRD PARTY NOTICES）

本仓库自身的代码以 [MIT](./LICENSE) 发布。系统在运行时**集成但不内嵌**下列第三方组件——它们由使用者自行拉取官方发行版，本仓库只提供编排（Docker Compose / Ansible）与集成代码。

## 一、运行时依赖

| 组件 | 版本（验证基线） | 许可证 | 引入方式 | 我们对它做了什么 |
|---|---|---|---|---|
| [MaiBot](https://github.com/Mai-with-u/MaiBot) | 1.3.19 | **GPL-3.0** | 用户 pip install maibot==1.3.19 或官方镜像 | 运行时注入两个模块（读侧/写侧）并 patch 三个位置；补丁源码见 patches/maibot-openviking/，**按 GPL-3.0 发布** |
| [OpenViking](https://github.com/volcengine/OpenViking) | 0.5.3 | **AGPL-3.0** | 用户自行安装 / 官方镜像 | 仅通过 HTTP API 与 viking:// 命名空间调用，**未修改其源码** |
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ) / [NapCat-Docker](https://github.com/NapNeko/NapCat-Docker) | 4.18.42（镜像 latest） | **NOASSERTION**（上游自定义许可；Docker 镜像未声明 SPDX） | 用户自行拉取官方镜像 | 未修改，仅通过 OneBot v11 WebSocket 通信 |
| SnowLuma 适配器 | 线上 2026-11 版本 | **上游未提供 LICENSE 文件**（默认保留一切权利） | 用户在 MaiBot WebUI 中自行安装 | **本仓库不分发插件本体**；patches/snowluma-adapter/ 仅为可选的 diff 与复现脚本 |
| [Caddy](https://github.com/caddyserver/caddy) | 2.11.7 | Apache-2.0 | 官方 apt 仓库 / 镜像 | 仅提供站点配置模板 |
| [AIRI](https://github.com/moeru-ai/airi) | — | MIT | 可选，未上线 | 仅设计文档 |
| [dsh](https://github.com/deepseek-ai/deepseek-harness) | — | MIT | 可选，未上云 | 仅 ACP 桥接设计 |
| LiteLLM / NewAPI / OpenList | — | MIT / 见上游 | 可选 | 仅作为模型网关与备份目的地的说明 |

> 版本号是我们在 2026-11-08 实机核对过的值；上游随时可能变更许可证，分发前请自行复核。

## 二、分发义务（自托管分发模式）

本项目采用**路线 A：自托管分发**——我们把编排与自研层开源，使用者在自己的机器上部署。这种形态下：

1. **MaiBot（GPL-3.0）**
   - 我们不打包它的代码，但 patches/maibot-openviking/ 是对它的修改，属于衍生作品 → 该目录以 GPL-3.0 发布（见 LICENSE 的 Exception 段）。
   - 如果你分发**包含 MaiBot 的镜像**，必须同时提供 MaiBot 完整源码与你的修改（本仓库已公开补丁，满足条件）。
   - 如果你只是部署在**自己的服务器**上，GPL 的分发义务不触发。

2. **OpenViking（AGPL-3.0）**
   - 我们**没有修改**它的源码，因此不需要发布任何 OV 补丁。
   - 但 AGPL §13：若你把 OV 作为网络服务提供给他人使用，必须向这些使用者提供对应源码（指向上游发行版即可）。对外暴露 ov. 域名时请注意这一条。

3. **NapCat（自定义许可 / NOASSERTION）**
   - QQ 协议端许可不明确，**不要随产品分发**。让使用者自行拉取官方镜像，并在文档中说明风险自担。

4. **SnowLuma 适配器等 MaiBot 插件**
   - 上游未声明许可证 = 保留一切权利。**本仓库与任何发行物都不得打包插件本体**，只能由使用者在 WebUI 中自行安装。
   - patches/snowluma-adapter/ 只包含我们自己的 diff 与验证脚本。

5. **本仓库自研部分（MIT）**
   - ring_router/、persona_plan_b/、openviking_service/、ring_common/、airi_embodiment/、acp-bridge/、scripts/、deploy/、docs/ 均为 MIT。
   - 你可以闭源分发这些部分的衍生服务，但改了 patches/maibot-openviking/ 就必须按 GPL 公开。

## 三、我们不做的事

- 不分发 QQ 客户端、不绕过腾讯的服务条款；
- 不内嵌任何上游的模型权重或商业 API 密钥；
- 不在镜像里打包无许可证的第三方插件。

## 四、报告许可证问题

如果你认为本仓库的某个文件侵犯了你的权利，请开 issue 说明文件路径与依据，我们会在 7 天内移除或替换。
