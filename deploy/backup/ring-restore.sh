#!/usr/bin/env bash
# RING 恢复：把一份 .tar.gz.gpg 解到指定目录（默认 /restore），供人工比对后再覆盖。
#
# 用法：ring-restore.sh <archive.tar.gz.gpg> [输出目录]
# 安全：只做解密 + 解包，不写 /data，不动任何服务。
set -euo pipefail
umask 077

ARCHIVE="${1:?用法: ring-restore.sh <archive.tar.gz.gpg> [输出目录]}"
OUT="${2:-/restore}"
PASSFILE="${BACKUP_PASSPHRASE_FILE:-/run/secrets/backup_passphrase}"
TMP_TGZ="$(mktemp /tmp/ring-restore-XXXXXX.tar.gz)"

cleanup() { rm -f "$TMP_TGZ"; }
trap cleanup EXIT

[ -r "$ARCHIVE" ] || { echo "归档不可读: $ARCHIVE" >&2; exit 2; }
[ -r "$PASSFILE" ] || { echo "口令文件不可读: $PASSFILE" >&2; exit 2; }

echo "[restore] 解密 $ARCHIVE"
gpg --batch --yes --quiet --pinentry-mode loopback \
    --passphrase-file "$PASSFILE" \
    --decrypt --output "$TMP_TGZ" "$ARCHIVE"

echo "[restore] 解包到 $OUT"
mkdir -p "$OUT"
tar -xzf "$TMP_TGZ" -C "$OUT"

echo "[restore] 完成。请先核对内容，再停服务、按需覆盖："
echo "  docker compose --profile core stop maibot openviking"
echo "  sudo rsync -a --delete $OUT/openviking/ <RING_DATA_DIR>/openviking/"
