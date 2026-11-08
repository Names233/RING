"""Maisaka OpenViking 边聊边记写入服务。

后台协程周期性把最近的聊天消息增量写入 OpenViking 会话，
再按阈值显式 commit，由 OpenViking 自身抽取长期记忆。
与读侧 ``openviking_injector`` 共用同一份实例配置。
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import quote

import aiohttp

from src.common.logger import get_logger
from src.common.paths import get_instance_root
from src.maisaka.memory.openviking_injector import (
    OpenVikingConfig,
    openviking_memory_injector,
)

if TYPE_CHECKING:
    from src.chat.message_receive.message import SessionMessage

logger = get_logger("maisaka_openviking_writer")

OPENVIKING_WRITE_STATE_FILENAME = "openviking_write_state.json"
OPENVIKING_SESSION_ID_PREFIX = "mb-"
OPENVIKING_SESSIONS_PATH = "/api/v1/sessions"
OPENVIKING_COMMIT_TIMEOUT_SECONDS = 20.0
OPENVIKING_COMMIT_POLICY: dict[str, int] = {
    # 阈值设得极高：改为由 writer 自己决定何时 commit，避免不可控触发。
    "message_count_threshold": 1000,
    "idle_timeout_seconds": 86400,
    "min_commit_interval_seconds": 60,
    "keep_recent_count": 6,
}


def _message_epoch(message: Any) -> float:
    """把消息时间归一成 epoch 秒；DB 里的 timestamp 是 naive datetime。"""

    value = getattr(message, "timestamp", None)
    if isinstance(value, datetime):
        try:
            return float(value.timestamp())
        except (OSError, OverflowError, ValueError):
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit]


class OpenVikingMemoryWriter:
    """把聊天消息增量写入 OpenViking 会话并按需提交。"""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._state: dict[str, dict[str, Any]] = {}
        self._state_path: Path | None = None
        self._state_loaded = False

    # ------------------------------------------------------------------ 生命周期

    async def ensure_started(self) -> None:
        """幂等启动后台写入协程。"""

        if self._task is not None and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop(), name="openviking-memory-writer")
        self._task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: "asyncio.Task[None]") -> None:
        self._task = None
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning(f"OpenViking 写入任务退出: {type(exc).__name__}: {exc}")

    async def _run_loop(self) -> None:
        """每 flush_interval_seconds 跑一次，异常一律吞掉并等下轮重试。"""

        first_cycle = True
        while True:
            config = self._load_config()
            interval = max(5.0, float(config.flush_interval_seconds))
            if first_cycle:
                first_cycle = False
                logger.info(
                    f"OpenViking 写入任务已启动: interval={interval:.0f}s "
                    f"lookback={float(config.lookback_seconds):.0f}s "
                    f"batch={int(config.max_batch_per_session)} "
                    f"commit_at={int(config.commit_message_threshold)} "
                    f"idle={float(config.idle_commit_seconds):.0f}s"
                )
            try:
                stats = await self._flush_once()
                logger.debug(
                    f"OpenViking 写入心跳: sessions={stats.get('sessions', 0)} "
                    f"written={stats.get('written', 0)} "
                    f"committed={stats.get('committed', 0)} "
                    f"errors={stats.get('errors', 0)}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"OpenViking 写入周期失败，将重试: {type(exc).__name__}: {exc}")
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------ 主流程

    async def flush_now(self) -> dict[str, Any]:
        """自检入口：立即跑一轮写入并返回本轮统计。"""

        return await self._flush_once()

    async def _flush_once(self) -> dict[str, Any]:
        async with self._lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> dict[str, Any]:
        config = self._load_config()
        stats: dict[str, Any] = {
            "enabled": bool(config.write_enabled),
            "sessions": 0,
            "written": 0,
            "committed": 0,
            "errors": 0,
            "task_ids": [],
        }
        if not config.write_enabled:
            return stats

        if not self._resolve_api_key(config):
            stats["skipped"] = "missing_api_key"
            logger.debug("OpenViking 写入跳过：未取到 API key")
            return stats

        now = time()
        try:
            messages = self._fetch_recent_messages(now, config)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats["errors"] += 1
            logger.warning(f"OpenViking 写入取消息失败: {type(exc).__name__}: {exc}")
            return stats

        groups: dict[str, list[Any]] = {}
        for message in messages:
            session_id = str(getattr(message, "session_id", "") or "").strip()
            if not session_id:
                continue
            groups.setdefault(session_id, []).append(message)

        state = self._load_state()
        stats["sessions"] = len(groups)

        targets = set(groups)
        targets.update(
            session_id
            for session_id, entry in state.items()
            if int(entry.get("uncommitted") or 0) > 0
        )

        for session_id in sorted(targets):
            try:
                written = await self._write_session(session_id, groups.get(session_id, []), config)
            except asyncio.CancelledError:
                self._save_state()
                raise
            except Exception as exc:
                stats["errors"] += 1
                logger.warning(
                    f"OpenViking 写入会话失败: session={session_id[:8]} "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            stats["written"] += written
            entry = state.get(session_id) or {}
            last_task_id = str(entry.get("last_task_id") or "")
            if written and last_task_id and last_task_id not in stats["task_ids"]:
                stats["task_ids"].append(last_task_id)
                stats["committed"] += 1

        self._save_state()
        return stats

    @staticmethod
    def _fetch_recent_messages(now: float, config: OpenVikingConfig) -> list[Any]:
        from src.common.message_repository import find_messages

        since = now - max(60.0, float(config.lookback_seconds))
        result = find_messages(
            after_time=since,
            limit=0,
            sort=[("time", 1)],
            filter_command=True,
        )
        return list(result or [])

    async def _write_session(
        self,
        session_id: str,
        messages: list[Any],
        config: OpenVikingConfig,
    ) -> int:
        state = self._state
        entry = state.setdefault(session_id, {})
        now = time()

        cursor = float(entry.get("cursor") or 0.0)
        pending = [message for message in messages if _message_epoch(message) > cursor]
        pending.sort(key=_message_epoch)

        if cursor <= 0.0 and pending:
            # 首次见到该会话：从本批最早一条起写，避免把整个历史都灌进去。
            cursor = _message_epoch(pending[0]) - 0.001
            entry["cursor"] = cursor

        if not pending:
            await self._maybe_commit(session_id, entry, config)
            return 0

        max_batch = max(1, int(config.max_batch_per_session))
        considered = pending[:max_batch]
        cursor_target = _message_epoch(considered[-1])

        payload_messages: list[dict[str, str]] = []
        last_signature: tuple[str, str] | None = None
        for message in considered:
            text = self._message_text(message)
            if not text:
                continue
            role = self._message_role(message)
            text = _truncate_text(text, max(0, int(config.max_content_chars)))
            signature = (role, text)
            if signature == last_signature:
                continue
            last_signature = signature
            payload_messages.append(
                {
                    "role": role,
                    "content": text,
                    "created_at": datetime.fromtimestamp(
                        _message_epoch(message), tz=timezone.utc
                    ).isoformat(),
                }
            )

        if not payload_messages:
            entry["cursor"] = cursor_target
            await self._maybe_commit(session_id, entry, config)
            return 0

        await self._ensure_session(session_id, config)
        written = await self._post_messages(session_id, payload_messages, config)
        if written <= 0:
            # 没写成功就不推进游标，下轮重试同一批。
            return 0

        entry["cursor"] = cursor_target
        entry["uncommitted"] = int(entry.get("uncommitted") or 0) + written
        entry["last_write_at"] = now
        logger.info(
            f"OpenViking 写入: session={session_id[:8]} n={written} "
            f"uncommitted={entry['uncommitted']}"
        )

        await self._maybe_commit(session_id, entry, config)
        return written

    async def _maybe_commit(
        self,
        session_id: str,
        entry: dict[str, Any],
        config: OpenVikingConfig,
    ) -> None:
        uncommitted = int(entry.get("uncommitted") or 0)
        if uncommitted <= 0:
            return
        now = time()
        threshold = max(1, int(config.commit_message_threshold))
        idle_seconds = max(0.0, float(config.idle_commit_seconds))
        last_write_at = float(entry.get("last_write_at") or 0.0)
        due_by_count = uncommitted >= threshold
        due_by_idle = idle_seconds > 0 and (now - last_write_at) >= idle_seconds
        if not (due_by_count or due_by_idle):
            return

        task_id = await self._commit(session_id, config)
        if task_id is None:
            logger.warning(f"OpenViking 提交失败，稍后重试: session={session_id[:8]}")
            return
        entry["uncommitted"] = 0
        entry["last_commit_at"] = now
        if task_id:
            entry["last_task_id"] = task_id
            logger.info(f"OpenViking 提交: session={session_id[:8]} task={task_id[:8]}")
        else:
            logger.info(f"OpenViking 提交跳过（无新增待归档消息）: session={session_id[:8]}")

    async def _ensure_session(self, session_id: str, config: OpenVikingConfig) -> None:
        body = {
            "session_id": self._openviking_session_id(session_id),
            "auto_commit_policy": dict(OPENVIKING_COMMIT_POLICY),
        }
        # 已存在时服务端可能返回 4xx，这里只作为尽力而为的准备步骤。
        await self._request_json(
            "POST",
            OPENVIKING_SESSIONS_PATH,
            config=config,
            payload=body,
            label="create_session",
            quiet=True,
        )

    async def _post_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        config: OpenVikingConfig,
    ) -> int:
        path = (
            f"{OPENVIKING_SESSIONS_PATH}/{quote(self._openviking_session_id(session_id), safe='')}"
            "/messages/batch"
        )
        payload = await self._request_json(
            "POST",
            path,
            config=config,
            payload={"messages": messages},
            label="batch_messages",
        )
        if payload is None:
            return 0
        return len(messages)

    async def _commit(self, session_id: str, config: OpenVikingConfig) -> str | None:
        """返回 task_id；空串表示服务端判定无待归档内容（正常跳过），None 表示请求失败。"""

        path = (
            f"{OPENVIKING_SESSIONS_PATH}/{quote(self._openviking_session_id(session_id), safe='')}"
            "/commit"
        )
        payload = await self._request_json(
            "POST",
            path,
            config=config,
            payload={},
            timeout=max(float(config.timeout_seconds), OPENVIKING_COMMIT_TIMEOUT_SECONDS),
            label="commit",
        )
        if payload is None:
            return None
        result = payload.get("result")
        if isinstance(result, Mapping):
            return str(result.get("task_id") or "")
        return ""

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        config: OpenVikingConfig,
        payload: Any = None,
        timeout: float | None = None,
        label: str = "",
        quiet: bool = False,
    ) -> dict[str, Any] | None:
        api_key = self._resolve_api_key(config)
        if not api_key:
            return None
        url = f"{config.base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        total_timeout = max(1.0, float(timeout or config.timeout_seconds))
        client_timeout = aiohttp.ClientTimeout(total=total_timeout)
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.request(method, url, json=payload, headers=headers) as response:
                    text = await response.text()
                    if response.status >= 400:
                        if not quiet:
                            logger.warning(
                                f"OpenViking 写入请求被拒: {label or method} status={response.status}"
                            )
                        return None
                    if not text.strip():
                        return {}
                    try:
                        decoded = json.loads(text)
                    except json.JSONDecodeError:
                        return {}
                    return decoded if isinstance(decoded, dict) else {}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not quiet:
                logger.warning(
                    f"OpenViking 写入请求异常: {label or method} {type(exc).__name__}: {exc}"
                )
            return None

    # ------------------------------------------------------------------ 消息转换

    @staticmethod
    def _openviking_session_id(session_id: str) -> str:
        clean = str(session_id or "").strip()
        if clean.startswith(OPENVIKING_SESSION_ID_PREFIX):
            return clean
        return f"{OPENVIKING_SESSION_ID_PREFIX}{clean}"

    @classmethod
    def _message_text(cls, message: Any) -> str:
        text = str(getattr(message, "processed_plain_text", "") or "")
        if not text.strip():
            try:
                text = openviking_memory_injector._extract_message_text(message)
            except Exception:
                text = ""
        return " ".join(str(text).replace("\r", " ").replace("\n", " ").split())

    @classmethod
    def _message_role(cls, message: Any) -> str:
        platform = str(getattr(message, "platform", "") or "").strip()
        user_info = getattr(getattr(message, "message_info", None), "user_info", None)
        user_id = str(getattr(user_info, "user_id", "") or "").strip()
        try:
            from src.common.utils.system_utils import is_bot_self

            if is_bot_self(platform, user_id):
                return "assistant"
        except Exception:
            pass
        return "user"

    # ------------------------------------------------------------------ 配置与游标

    def _load_config(self) -> OpenVikingConfig:
        """复用读侧配置加载，保证两侧读到同一份快照。"""

        return openviking_memory_injector._load_config()

    def _resolve_api_key(self, config: OpenVikingConfig) -> str:
        return openviking_memory_injector._resolve_api_key(config)

    def _resolve_state_path(self, config: OpenVikingConfig) -> Path:
        raw = str(config.state_file or "").strip()
        if raw:
            return Path(raw).expanduser()
        return get_instance_root() / "data" / OPENVIKING_WRITE_STATE_FILENAME

    def _load_state(self) -> dict[str, dict[str, Any]]:
        path = self._resolve_state_path(self._load_config())
        if self._state_loaded and self._state_path == path:
            return self._state

        state: dict[str, dict[str, Any]] = {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            sessions = payload
            if isinstance(payload, Mapping) and isinstance(payload.get("sessions"), Mapping):
                sessions = payload["sessions"]
            if isinstance(sessions, Mapping):
                for key, value in sessions.items():
                    if isinstance(value, Mapping):
                        state[str(key)] = dict(value)
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning(
                f"OpenViking 写入游标读取失败，按最近窗口重新开始: {type(exc).__name__}"
            )

        self._state = state
        self._state_path = path
        self._state_loaded = True
        return state

    def _save_state(self, state: dict[str, dict[str, Any]] | None = None) -> None:
        if not self._state_loaded:
            return
        path = self._state_path or self._resolve_state_path(self._load_config())
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sessions": self._state if state is None else state,
        }
        tmp_path = path.with_name(f"{path.name}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp_path, path)
        except Exception as exc:
            logger.warning(f"OpenViking 写入游标保存失败: {type(exc).__name__}: {exc}")


openviking_memory_writer = OpenVikingMemoryWriter()
