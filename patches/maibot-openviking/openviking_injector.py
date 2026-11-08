"""Maisaka OpenViking 跨会话长期记忆注入服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import aiohttp

from src.common.logger import get_logger
from src.common.paths import get_instance_root

if TYPE_CHECKING:
    from src.chat.message_receive.message import SessionMessage

logger = get_logger("maisaka_openviking_memory")

OPENVIKING_MEMORY_REFERENCE_MARKER = "【OpenViking记忆-内部参考】"
OPENVIKING_MEMORY_REFERENCE_TAIL = "以上为跨会话长期记忆，仅供推理参考，不要原文复述给用户。"
OPENVIKING_CONFIG_FILENAME = "openviking.json"
OPENVIKING_SEARCH_PATH = "/api/v1/search/search"


@dataclass(frozen=True)
class OpenVikingConfig:
    """OpenViking 记忆注入配置快照。"""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:1933"
    api_key: str = ""
    api_key_file: str = ""
    timeout_seconds: float = 6.0
    limit: int = 6
    max_tokens: int = 700
    peer_scope: str = "all"
    window_size: int = 8
    min_messages: int = 4
    query_max_chars: int = 600
    max_chars: int = 1200
    cache_ttl_seconds: float = 120.0
    min_interval_seconds: float = 30.0
    min_new_messages: int = 4
    failure_cooldown_seconds: float = 120.0
    # 以下为「边聊边记」写入侧配置，读侧行为不受影响。
    write_enabled: bool = True
    flush_interval_seconds: float = 60.0
    lookback_seconds: float = 7200.0
    max_batch_per_session: int = 40
    commit_message_threshold: int = 20
    idle_commit_seconds: float = 900.0
    state_file: str = ""
    max_content_chars: int = 2000


@dataclass
class _State:
    """单个聊天流的 OpenViking 记忆运行时状态。"""

    last_recall_at: float = 0.0
    last_message_count: int = 0
    cached_reference: str = ""
    cache_expires_at: float = 0.0
    failure_until: float = 0.0


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _as_float(value: Any, *, default: float, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _as_int(value: Any, *, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _as_str(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    normalized = str(value).strip()
    return normalized or default


class OpenVikingInjector:
    """每轮 Planner 推理前召回 OpenViking 跨会话长期记忆。"""

    def __init__(self) -> None:
        self._states: dict[str, _State] = {}
        self._config_path: Path | None = None
        self._config_mtime: float | None = None
        self._config = OpenVikingConfig()
        self._api_key_cache = ""
        self._api_key_file_mtime: float | None = None

    async def build_injection_message(
        self,
        *,
        session_id: str,
    ) -> str:
        """构造给 Planner 共享的一次性 OpenViking 记忆参考。"""

        try:
            # 惰性导入：写入模块要复用本模块的配置解析，避免循环导入。
            from src.maisaka.memory.openviking_writer import openviking_memory_writer

            await openviking_memory_writer.ensure_started()
        except Exception as exc:
            logger.debug(f"OpenViking 写入任务启动失败，已跳过: {exc}")

        config = self._load_config()
        clean_session_id = str(session_id or "").strip()
        if not config.enabled:
            self.clear_session_reference(clean_session_id)
            return ""

        resolved_session_id = clean_session_id
        try:
            from src.chat.message_receive.chat_manager import chat_manager

            session = chat_manager.get_existing_session_by_session_id(clean_session_id)
            if session is None:
                logger.debug(f"OpenViking 记忆跳过：无法解析真实聊天流 session_id={clean_session_id!r}")
                return ""

            from src.common.message_repository import count_messages, find_messages

            resolved_session_id = str(session.session_id or clean_session_id)
            total_message_count = count_messages(session_id=resolved_session_id)
            if total_message_count < config.min_messages:
                self.clear_session_reference(resolved_session_id)
                return ""

            state = self._states.setdefault(resolved_session_id, _State())
            now = time()
            if (
                state.cached_reference
                and config.cache_ttl_seconds > 0
                and now < state.cache_expires_at
            ):
                return state.cached_reference

            if not self._can_trigger(
                state=state,
                total_message_count=total_message_count,
                now=now,
                min_interval_seconds=config.min_interval_seconds,
                min_new_messages=config.min_new_messages,
            ):
                self.clear_session_reference(resolved_session_id)
                return ""

            recent_messages = find_messages(
                session_id=resolved_session_id,
                limit=config.window_size,
                limit_mode="latest",
                filter_command=True,
            )
            if len(recent_messages) < config.window_size:
                self.clear_session_reference(resolved_session_id)
                return ""

            if now < state.failure_until:
                return ""

            query = self._build_query(recent_messages)
            if not query:
                self.clear_session_reference(resolved_session_id)
                return ""

            body = await self._search_openviking(query)
            reference = self._format_reference(body, max_chars=config.max_chars)
            if not reference:
                self.clear_session_reference(resolved_session_id)
                return ""
        except Exception as exc:
            logger.debug(f"OpenViking 记忆注入失败，已跳过: {exc}", exc_info=True)
            self._mark_failure(resolved_session_id, config)
            return ""

        state.last_recall_at = now
        state.last_message_count = total_message_count
        state.cached_reference = reference
        state.cache_expires_at = (
            now + config.cache_ttl_seconds if config.cache_ttl_seconds > 0 else 0.0
        )
        logger.info(
            f"OpenViking 记忆注入成功: session_id={resolved_session_id} chars={len(reference)}"
        )
        return reference

    def clear_session_reference(self, session_id: str) -> None:
        """清理当前会话的本轮注入参考。"""

        state = self._states.get(str(session_id or "").strip())
        if state is None:
            return
        state.cached_reference = ""
        state.cache_expires_at = 0.0

    def _load_config(self) -> OpenVikingConfig:
        """按 mtime 缓存加载实例目录下的 OpenViking 配置。"""

        try:
            config_path = get_instance_root() / "data" / OPENVIKING_CONFIG_FILENAME
            config_mtime = config_path.stat().st_mtime
        except OSError:
            self._config = OpenVikingConfig(enabled=False)
            self._config_path = None
            self._config_mtime = None
            return self._config
        except Exception as exc:
            logger.debug(f"OpenViking 配置路径解析失败，已禁用: {exc}")
            self._config = OpenVikingConfig(enabled=False)
            self._config_path = None
            self._config_mtime = None
            return self._config

        if self._config_path == config_path and self._config_mtime == config_mtime:
            return self._config

        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug(f"OpenViking 配置解析失败，已禁用: {exc}")
            self._config = OpenVikingConfig(enabled=False)
            self._config_path = config_path
            self._config_mtime = config_mtime
            return self._config

        if not isinstance(payload, Mapping):
            logger.debug("OpenViking 配置格式无效，已禁用")
            self._config = OpenVikingConfig(enabled=False)
            self._config_path = config_path
            self._config_mtime = config_mtime
            return self._config

        self._config = OpenVikingConfig(
            enabled=_as_bool(payload.get("enabled"), default=True),
            base_url=_as_str(payload.get("base_url"), default="http://127.0.0.1:1933"),
            api_key=_as_str(payload.get("api_key")),
            api_key_file=_as_str(payload.get("api_key_file")),
            timeout_seconds=_as_float(payload.get("timeout_seconds"), default=6.0, minimum=0.1),
            limit=_as_int(payload.get("limit"), default=6, minimum=1),
            max_tokens=_as_int(payload.get("max_tokens"), default=700, minimum=0),
            peer_scope=_as_str(payload.get("peer_scope"), default="all"),
            window_size=_as_int(payload.get("window_size"), default=8, minimum=1),
            min_messages=_as_int(payload.get("min_messages"), default=4, minimum=0),
            query_max_chars=_as_int(payload.get("query_max_chars"), default=600, minimum=0),
            max_chars=_as_int(payload.get("max_chars"), default=1200, minimum=1),
            cache_ttl_seconds=_as_float(payload.get("cache_ttl_seconds"), default=120.0),
            min_interval_seconds=_as_float(payload.get("min_interval_seconds"), default=30.0),
            min_new_messages=_as_int(payload.get("min_new_messages"), default=4, minimum=0),
            failure_cooldown_seconds=_as_float(
                payload.get("failure_cooldown_seconds"), default=120.0
            ),
            write_enabled=_as_bool(payload.get("write_enabled"), default=True),
            flush_interval_seconds=_as_float(
                payload.get("flush_interval_seconds"), default=60.0, minimum=5.0
            ),
            lookback_seconds=_as_float(
                payload.get("lookback_seconds"), default=7200.0, minimum=60.0
            ),
            max_batch_per_session=_as_int(
                payload.get("max_batch_per_session"), default=40, minimum=1
            ),
            commit_message_threshold=_as_int(
                payload.get("commit_message_threshold"), default=20, minimum=1
            ),
            idle_commit_seconds=_as_float(payload.get("idle_commit_seconds"), default=900.0),
            state_file=_as_str(payload.get("state_file")),
            max_content_chars=_as_int(payload.get("max_content_chars"), default=2000, minimum=1),
        )
        self._config_path = config_path
        self._config_mtime = config_mtime
        return self._config

    def _resolve_api_key(self, config: OpenVikingConfig) -> str:
        """优先使用配置内的 api_key，否则按 mtime 缓存读取 api_key_file。"""

        if config.api_key:
            return config.api_key.strip()
        if not config.api_key_file:
            return ""

        key_path = Path(config.api_key_file).expanduser()
        try:
            key_mtime = key_path.stat().st_mtime
        except OSError as exc:
            logger.debug(f"OpenViking API key 文件不可读: {exc}")
            return ""
        if self._api_key_cache and self._api_key_file_mtime == key_mtime:
            return self._api_key_cache
        try:
            api_key = key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.debug(f"OpenViking API key 文件读取失败: {exc}")
            return ""
        self._api_key_cache = api_key
        self._api_key_file_mtime = key_mtime
        return api_key

    def _mark_failure(self, session_id: str, config: OpenVikingConfig) -> None:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return
        state = self._states.setdefault(clean_session_id, _State())
        state.cached_reference = ""
        state.cache_expires_at = 0.0
        state.failure_until = time() + max(0.0, config.failure_cooldown_seconds)

    @staticmethod
    def _can_trigger(
        *,
        state: _State,
        total_message_count: int,
        now: float,
        min_interval_seconds: float,
        min_new_messages: int,
    ) -> bool:
        if state.last_message_count <= 0:
            return True
        if min_interval_seconds > 0 and now - state.last_recall_at < min_interval_seconds:
            return False
        return total_message_count - state.last_message_count >= min_new_messages

    def _build_query(self, recent_messages: Sequence[SessionMessage]) -> str:
        """把最近消息压成按时间正序的检索 query，从尾部保留最近内容。"""

        lines: list[str] = []
        for message in recent_messages:
            text = self._extract_message_text(message)
            if not text:
                continue
            sender = self._describe_message_sender(message)
            lines.append(f"[{sender}]: {text}")
        if not lines:
            return ""

        query = "\n".join(lines)
        max_chars = self._config.query_max_chars
        if max_chars > 0 and len(query) > max_chars:
            query = query[-max_chars:]
            newline_index = query.find("\n")
            if 0 <= newline_index < len(query) - 1:
                query = query[newline_index + 1 :]
        return query.strip()

    @staticmethod
    def _extract_message_text(message: SessionMessage) -> str:
        """只取文本与语音转写，忽略图片/表情/@ 等组件。"""

        try:
            from src.common.data_models.message_component_data_model import (
                TextComponent,
                VoiceComponent,
            )
        except Exception:
            return ""

        parts: list[str] = []
        raw_message = getattr(message, "raw_message", None)
        for component in getattr(raw_message, "components", []) or []:
            if isinstance(component, TextComponent):
                text = str(getattr(component, "text", "") or "").strip()
                if text:
                    parts.append(text)
            elif isinstance(component, VoiceComponent):
                content = str(getattr(component, "content", "") or "").strip()
                if content and not content.startswith("[语音消息"):
                    parts.append(content)
        text = " ".join(parts).replace("\r", " ").replace("\n", " ").strip()
        return " ".join(text.split())

    @staticmethod
    def _describe_message_sender(message: SessionMessage) -> str:
        user_info = message.message_info.user_info
        return str(
            getattr(user_info, "user_cardname", "")
            or getattr(user_info, "user_nickname", "")
            or getattr(user_info, "user_id", "")
            or "unknown_user"
        ).strip()

    async def _search_openviking(self, query: str) -> str:
        """调用 OpenViking 搜索接口并返回纯文本记忆正文。"""

        config = self._load_config()
        clean_query = str(query or "").strip()
        if not clean_query:
            return ""

        api_key = self._resolve_api_key(config)
        if not api_key:
            logger.debug("OpenViking 记忆跳过：未配置 api_key")
            return ""

        url = config.base_url.rstrip("/") + OPENVIKING_SEARCH_PATH
        timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": clean_query,
            "limit": config.limit,
            "mode": "context",
            "max_tokens": config.max_tokens,
            "peer_scope": config.peer_scope,
            "query_expansion": "off",
        }

        data = await self._post_search(url=url, payload=payload, headers=headers, timeout=timeout)
        body = self._extract_context_body(data)
        if body:
            return body
        return await self._search_list_mode(
            query=clean_query, url=url, headers=headers, timeout=timeout
        )

    async def _post_search(
        self,
        *,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> Any:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=dict(payload), headers=dict(headers)) as response:
                if response.status != 200:
                    body = await response.text()
                    raise RuntimeError(
                        f"OpenViking 搜索失败 status={response.status} body={body[:200]}"
                    )
                return await response.json()

    @staticmethod
    def _extract_context_body(data: Any) -> str:
        result = data.get("result") if isinstance(data, Mapping) else None
        if not isinstance(result, Mapping):
            return ""

        rendered = str(result.get("rendered") or "").strip()
        if rendered:
            return rendered

        entries = result.get("entries")
        if not isinstance(entries, list):
            return ""
        texts = [
            str(entry.get("text") or "").strip()
            for entry in entries
            if isinstance(entry, Mapping)
        ]
        return "\n".join(text for text in texts if text)

    async def _search_list_mode(
        self,
        *,
        query: str,
        url: str,
        headers: Mapping[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> str:
        config = self._config
        payload = {"query": query, "limit": config.limit}
        data = await self._post_search(url=url, payload=payload, headers=headers, timeout=timeout)
        result = data.get("result") if isinstance(data, Mapping) else None
        if not isinstance(result, Mapping):
            return ""
        memories = result.get("memories")
        if not isinstance(memories, list):
            return ""
        abstracts = [
            str(memory.get("abstract") or "").strip()
            for memory in memories
            if isinstance(memory, Mapping)
        ]
        return "\n".join(abstract for abstract in abstracts if abstract)

    def _format_reference(self, body: str, max_chars: int) -> str:
        """把记忆正文包成内部参考消息，超长时保留标记行并截断正文。"""

        clean_body = str(body or "").replace("\r\n", "\n").strip()
        if not clean_body:
            return ""

        reference = "\n".join(
            (
                OPENVIKING_MEMORY_REFERENCE_MARKER,
                clean_body,
                OPENVIKING_MEMORY_REFERENCE_TAIL,
            )
        )
        if max_chars <= 0 or len(reference) <= max_chars:
            return reference

        overhead = (
            len(OPENVIKING_MEMORY_REFERENCE_MARKER)
            + len(OPENVIKING_MEMORY_REFERENCE_TAIL)
            + 2
        )
        available = max_chars - overhead - 1
        if available <= 0:
            return reference[:max_chars].rstrip()
        clipped = clean_body[:available].rstrip() + "…"
        return "\n".join(
            (
                OPENVIKING_MEMORY_REFERENCE_MARKER,
                clipped,
                OPENVIKING_MEMORY_REFERENCE_TAIL,
            )
        )


openviking_memory_injector = OpenVikingInjector()
