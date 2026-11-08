# RING — Docker Compose 快捷入口
#
#   make init      交互式首装（等价 ./ring-init.sh）
#   make up        启动全部（core + ring + edge）
#   make core      只启动最小可对话栈（openviking + maibot + napcat）
#   make down      停止（保留数据）
#   make logs      跟踪日志
#   make ps        状态
#   make doctor    体检
#   make backup    立刻备份一次
#   make restore F=ring-20260101T000000Z.tar.gz.gpg
#   make upgrade   拉镜像 + 重建
#   make test      跑仓库单测（需要本地 python 环境）

SHELL := /bin/bash
RINGCTL := ./ringctl
F ?=

.PHONY: help init up core ring edge down logs ps doctor backup restore upgrade build pull config test clean

help:
	@sed -n '2,16p' Makefile | sed -e 's/^# \{0,1\}//'

init:
	./ring-init.sh

up:
	$(RINGCTL) up all

core:
	$(RINGCTL) up core

ring:
	$(RINGCTL) up ring

edge:
	$(RINGCTL) up edge

down:
	$(RINGCTL) down

logs:
	$(RINGCTL) logs $(SERVICE)

ps:
	$(RINGCTL) ps

doctor:
	$(RINGCTL) doctor

backup:
	$(RINGCTL) backup

restore:
	@test -n "$(F)" || { echo "用法: make restore F=<归档文件名>"; exit 2; }
	$(RINGCTL) restore "$(F)"

upgrade:
	$(RINGCTL) upgrade

build:
	$(RINGCTL) build

pull:
	$(RINGCTL) pull

config:
	$(RINGCTL) config

test:
	cd ../.. && python -m pytest -q

clean:
	$(RINGCTL) down
	@echo "数据仍在 ${RING_DATA_DIR:-./data}，如需彻底清理请手动删除该目录"
