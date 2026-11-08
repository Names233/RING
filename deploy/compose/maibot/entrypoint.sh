#!/bin/sh
# RING MaiBot 容器入口：首次启动自动初始化实例，然后把实例目录交给 maibot run。
#
# 实例目录通过 MAIBOT_INSTANCE_DIR 指定（compose 里挂到 ${RING_DATA_DIR}/maibot）。
# 首次启动会执行 `maibot init` 生成 bot_config.toml / model_config.toml，
# 随后由 prepare_instance.py 把监听地址改成容器内可达的 0.0.0.0，并生成
# data/openviking.json（OpenViking 读写钩子的配置）。
set -eu

INSTANCE_DIR="${MAIBOT_INSTANCE_DIR:-/app/maibot}"
mkdir -p "$INSTANCE_DIR"

if [ ! -f "$INSTANCE_DIR/config/bot_config.toml" ] || [ ! -f "$INSTANCE_DIR/config/model_config.toml" ]; then
    echo "[ring] 首次启动：初始化 MaiBot 实例 $INSTANCE_DIR"
    maibot init --directory "$INSTANCE_DIR"
fi

python /usr/local/bin/prepare_instance.py "$INSTANCE_DIR"

exec maibot run --directory "$INSTANCE_DIR"
