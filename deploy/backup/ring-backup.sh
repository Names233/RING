#!/usr/bin/env bash
# RING 备份：tar + gpg AES256 对称加密 + WebDAV 上传 + 远端保留策略。
#
# 环境变量（compose 已注入，也可直接 docker run 传）：
#   RING_DATA_DIR            数据根（默认 /data，只读挂载）
#   BACKUP_PATHS             空格分隔的相对路径（默认 "openviking maibot napcat/config caddy"）
#   BACKUP_SPOOL_DIR         本地产物目录（默认 /var/backups/ring，保留最近 2 份）
#   BACKUP_PASSPHRASE_FILE   GPG 口令文件（必须存在，建议 600）
#   BACKUP_KEEP              远端保留份数（默认 14，按文件名时间戳倒序）
#   DAV_BASE/DAV_USER/DAV_PASS   WebDAV 目录与凭据；DAV_BASE 为空则只备份到本地
#
# 退出码：0 成功；2 配置/环境问题；1 备份或上传失败。
set -euo pipefail
umask 077

DATA_DIR="${RING_DATA_DIR:-/data}"
SPOOL="${BACKUP_SPOOL_DIR:-/var/backups/ring}"
PASSFILE="${BACKUP_PASSPHRASE_FILE:-/run/secrets/backup_passphrase}"
PATHS_RAW="${BACKUP_PATHS:-openviking maibot napcat/config caddy}"
KEEP="${BACKUP_KEEP:-14}"
DAV_BASE="${DAV_BASE:-}"
DAV_BASE="${DAV_BASE%/}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="ring-backup-${STAMP}.tar.gz.gpg"
OUT="${SPOOL}/${NAME}"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

[ -r "$PASSFILE" ] || { log "FAILED: 口令文件不可读: $PASSFILE"; exit 2; }
[ -d "$DATA_DIR" ] || { log "FAILED: 数据目录不存在: $DATA_DIR"; exit 2; }
mkdir -p "$SPOOL"

paths=()
for p in $PATHS_RAW; do
    if [ -e "${DATA_DIR}/${p}" ]; then
        paths+=("$p")
    else
        log "note: ${DATA_DIR}/${p} 不存在，跳过"
    fi
done
if [ "${#paths[@]}" -eq 0 ]; then
    log "FAILED: 没有任何可备份路径（检查 BACKUP_PATHS）"
    exit 2
fi

log "打包: ${paths[*]}"
tar -C "$DATA_DIR" \
    --exclude='backup/passphrase' \
    --exclude='backup/spool' \
    --exclude='*/logs/*' \
    --exclude='*/__pycache__' \
    --exclude='*/node_modules' \
    --use-compress-program='gzip -6' \
    -cf - "${paths[@]}" \
  | gpg --batch --yes --quiet --pinentry-mode loopback \
        --passphrase-file "$PASSFILE" \
        --symmetric --cipher-algo AES256 --s2k-digest-algo SHA512 \
        -o "$OUT"

( cd "$SPOOL" && sha256sum "$NAME" > "${NAME}.sha256" )
SIZE="$(stat -c %s "$OUT")"
log "本地产物: $OUT (${SIZE} bytes)"

if [ -n "$DAV_BASE" ]; then
    : "${DAV_USER:?已设置 DAV_BASE 但 DAV_USER 为空}"
    : "${DAV_PASS:?已设置 DAV_BASE 但 DAV_PASS 为空}"

    log "上传到 $DAV_BASE/"
    for f in "${SPOOL}/${NAME}" "${SPOOL}/${NAME}.sha256"; do
        curl -fsS --show-error --retry 3 --retry-delay 10 --retry-all-errors --max-time 900 \
            -u "${DAV_USER}:${DAV_PASS}" -T "$f" "${DAV_BASE}/$(basename "$f")"
    done

    remote_len="$(curl -fsSI --retry 3 --retry-all-errors --max-time 60 \
        -u "${DAV_USER}:${DAV_PASS}" "${DAV_BASE}/${NAME}" \
        | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}' | tail -n1)"
    if [ -n "$remote_len" ] && [ "$remote_len" != "$SIZE" ]; then
        log "FAILED: 远端大小 ${remote_len} != 本地 ${SIZE}"
        exit 1
    fi
    log "回验通过: 远端 content-length=${remote_len:-unknown}"

    if command -v python3 >/dev/null 2>&1; then
        DAV_BASE="$DAV_BASE" DAV_USER="$DAV_USER" DAV_PASS="$DAV_PASS" BACKUP_KEEP="$KEEP" \
            python3 /usr/local/bin/retention.py || log "WARN: 远端保留策略失败（不影响本次备份成功）"
    fi
else
    log "未配置 DAV_BASE：本次只写本地 spool"
fi

# 本地 spool 只保留最近 2 份
if [ -d "$SPOOL" ]; then
    find "$SPOOL" -maxdepth 1 -type f -name 'ring-backup-*.tar.gz.gpg' -printf '%T@ %p\n' \
        | sort -rn | awk 'NR>2{print $2}' | while read -r old; do
            rm -f "$old" "${old}.sha256"
        done
fi

log "=== ring-backup OK: $NAME ==="
