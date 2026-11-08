#!/usr/bin/env python3
"""容器内 MaiBot 实例准备：改监听地址 + 生成 OpenViking 钩子配置。

只做两件幂等的事：
1. 把 config/bot_config.toml 里的 [http].host / [maim_message].ws_server_host
   改成 0.0.0.0（容器内 loopback 对外不可达；宿主侧仍只绑 127.0.0.1）。
   已配置成 0.0.0.0 时不改动；设置 MAIBOT_FORCE_BIND_HOST=0 可完全跳过。
2. 若 data/openviking.json 不存在（或 RING_OV_CONFIG_FORCE=1），按环境变量生成，
   权限 0600。字段与 patches/maibot-openviking/config-sample.json 同序同义。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV_BASE_URL = "OPENVIKING_BASE_URL"
ENV_API_KEY = "OPENVIKING_API_KEY"
ENV_API_KEY_FILE = "OPENVIKING_API_KEY_FILE"
DEFAULT_BASE_URL = "http://openviking:1933"


def patch_bind_hosts(instance_dir: Path) -> list[str]:
    """把实例配置的监听地址收敛到 0.0.0.0（幂等）。"""
    if os.environ.get("MAIBOT_FORCE_BIND_HOST", "1").strip() == "0":
        return []

    config_path = instance_dir / "config" / "bot_config.toml"
    if not config_path.is_file():
        return []

    import tomlkit

    text = config_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(text)
    changes: list[str] = []

    http_section = doc.get("http")
    if http_section is not None and list(http_section.get("host", [])) != ["0.0.0.0"]:
        http_section["host"] = ["0.0.0.0"]
        changes.append("[http].host = [\"0.0.0.0\"]")

    mm_section = doc.get("maim_message")
    if mm_section is not None and mm_section.get("ws_server_host") != "0.0.0.0":
        mm_section["ws_server_host"] = "0.0.0.0"
        changes.append("[maim_message].ws_server_host = 0.0.0.0")

    if changes:
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def openviking_payload() -> dict[str, object]:
    return {
        "enabled": True,
        "base_url": os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/"),
        "api_key": os.environ.get(ENV_API_KEY, "").strip(),
        "api_key_file": os.environ.get(ENV_API_KEY_FILE, "").strip(),
        "timeout_seconds": 6.0,
        "limit": 6,
        "max_tokens": 700,
        "peer_scope": "all",
        "window_size": 8,
        "min_messages": 4,
        "query_max_chars": 600,
        "max_chars": 1200,
        "cache_ttl_seconds": 120,
        "min_interval_seconds": 30,
        "min_new_messages": 4,
        "failure_cooldown_seconds": 120,
        "write_enabled": True,
        "flush_interval_seconds": 60,
        "lookback_seconds": 7200,
        "max_batch_per_session": 40,
        "commit_message_threshold": 20,
        "idle_commit_seconds": 900,
        "state_file": "",
        "max_content_chars": 2000,
    }


def write_openviking_config(instance_dir: Path) -> str | None:
    target = instance_dir / "data" / "openviking.json"
    force = os.environ.get("RING_OV_CONFIG_FORCE", "0").strip() == "1"
    if target.is_file() and not force:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = openviking_payload()
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)
    return str(target)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: prepare_instance.py <maibot-instance-dir>", file=sys.stderr)
        return 2
    instance_dir = Path(argv[1]).expanduser().resolve()
    if not instance_dir.is_dir():
        print(f"实例目录不存在: {instance_dir}", file=sys.stderr)
        return 2

    for change in patch_bind_hosts(instance_dir):
        print(f"[ring] 已调整监听地址: {change}")

    written = write_openviking_config(instance_dir)
    if written:
        base = os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL)
        print(f"[ring] 已生成 OpenViking 钩子配置: {written}（base_url={base}）")
    else:
        print("[ring] 保留已有 data/openviking.json（RING_OV_CONFIG_FORCE=1 可强制重写）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
