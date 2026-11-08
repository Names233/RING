#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# RING 交互式首装脚本（Docker Compose 路径）
#
#   ./ring-init.sh            交互式：生成 .env 与随机密钥、建目录、渲染配置，最后启动 core
#   ./ring-init.sh --yes      全部用默认值 + 已有环境变量（适合无人值守/重装）
#   ./ring-init.sh --no-up    只准备配置，不启动容器
#   ./ring-init.sh --force    覆盖已有 .env（旧的备份为 .env.bak.<时间戳>）
#
# 生成的目录结构（RING_DATA_DIR，默认 ./data）：
#   data/openviking/ov.conf            记忆库配置（含 root_api_key，0600）
#   data/openviking/workspace records  记忆数据
#   data/maibot/                       MaiBot 配置/数据库/插件
#   data/napcat/{config,qq}            QQ 协议端配置与登录态
#   data/caddy/{Caddyfile,data}        反代站点与证书
#   data/backup/{passphrase,spool}     备份口令与本地留存
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

ASK_YES=0
DO_UP=1
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASK_YES=1 ;;
    --no-up) DO_UP=0 ;;
    --force|-f) FORCE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed -e 's/^# {0,1}//'
      exit 0
      ;;
    *) echo "未知参数: $arg（--yes / --no-up / --force）" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then
  C_INFO=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_INFO=''; C_WARN=''; C_ERR=''; C_OFF=''
fi
info() { printf '%s==>%s %s\n' "$C_INFO" "$C_OFF" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
die()  { printf '%s[x]%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }

ask() {
  # ask <变量名> <提示> <默认值> [secret]
  local __var="$1" __prompt="$2" __default="$3" __secret="${4:-}" __ans=""
  if [ "$ASK_YES" = "1" ]; then
    printf -v "$__var" '%s' "$__default"
    return 0
  fi
  if [ -n "$__secret" ] && [ -n "$__default" ]; then
    printf '%s [******]: ' "$__prompt"
  else
    printf '%s [%s]: ' "$__prompt" "$__default"
  fi
  IFS= read -r __ans || true
  [ -z "$__ans" ] && __ans="$__default"
  printf -v "$__var" '%s' "$__ans"
}

gen_hex() { openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
gen_pass() { openssl rand -base64 32 2>/dev/null | tr -d '\n' || head -c 32 /dev/urandom | base64 | tr -d '\n='; }

# ---------------------------------------------------------------------------
# 1. 环境检查
# ---------------------------------------------------------------------------
info "检查 docker / compose"
command -v docker >/dev/null 2>&1 || die "未找到 docker。请先安装 Docker Engine 24+ 与 compose v2 插件：https://docs.docker.com/engine/install/"

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
  warn "检测到旧版 docker-compose（v1），建议改装 compose v2 插件"
else
  die "未找到 compose。Debian/Ubuntu: apt install docker-compose-plugin；或参考 deploy/README.md 的故障排查"
fi

if ! docker info >/dev/null 2>&1; then
  die "当前用户无法访问 docker daemon：请用 sudo 运行，或把用户加入 docker 组后重新登录（usermod -aG docker $USER）"
fi
info "docker: $(docker --version)"
info "compose: $($COMPOSE version --short 2>/dev/null || $COMPOSE version | head -n1)"

# ---------------------------------------------------------------------------
# 2. 已有配置处理
# ---------------------------------------------------------------------------
if [ -f .env ]; then
  if [ "$FORCE" = "1" ]; then
    bak=".env.bak.$(date +%Y%m%d%H%M%S)"
    cp .env "$bak"
    warn "已备份旧 .env 到 $bak"
  else
    warn ".env 已存在。要改配置请直接编辑它；要重新生成请加 --force"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# 3. 采集配置
# ---------------------------------------------------------------------------
echo
info "基础配置（回车使用方括号里的默认值）"
ask RING_DATA_DIR "数据目录（绝对路径或相对本目录）" "./data"
ask TZ_VALUE "时区" "Asia/Shanghai"

echo
info "对外域名（edge profile 用；暂不反代可以留默认）"
ask OV_DOMAIN "OpenViking 域名" "ov.example.com"
ask MB_DOMAIN "MaiBot WebUI 域名" "mb.example.com"
ask ACME_EMAIL "Let's Encrypt 邮箱（可空）" ""

echo
info "模型网关（ring-cloud 调用的 OpenAI 兼容接口）"
ask AGT_BASE_URL "AGT_BASE_URL（宿主机网关用 host.docker.internal）" "http://host.docker.internal:8045/v1"
ask AGT_API_KEY "AGT_API_KEY（密钥，可空=离线模式）" "" secret
ask AGT_MODEL "对话模型名" "gemini-3.8-flash"

echo
info "OpenViking 的向量化 / 重排 / 视觉模型（OpenAI 兼容）"
ask OV_EMBEDDING_API_BASE "embedding api_base" "https://your-embedding-endpoint/v1"
ask OV_EMBEDDING_MODEL "embedding 模型名" "qwen3-text-embedding"
ask OV_EMBEDDING_API_KEY "embedding api_key" "" secret
ask OV_EMBEDDING_DIMENSION "embedding 维度" "1024"
ask OV_RERANK_API_BASE "rerank api_base" "https://your-rerank-endpoint/api/v1/services/rerank/text-rerank"
ask OV_RERANK_MODEL "rerank 模型名" "qwen3-text-rerank"
ask OV_RERANK_API_KEY "rerank api_key（可与 embedding 相同）" "" secret
ask OV_VLM_API_BASE "vlm api_base" "https://your-vlm-endpoint/v1"
ask OV_VLM_MODEL "vlm 模型名" "gemini-3.8-flash"
ask OV_VLM_API_KEY "vlm api_key（可与 embedding 相同）" "" secret

echo
info "备份（可跳过，之后编辑 data/backup/backup.env 也能补）"
ask DAV_BASE "WebDAV 地址（空=只备份到本地 spool）" ""
if [ -n "$DAV_BASE" ]; then
  ask DAV_USER "WebDAV 用户名" ""
  ask DAV_PASS "WebDAV 密码" "" secret
else
  DAV_USER=""
  DAV_PASS=""
fi

for v in "$OV_EMBEDDING_API_KEY" "$OV_RERANK_API_KEY" "$OV_VLM_API_KEY" "$AGT_API_KEY" "$OV_EMBEDDING_MODEL"; do
  case "$v" in
    *'&'*|*'|'*) die "配置值里不能包含 & 或 |（会破坏模板渲染），请换一个值" ;;
  esac
done

# ---------------------------------------------------------------------------
# 4. 生成随机密钥
# ---------------------------------------------------------------------------
OV_ROOT_API_KEY="$(gen_hex)"
OV_USER_API_KEY="$OV_ROOT_API_KEY"
HEARTBEAT_SECRET_TOKEN="$(gen_hex)"
BACKUP_PASSPHRASE="$(gen_pass)"

# ---------------------------------------------------------------------------
# 5. 建目录
# ---------------------------------------------------------------------------
info "创建数据目录：$RING_DATA_DIR"
mkdir -p "$RING_DATA_DIR"/{openviking/workspace,openviking/records,maibot,napcat/config,napcat/qq,caddy/data,caddy/config,backup/spool}
chmod 700 "$RING_DATA_DIR/backup"
umask 077
printf '%s\n' "$BACKUP_PASSPHRASE" > "$RING_DATA_DIR/backup/passphrase"
chmod 600 "$RING_DATA_DIR/backup/passphrase"

# ---------------------------------------------------------------------------
# 6. 渲染配置
# ---------------------------------------------------------------------------
info "渲染 openviking/ov.conf"
sed -e "s|__OV_ROOT_API_KEY__|$OV_ROOT_API_KEY|g" \
    -e "s|__OV_EMBEDDING_MODEL__|$OV_EMBEDDING_MODEL|g" \
    -e "s|__OV_EMBEDDING_API_KEY__|$OV_EMBEDDING_API_KEY|g" \
    -e "s|__OV_EMBEDDING_API_BASE__|$OV_EMBEDDING_API_BASE|g" \
    -e "s|__OV_EMBEDDING_DIMENSION__|$OV_EMBEDDING_DIMENSION|g" \
    -e "s|__OV_RERANK_MODEL__|$OV_RERANK_MODEL|g" \
    -e "s|__OV_RERANK_API_KEY__|$OV_RERANK_API_KEY|g" \
    -e "s|__OV_RERANK_API_BASE__|$OV_RERANK_API_BASE|g" \
    -e "s|__OV_RERANK_THRESHOLD__|0.1|g" \
    -e "s|__OV_VLM_MODEL__|$OV_VLM_MODEL|g" \
    -e "s|__OV_VLM_API_KEY__|$OV_VLM_API_KEY|g" \
    -e "s|__OV_VLM_API_BASE__|$OV_VLM_API_BASE|g" \
    -e "s|__OV_VLM_TEMPERATURE__|0.0|g" \
    -e "s|__OV_VLM_MAX_TOKENS__|4096|g" \
    config/ov.conf.tmpl > "$RING_DATA_DIR/openviking/ov.conf"
chmod 600 "$RING_DATA_DIR/openviking/ov.conf"
grep -q '__OV_' "$RING_DATA_DIR/openviking/ov.conf" && die "ov.conf 仍有未替换的占位符"

info "渲染 backup/backup.env"
sed -e "s|__DAV_BASE__|$DAV_BASE|g" \
    -e "s|__DAV_USER__|$DAV_USER|g" \
    -e "s|__DAV_PASS__|$DAV_PASS|g" \
    config/backup.env.tmpl > "$RING_DATA_DIR/backup/backup.env"
chmod 600 "$RING_DATA_DIR/backup/backup.env"

info "放置 caddy/Caddyfile"
if [ ! -f "$RING_DATA_DIR/caddy/Caddyfile" ]; then
  cp config/Caddyfile.tmpl "$RING_DATA_DIR/caddy/Caddyfile"
fi

# ---------------------------------------------------------------------------
# 7. 写 .env
# ---------------------------------------------------------------------------
info "写入 .env"
{
  echo "# 由 ring-init.sh 于 $(date -u '+%Y-%m-%dT%H:%M:%SZ') 生成；请勿提交到 Git"
  echo "TZ=$TZ_VALUE"
  echo "RING_DATA_DIR=$RING_DATA_DIR"
  echo
  echo "OV_DOMAIN=$OV_DOMAIN"
  echo "MB_DOMAIN=$MB_DOMAIN"
  echo "ACME_EMAIL=$ACME_EMAIL"
  echo
  echo "MAIBOT_VERSION=1.3.19"
  echo "OPENVIKING_VERSION=0.5.3"
  echo
  echo "OV_ROOT_API_KEY=$OV_ROOT_API_KEY"
  echo "OV_USER_API_KEY=$OV_USER_API_KEY"
  echo "OV_EMBEDDING_MODEL=$OV_EMBEDDING_MODEL"
  echo "OV_EMBEDDING_API_KEY=$OV_EMBEDDING_API_KEY"
  echo "OV_EMBEDDING_API_BASE=$OV_EMBEDDING_API_BASE"
  echo "OV_EMBEDDING_DIMENSION=$OV_EMBEDDING_DIMENSION"
  echo "OV_RERANK_MODEL=$OV_RERANK_MODEL"
  echo "OV_RERANK_API_KEY=$OV_RERANK_API_KEY"
  echo "OV_RERANK_API_BASE=$OV_RERANK_API_BASE"
  echo "OV_RERANK_THRESHOLD=0.1"
  echo "OV_VLM_MODEL=$OV_VLM_MODEL"
  echo "OV_VLM_API_KEY=$OV_VLM_API_KEY"
  echo "OV_VLM_API_BASE=$OV_VLM_API_BASE"
  echo "OV_VLM_TEMPERATURE=0.0"
  echo "OV_VLM_MAX_TOKENS=4096"
  echo
  echo "OPENVIKING_BASE_URL=http://openviking:1933"
  echo "OPENVIKING_API_KEY_FILE="
  echo "RING_OV_CONFIG_FORCE=0"
  echo
  echo "HEARTBEAT_SECRET_TOKEN=$HEARTBEAT_SECRET_TOKEN"
  echo "AGT_BASE_URL=$AGT_BASE_URL"
  echo "AGT_API_KEY=$AGT_API_KEY"
  echo "AGT_MODEL=$AGT_MODEL"
  echo "AGT_TIMEOUT_SECONDS=20.0"
  echo "RING_OFFLINE_MODE=0"
  echo
  echo "NAPCAT_UID=$(id -u)"
  echo "NAPCAT_GID=$(id -g)"
  echo
  echo 'BACKUP_PATHS="openviking maibot napcat/config caddy"'
  echo "BACKUP_KEEP=14"
  echo "DAV_BASE=$DAV_BASE"
  echo "DAV_USER=$DAV_USER"
  echo "DAV_PASS=$DAV_PASS"
} > .env
chmod 600 .env

info "配置完成：$HERE/.env（0600），数据目录 $RING_DATA_DIR"
if grep -q '__CHANGE_ME__' .env; then
  warn ".env 里还有 __CHANGE_ME__ 占位符，请补上真实值后再 up"
fi

# ---------------------------------------------------------------------------
# 8. 启动
# ---------------------------------------------------------------------------
if [ "$DO_UP" = "1" ]; then
  echo
  info "构建并启动 core（openviking + maibot + napcat），首次构建约 10-20 分钟"
  if [ "$ASK_YES" = "0" ]; then
    ask GO "现在开始构建并启动？[Y/n]" "Y"
    case "$GO" in
      [nN]*) DO_UP=0 ;;
    esac
  fi
fi

if [ "$DO_UP" = "1" ]; then
  $COMPOSE -f docker-compose.yml --env-file .env --profile core up -d --build
  echo
  info "已启动。查看状态：./ringctl ps ；跟踪日志：./ringctl logs"
else
  info "已跳过启动。手动启动：$COMPOSE -f docker-compose.yml --profile core up -d --build"
fi

cat <<'NEXT'

-------------------------------------------------------------------
下一步：让机器人真的能说话

1) QQ 登录（NapCat WebUI，一次即可）
   本机没暴露 6099 到公网，用 SSH 隧道：
     ssh -L 6099:127.0.0.1:6099 <user>@<server>
   浏览器打开 http://127.0.0.1:6099 ，用 QQ 扫码登录。
   首次启动会在 data/napcat/config/ 下生成 webui.json（含 token），
   同时生成 onebot11_<QQ号>.json：
     - WebSocket 服务端：0.0.0.0:3001，token 自己设一个
     - 消息格式：array

2) 把同一个 token 写进 MaiBot 的 QQ 适配器配置
   data/maibot/plugins/maibot-team_snowluma-adapter/config.toml
     [client]
     client_type = "napcat"
     server = "napcat"        # 容器内用服务名，不能写 127.0.0.1
     port = 3001
     token = "<上一步的 token>"
   改完 ./ringctl restart maibot

3) 配置 MaiBot 的模型（对话本体）
   data/maibot/config/model_config.toml —— 按里面的注释填 provider / api_key / model

4) 检查
   ./ringctl doctor
   curl -s http://127.0.0.1:1933/health     # 记忆库
   curl -s http://127.0.0.1:8001/           # WebUI
   在群里 @机器人 说一句话，看到回复即成功。

5) 想加反代 + HTTPS：编辑 .env 的 OV_DOMAIN/MB_DOMAIN，然后
   $COMPOSE --profile edge up -d
-------------------------------------------------------------------
NEXT
