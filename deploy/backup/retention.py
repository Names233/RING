#!/usr/bin/env python3
"""WebDAV 远端保留策略：按文件名时间戳保留最新 N 份，删除更早的包与 sidecar。

只用标准库（urllib + xml.etree），支持 Basic Auth 的通用 WebDAV 服务
（OpenList / Nextcloud / Apache mod_dav 等）。失败只告警，不影响本次备份结论。
"""

from __future__ import annotations

import base64
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

NS = {"d": "DAV:"}
NAME_RE = re.compile(r"^ring-backup-(\d{8}T\d{6}Z)\.tar\.gz\.gpg$")
PROPFIND_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/></d:prop></d:propfind>"""


def _request(method: str, url: str, auth: str, data: bytes | None = None,
             headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Basic {auth}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    base = os.environ.get("DAV_BASE", "").rstrip("/")
    user = os.environ.get("DAV_USER", "")
    password = os.environ.get("DAV_PASS", "")
    keep = max(1, int(os.environ.get("BACKUP_KEEP", "14")))
    if not base or not user:
        print("retention: DAV_BASE/DAV_USER 未配置，跳过")
        return 0

    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    try:
        body = _request("PROPFIND", base + "/", auth, PROPFIND_BODY, {"Depth": "1"})
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"retention: PROPFIND 失败: {exc}")
        return 1

    names: list[str] = []
    try:
        root = ET.fromstring(body)
        for resp in root.findall("d:response", NS):
            href = resp.findtext("d:href", default="", namespaces=NS)
            names.append(href.rstrip("/").rsplit("/", 1)[-1])
    except ET.ParseError as exc:
        print(f"retention: 解析 PROPFIND 失败: {exc}")
        return 1

    packages = sorted(n for n in names if NAME_RE.match(n))
    doomed = packages[:-keep]
    if not doomed:
        print(f"retention: remote={len(packages)} keep={keep} drop=0")
        return 0

    failures = 0
    for name in doomed:
        for target in (name, name + ".sha256"):
            try:
                _request("DELETE", f"{base}/{target}", auth)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    failures += 1
                    print(f"retention: 删除 {target} 失败: {exc}")
            except urllib.error.URLError as exc:
                failures += 1
                print(f"retention: 删除 {target} 失败: {exc}")
    print(f"retention: remote={len(packages)} keep={keep} drop={len(doomed)} failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
