"""OneBot 正向 WebSocket 传输层（SnowLuma / SnowLuma / NapCat 通用）。"""

from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, Optional, Set, cast
from urllib.parse import quote, quote_plus, urlencode
from uuid import uuid4

import asyncio
import contextlib
import errno
import json
import re
import socket
import time

from .config import QQServerConfig
from .profile import ProfileState

if TYPE_CHECKING:
    from aiohttp import ClientWebSocketResponse as AiohttpClientWebSocketResponse

try:
    from aiohttp import (
        ClientConnectorError,
        ClientSession,
        ClientSSLError,
        ClientTimeout,
        WSMsgType,
        WSServerHandshakeError,
    )

    AIOHTTP_AVAILABLE = True
except ImportError:
    ClientSession = cast(Any, None)
    ClientTimeout = cast(Any, None)
    WSMsgType = cast(Any, None)
    AIOHTTP_AVAILABLE = False

if not TYPE_CHECKING:
    AiohttpClientWebSocketResponse = Any

# 断连后按指数退避重连：attempt 每失败一次加一，指数最多放大 2**6 倍，总等待不超过 300 秒。
RECONNECT_BACKOFF_EXPONENT_CAP = 6
MAX_RECONNECT_DELAY_SEC = 300.0
# 连续失败的完整警告在窗口内只输出一次，其余降级为 debug，避免 NapCat 未就绪时刷屏。
FAILURE_LOG_THROTTLE_SEC = 300.0


class QQTransportClient:
    """OneBot 正向 WebSocket 客户端。"""

    def __init__(
        self,
        logger: Any,
        on_connection_opened: Callable[[], Coroutine[Any, Any, None]],
        on_connection_closed: Callable[[], Coroutine[Any, Any, None]],
        on_payload: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """初始化传输层客户端。

        Args:
            logger: 插件日志对象。
            on_connection_opened: 连接建立后的异步回调。
            on_connection_closed: 连接断开后的异步回调。
            on_payload: 收到非 echo 载荷后的异步回调。
        """
        self._logger = logger
        self._on_connection_opened = on_connection_opened
        self._on_connection_closed = on_connection_closed
        self._on_payload = on_payload
        self._server_config: Optional[QQServerConfig] = None
        self._connection_task: Optional[asyncio.Task[None]] = None
        self._pending_actions: Dict[str, asyncio.Future[Dict[str, Any]]] = {}
        self._background_tasks: Set[asyncio.Task[Any]] = set()
        self._send_lock = asyncio.Lock()
        self._ws: Optional[AiohttpClientWebSocketResponse] = None
        self._stop_requested: bool = False
        self._connection_active: bool = False
        self._warned_missing_token_for_ws_url: Optional[str] = None
        self._profile_state: Optional[ProfileState] = None
        self._reconnect_attempt: int = 0
        self._failure_log_monotonic: Optional[float] = None
        self._failure_log_suppressed: int = 0

    @classmethod
    def is_available(cls) -> bool:
        """判断当前环境是否安装了传输层依赖。

        Returns:
            bool: 若已安装 ``aiohttp``，则返回 ``True``。
        """
        return AIOHTTP_AVAILABLE

    def configure(self, server_config: QQServerConfig, profile_state: Optional[ProfileState] = None) -> None:
        """更新当前传输层使用的对端服务端配置与画像。

        Args:
            server_config: 最新生效的对端服务端配置。
            profile_state: 当前连接的画像容器（保留给上层诊断使用，不影响鉴权）。
        """
        self._server_config = server_config
        self._profile_state = profile_state
        self._warned_missing_token_for_ws_url = None

    def _build_connect_url(self, server_config: QQServerConfig) -> str:
        """构造连接地址。

        token 同时以 URL ``access_token`` 参数携带（OneBot v11 标准方式之一），
        与 ``Authorization: Bearer`` 头双通道并发；SnowLuma 与 NapCat 各取所需。

        Args:
            server_config: 当前生效的对端服务端配置。

        Returns:
            str: 实际用于握手的 WebSocket 地址（可能包含 token，禁止写入日志）。
        """
        base_url = server_config.build_ws_url()
        if not server_config.token:
            return base_url
        return f"{base_url}?{urlencode({'access_token': server_config.token})}"

    def _build_display_url(self, server_config: QQServerConfig) -> str:
        """构造用于日志展示的连接地址（剔除 token，避免泄露）。

        Args:
            server_config: 当前生效的对端服务端配置。

        Returns:
            str: 脱敏后的 WebSocket 地址。
        """
        if not server_config.token:
            return server_config.build_ws_url()
        return f"{server_config.build_ws_url()}?access_token=***"

    async def start(self) -> None:
        """启动 OneBot 正向 WebSocket 连接循环。

        Raises:
            RuntimeError: 当缺少配置或依赖时抛出。
        """
        if not self.is_available():
            raise RuntimeError("SnowLuma 适配器依赖 aiohttp，但当前环境未安装该依赖")
        if self._server_config is None:
            raise RuntimeError("SnowLuma 适配器尚未配置 client")
        if self._connection_task is not None and not self._connection_task.done():
            return

        self._stop_requested = False
        self._connection_task = asyncio.create_task(self._connection_loop(), name="napcat_adapter.connection")

    async def stop(self) -> None:
        """停止当前连接并清理所有后台任务。"""
        self._stop_requested = True
        connection_task = self._connection_task
        self._connection_task = None

        ws = self._ws
        if ws is not None and not ws.closed:
            with contextlib.suppress(Exception):
                await ws.close()
        self._ws = None

        if connection_task is not None:
            connection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection_task

        await self._cancel_background_tasks()
        await self._notify_connection_closed()
        self._fail_pending_actions("连接已关闭")

    async def call_action(self, action_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送 OneBot 动作并等待对应的 echo 响应。

        Args:
            action_name: OneBot 动作名称。
            params: 动作参数。

        Returns:
            Dict[str, Any]: 对端返回的原始响应字典。

        Raises:
            RuntimeError: 当连接不可用时抛出。
        """
        ws = self._ws
        server_config = self._server_config
        if ws is None or ws.closed or server_config is None:
            raise RuntimeError("对端未连接")

        echo_id = uuid4().hex
        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending_actions[echo_id] = response_future

        request_payload = {"action": action_name, "params": params, "echo": echo_id}
        try:
            async with self._send_lock:
                await ws.send_str(json.dumps(request_payload, ensure_ascii=False))
            return await asyncio.wait_for(response_future, timeout=server_config.action_timeout_sec)
        finally:
            self._pending_actions.pop(echo_id, None)

    async def _connection_loop(self) -> None:
        """维护单个 WebSocket 连接，并在断开后按配置重连。"""
        assert ClientSession is not None
        assert ClientTimeout is not None

        while not self._stop_requested:
            server_config = self._server_config
            if server_config is None:
                return

            ws_url = self._build_connect_url(server_config)
            display_url = self._build_display_url(server_config)
            timeout = ClientTimeout(total=None, connect=10)
            self._log_connection_attempt(display_url, server_config)

            try:
                async with ClientSession(headers=self._build_headers(server_config), timeout=timeout) as session:
                    async with session.ws_connect(ws_url, heartbeat=server_config.heartbeat_interval or None) as ws:
                        self._ws = ws
                        self._logger.info(f"适配器已连接: {display_url}")
                        # 连接成功即视为掉线恢复，重置退避阶梯与失败日志节流状态。
                        self._reconnect_attempt = 0
                        self._failure_log_monotonic = None
                        self._failure_log_suppressed = 0
                        disconnect_reason = await self._receive_loop(ws)
                        self._log_connection_closed(display_url, server_config, disconnect_reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_connection_failure(display_url, server_config, exc)
            finally:
                self._ws = None
                await self._notify_connection_closed()
                self._fail_pending_actions("连接已中断")

            if self._stop_requested:
                break

            # 指数退避：5 → 10 → 20 → 40 → 80 → 160 → 300（封顶）秒。
            delay = self._next_reconnect_delay(server_config)
            self._reconnect_attempt += 1
            await asyncio.sleep(delay)

    async def _receive_loop(self, ws: AiohttpClientWebSocketResponse) -> str:
        """持续消费 WebSocket 消息并分发处理。

        Args:
            ws: 当前活跃的 WebSocket 连接对象。

        Returns:
            str: 当前连接结束时的简要原因描述。
        """
        assert WSMsgType is not None

        disconnect_reason = "未收到更多 WebSocket 消息，连接已结束"
        bootstrap_task = self._create_background_task(
            self._notify_connection_opened(),
            "napcat_adapter.bootstrap",
        )
        try:
            async for ws_message in ws:
                if ws_message.type != WSMsgType.TEXT:
                    if ws_message.type == WSMsgType.CLOSE:
                        disconnect_reason = self._describe_terminal_ws_message(
                            ws=ws,
                            ws_message=ws_message,
                            message_label="收到服务端 CLOSE 帧",
                        )
                        break
                    if ws_message.type == WSMsgType.CLOSED:
                        disconnect_reason = self._describe_terminal_ws_message(
                            ws=ws,
                            ws_message=ws_message,
                            message_label="WebSocket 已关闭",
                        )
                        break
                    if ws_message.type == WSMsgType.ERROR:
                        disconnect_reason = self._describe_terminal_ws_message(
                            ws=ws,
                            ws_message=ws_message,
                            message_label="WebSocket 进入错误状态",
                        )
                        break
                    continue

                payload = self._parse_json_message(ws_message.data)
                if payload is None:
                    continue

                if echo_id := str(payload.get("echo") or "").strip():
                    self._resolve_pending_action(echo_id, payload)
                    continue

                self._create_background_task(self._on_payload(payload), "napcat_adapter.payload")
        finally:
            if bootstrap_task is not None and not bootstrap_task.done():
                bootstrap_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bootstrap_task

        return disconnect_reason

    def _create_background_task(self, coroutine: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
        """创建并跟踪一个后台任务。

        Args:
            coroutine: 待执行的协程对象。
            name: 任务名。

        Returns:
            asyncio.Task[Any]: 已创建的后台任务。
        """
        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._handle_background_task_completion)
        return task

    def _handle_background_task_completion(self, task: asyncio.Task[Any]) -> None:
        """处理后台任务结束后的清理与异常记录。

        Args:
            task: 已结束的后台任务。
        """
        self._background_tasks.discard(task)
        if task.cancelled():
            return

        exception = task.exception()
        if exception is not None:
            self._logger.error(f"SnowLuma 适配器后台任务异常: {exception}", exc_info=True)

    async def _cancel_background_tasks(self) -> None:
        """取消所有仍在运行的后台任务。"""
        background_tasks = list(self._background_tasks)
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def _notify_connection_opened(self) -> None:
        """在连接建立后触发上层回调。"""
        if self._connection_active:
            return

        self._connection_active = True
        try:
            await self._on_connection_opened()
        except Exception as exc:
            self._logger.warning(f"SnowLuma 适配器连接建立回调失败: {exc}")

    async def _notify_connection_closed(self) -> None:
        """在连接断开后触发上层回调。"""
        if not self._connection_active:
            return

        self._connection_active = False
        try:
            await self._on_connection_closed()
        except Exception as exc:
            self._logger.warning(f"SnowLuma 适配器断连回调失败: {exc}")

    def _resolve_pending_action(self, echo_id: str, payload: Dict[str, Any]) -> None:
        """解析等待中的动作响应。

        Args:
            echo_id: 动作请求对应的 echo 标识。
            payload: 对端返回的响应载荷。
        """
        response_future = self._pending_actions.get(echo_id)
        if response_future is None or response_future.done():
            return
        response_future.set_result(payload)

    def _fail_pending_actions(self, error_message: str) -> None:
        """让所有等待中的动作以异常方式结束。

        Args:
            error_message: 写入异常中的错误信息。
        """
        for response_future in self._pending_actions.values():
            if not response_future.done():
                response_future.set_exception(RuntimeError(error_message))
        self._pending_actions.clear()

    def _build_headers(self, server_config: QQServerConfig) -> Dict[str, str]:
        """构造连接所需的握手请求头。

        token 以 ``Authorization: Bearer`` 头携带（OneBot v11 标准方式之一），
        与 URL ``access_token`` 参数双通道并发，两类服务端各取所需。

        Args:
            server_config: 当前生效的对端服务端配置。

        Returns:
            Dict[str, str]: WebSocket 握手请求头。
        """
        if not server_config.token:
            return {}
        return {"Authorization": f"Bearer {server_config.token}"}

    def _next_reconnect_delay(self, server_config: QQServerConfig) -> float:
        """按连续失败次数计算下一次重连等待时间（指数退避，带上限）。

        Args:
            server_config: 当前生效的对端服务端配置。

        Returns:
            float: 本次应等待的秒数，不超过 ``MAX_RECONNECT_DELAY_SEC``。
        """
        exponent = min(self._reconnect_attempt, RECONNECT_BACKOFF_EXPONENT_CAP)
        return min(server_config.reconnect_delay_sec * 2**exponent, MAX_RECONNECT_DELAY_SEC)

    def _log_connection_failure(self, ws_url: str, server_config: QQServerConfig, exc: Exception) -> None:
        """记录连接失败，并按时间窗节流连续失败的日志。

        窗口内的重复失败降级为 debug 并累计次数；窗口外的失败恢复为完整 warning，
        并附上此前被省略的失败次数。

        Args:
            ws_url: 当前尝试连接的 WebSocket 地址（已脱敏）。
            server_config: 当前生效的对端服务端配置。
            exc: 导致本次失败的具体异常。
        """
        now = time.monotonic()
        last_logged = self._failure_log_monotonic
        if last_logged is not None and now - last_logged < FAILURE_LOG_THROTTLE_SEC:
            self._failure_log_suppressed += 1
            self._logger.debug(
                f"SnowLuma 适配器连接失败（已节流）: {ws_url}；"
                f"{self._describe_connection_error(exc, server_config)}"
                f"（连续失败 {self._reconnect_attempt + 1} 次）"
            )
            return

        suppressed, self._failure_log_suppressed = self._failure_log_suppressed, 0
        self._failure_log_monotonic = now
        message = (
            f"SnowLuma 适配器连接失败:{ws_url}；"
            f"{self._describe_connection_error(exc, server_config)}"
            f"{self._build_reconnect_hint(server_config)}"
        )
        if suppressed:
            message += f"（此前的 {suppressed} 次同类失败已省略）"
        self._logger.warning(message)

    def _log_connection_attempt(self, ws_url: str, server_config: QQServerConfig) -> None:
        """记录一次连接尝试的诊断信息。

        Args:
            ws_url: 即将连接的 WebSocket 地址。
            server_config: 当前生效的 对端服务端配置。
        """
        auth_mode = "已配置 token" if server_config.token else "未配置 token"
        self._logger.debug(f"SnowLuma 适配器开始连接: {ws_url}（鉴权: {auth_mode}）")

        if not server_config.token and self._warned_missing_token_for_ws_url != ws_url:
            self._logger.warning(
                "SnowLuma 适配器当前未配置 client.token；"
                "若对端开启了访问令牌校验，连接可能会被服务端立即断开"
            )
            self._warned_missing_token_for_ws_url = ws_url

    def _log_connection_closed(self, ws_url: str, server_config: QQServerConfig, reason: str) -> None:
        """记录连接结束与重连计划。

        Args:
            ws_url: 当前连接对应的 WebSocket 地址。
            server_config: 当前生效的 对端服务端配置。
            reason: 当前连接结束原因。
        """
        self._logger.warning(
            f"SnowLuma 适配器连接已断开: {ws_url}，{self._redact_connection_error(reason, server_config)}"
            f"{self._build_missing_token_hint(server_config)}"
            f"{self._build_reconnect_hint(server_config)}"
        )

    def _redact_connection_error(self, message: str, server_config: QQServerConfig) -> str:
        """移除异常文本中的访问令牌，包括 aiohttp 握手异常携带的完整 URL。"""
        if server_config.token:
            # 异常可能携带原值或 URL 编码后的值，不能只脱敏主动打印的连接地址。
            for token in sorted(
                {server_config.token, quote(server_config.token, safe=""), quote_plus(server_config.token)},
                key=len,
                reverse=True,
            ):
                message = message.replace(token, "***")
        return re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1***", message)

    def _describe_connection_error(self, exc: Exception, server_config: QQServerConfig) -> str:
        """根据实际异常区分连接、握手和鉴权问题，仅显示原因与操作提示。"""
        if isinstance(exc, WSServerHandshakeError):
            if exc.status == 401:
                auth_state = "client.token 已配置但未通过校验" if server_config.token else "当前未配置 client.token"
                reason = (
                    f"鉴权失败（HTTP 401）：{auth_state}；"
                    "请将 client.token 与当前账号的 OneBot 正向 WebSocket accessToken 核对一致"
                )
            elif exc.status == 403:
                reason = "访问被拒绝（HTTP 403）：请检查服务端的访问权限、IP 白名单及 Token 策略"
            elif exc.status == 404:
                reason = "接口不存在（HTTP 404）：请检查连接地址和路径是否指向 OneBot 正向 WebSocket 接口"
            else:
                reason = (
                    f"WebSocket 握手失败（HTTP {exc.status}）："
                    "请确认 OneBot 正向 WebSocket 端口，并检查服务端或反向代理配置"
                )
        elif isinstance(exc, ClientSSLError):
            reason = "TLS 握手或证书校验失败：请检查 ws/wss 协议、服务端证书及系统时间"
        elif isinstance(exc, TimeoutError):
            reason = "连接或通信超时：请检查目标地址、网络连通性、防火墙及服务端是否响应"
        elif isinstance(exc, ClientConnectorError):
            os_error = exc.os_error
            if isinstance(os_error, socket.gaierror):
                reason = "服务器域名解析失败：请检查 client.server 的域名拼写及 DNS 配置"
            elif isinstance(os_error, ConnectionRefusedError) or os_error.errno in (errno.ECONNREFUSED, 10061):
                return (
                    "目标端口拒绝连接：请确认 SnowLuma/NapCat 已启动并启用 OneBot 正向 WebSocket 服务，"
                    "且 client.server、client.port 与 地址 和 端口 一致"
                )
            else:
                reason = "无法建立网络连接：请检查目标地址、网络路由及防火墙"
        else:
            reason = "连接或通信发生异常：请检查服务端运行状态及日志"

        return reason

    def _build_missing_token_hint(self, server_config: QQServerConfig) -> str:
        """构造缺失 token 时的附加提示。

        Args:
            server_config: 当前生效的 对端服务端配置。

        Returns:
            str: 缺失 token 时的提示文案；无需提示时返回空字符串。
        """
        if server_config.token:
            return ""
        return "；当前未配置 client.token，若服务端开启了访问令牌校验，请补全 token"

    def _build_reconnect_hint(self, server_config: QQServerConfig) -> str:
        """构造连接结束后的重连提示。

        Args:
            server_config: 当前生效的 对端服务端配置。

        Returns:
            str: 自动重连提示；当停止请求已发出时返回空字符串。
        """
        if self._stop_requested:
            return ""
        return f"；将在 {self._next_reconnect_delay(server_config):g} 秒后重连"

    def _describe_terminal_ws_message(
        self,
        ws: AiohttpClientWebSocketResponse,
        ws_message: Any,
        message_label: str,
    ) -> str:
        """描述导致连接结束的终止类 WebSocket 消息。

        Args:
            ws: 当前活跃的 WebSocket 连接对象。
            ws_message: aiohttp 返回的终止消息。
            message_label: 当前终止消息的人类可读标签。

        Returns:
            str: 汇总后的终止原因描述。
        """
        details = []
        close_code = getattr(ws, "close_code", None)
        if close_code not in (None, 0):
            details.append(f"close_code={close_code}")

        message_data = getattr(ws_message, "data", None)
        if message_data not in (None, "", 0, close_code):
            details.append(f"data={message_data}")

        message_extra = str(getattr(ws_message, "extra", "") or "").strip()
        if message_extra:
            details.append(f"extra={message_extra}")

        ws_exception = ws.exception()
        if ws_exception is not None:
            details.append(f"exception={ws_exception}")

        if not details:
            return message_label
        return f"{message_label}（{', '.join(str(item) for item in details)}）"

    def _parse_json_message(self, data: Any) -> Optional[Dict[str, Any]]:
        """解析 WebSocket 文本消息中的 JSON 数据。

        Args:
            data: WebSocket 收到的原始文本数据。

        Returns:
            Optional[Dict[str, Any]]: 成功时返回字典，失败时返回 ``None``。
        """
        try:
            payload = json.loads(str(data))
        except Exception as exc:
            self._logger.warning(f"SnowLuma 适配器解析 JSON 载荷失败: {exc}")
            return None

        return payload if isinstance(payload, dict) else None
