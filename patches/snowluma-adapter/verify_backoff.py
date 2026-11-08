"""重连指数退避与失败日志节流的独立验证脚本（不依赖 aiohttp）。

用法::

    python verify_backoff.py

脚本加载与本文件同目录的 transport.py（或用 SNOWLUMA_TRANSPORT 指向别处的副本），
用最小桩对象替代 aiohttp 和插件配置模型，
然后断言：

1. 退避序列为 5, 10, 20, 40, 80, 160, 300, 300（base=5，指数封顶 2**6，总上限 300 秒）；
2. 首次失败的日志仍是完整 warning，且「将在 5 秒后重连」文案保持原样；
3. 连续失败在 300 秒窗口内降级为 debug 并计数，窗口外恢复完整 warning；
4. 连接成功把退避阶梯重置回 base，随后重新按阶梯增长（真实 _connection_loop 驱动）。
"""

import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
# 默认验证同目录的 transport.py；可用 SNOWLUMA_TRANSPORT 指向别处的副本。
# 插件目录自带 types.py，会遮蔽标准库 types，因此脚本自身不应放在插件目录内运行。
TRANSPORT_PATH = Path(os.environ.get("SNOWLUMA_TRANSPORT") or (HERE / "transport.py")).resolve()
EXPECTED_DELAYS = [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0]

_checks = 0


def check(condition: bool, message: str) -> None:
    """累计并校验一条断言。"""
    global _checks
    if not condition:
        raise AssertionError(message)
    _checks += 1


class FakeServerConfig:
    """QQServerConfig 的最小替身，只保留 transport 用到的字段。"""

    def __init__(self, reconnect_delay_sec: float = 5.0, token: str = "") -> None:
        self.reconnect_delay_sec = reconnect_delay_sec
        self.token = token
        self.heartbeat_interval = 30.0
        self.action_timeout_sec = 30.0

    def build_ws_url(self) -> str:
        return "ws://127.0.0.1:3001/"


class RecordingLogger:
    """按级别记录日志文本的替身 logger。"""

    def __init__(self, on_warning: Optional[Any] = None) -> None:
        self.records: List[Tuple[str, str]] = []
        self.on_warning = on_warning

    def _handler(self, level: str):
        def record(message: str, *args: Any, **kwargs: Any) -> None:
            self.records.append((level, message))
            if level == "warning" and self.on_warning is not None:
                self.on_warning(message)

        return record

    def __getattr__(self, name: str):
        if name in {"debug", "info", "warning", "error"}:
            return self._handler(name)
        raise AttributeError(name)

    def of(self, level: str) -> List[str]:
        return [message for recorded_level, message in self.records if recorded_level == level]


class FakeClock:
    """可推进的 time.monotonic 替身。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class AsyncioProxy:
    """把 asyncio.sleep 换成记录实现，其余属性透传真实 asyncio。"""

    def __init__(self, sleep_impl) -> None:
        self._sleep_impl = sleep_impl

    async def sleep(self, delay: float) -> None:
        await self._sleep_impl(delay)

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


class FakeWebSocket:
    """立即结束的 WebSocket 替身：不产生任何消息。"""

    closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class FakeWebSocketContext:
    """ws_connect 返回的异步上下文管理器。"""

    def __init__(self) -> None:
        self._ws = FakeWebSocket()

    async def __aenter__(self) -> FakeWebSocket:
        return self._ws

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


def build_client_session(plan: List[str]):
    """按计划产出成功/失败的 ClientSession 替身，每次构造消费一个阶段。"""
    remaining = list(plan)

    class StubClientSession:
        def __init__(self, headers: Any = None, timeout: Any = None) -> None:
            self.headers = headers
            self.timeout = timeout

        async def __aenter__(self):
            stage = remaining.pop(0) if remaining else "fail"
            if stage == "fail":
                raise RuntimeError("模拟连接失败")
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        def ws_connect(self, url: str, heartbeat: Any = None) -> FakeWebSocketContext:
            return FakeWebSocketContext()

    return StubClientSession


def load_transport():
    """以桩包的方式加载被验证的 transport.py。"""
    package_name = "_snowluma_verify"
    package = types.ModuleType(package_name)
    package.__path__ = [str(HERE)]
    sys.modules[package_name] = package

    config_module = types.ModuleType(package_name + ".config")
    config_module.QQServerConfig = FakeServerConfig
    sys.modules[package_name + ".config"] = config_module

    profile_module = types.ModuleType(package_name + ".profile")
    profile_module.ProfileState = type("ProfileState", (), {})
    sys.modules[package_name + ".profile"] = profile_module

    spec = importlib.util.spec_from_file_location(package_name + ".transport", TRANSPORT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    # 未安装 aiohttp 时 transport 只回退 ClientSession 等少数名字，补齐以免 isinstance 抛 NameError。
    for name in ("WSServerHandshakeError", "ClientSSLError", "ClientConnectorError"):
        if not hasattr(module, name):
            setattr(module, name, type(name, (Exception,), {"status": 0, "os_error": None}))
    return module


def make_client(transport, logger: RecordingLogger, server_config: FakeServerConfig):
    """构造一个不发起真实连接的 QQTransportClient。"""

    async def noop() -> None:
        return None

    client = transport.QQTransportClient(logger, noop, noop, noop)
    client.configure(server_config)
    return client


def test_backoff_sequence(transport) -> List[float]:
    """退避公式：随失败次数指数增长，指数与总时长双重封顶。"""
    client = make_client(transport, RecordingLogger(), FakeServerConfig())
    delays = []
    for attempt in range(8):
        client._reconnect_attempt = attempt
        delays.append(client._next_reconnect_delay(client._server_config))
    check(delays == EXPECTED_DELAYS, "退避序列不符: " + repr(delays))

    # 自定义 base：指数封顶 2**6，因此 2.5 * 64 = 160 之后不再增长（远未触及 300 秒上限）。
    alt = FakeServerConfig(reconnect_delay_sec=2.5)
    alt_delays = []
    for attempt in range(8):
        client._reconnect_attempt = attempt
        alt_delays.append(client._next_reconnect_delay(alt))
    check(alt_delays == [2.5, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 160.0], "自定义 base 退避不符: " + repr(alt_delays))

    # 指数封顶后（attempt 远大于 6）不再增长；总上限 300 秒对较大的 base 生效。
    client._reconnect_attempt = 40
    check(client._next_reconnect_delay(alt) == 160.0, "指数封顶失效")
    check(client._next_reconnect_delay(FakeServerConfig(reconnect_delay_sec=200.0)) == 300.0, "300 秒总上限未生效")
    return delays


def test_reconnect_hint(transport) -> None:
    """第一轮提示文案必须保持「将在 5 秒后重连」原文。"""
    client = make_client(transport, RecordingLogger(), FakeServerConfig())
    client._reconnect_attempt = 0
    check(client._build_reconnect_hint(client._server_config) == "；将在 5 秒后重连", "首轮重连提示被改写")
    client._reconnect_attempt = 6
    check(client._build_reconnect_hint(client._server_config) == "；将在 300 秒后重连", "封顶后的提示文案不符")
    client._stop_requested = True
    check(client._build_reconnect_hint(client._server_config) == "", "停止后不应给出重连提示")


def test_failure_log_throttle(transport) -> None:
    """连续失败日志：窗口内降级 debug 计数，窗口外恢复 warning 并汇报省略次数。"""
    logger = RecordingLogger()
    client = make_client(transport, logger, FakeServerConfig())
    clock = FakeClock(1000.0)
    original_time = transport.time
    transport.time = clock
    try:
        client._reconnect_attempt = 0
        client._log_connection_failure("ws://127.0.0.1:3001/", client._server_config, RuntimeError("模拟失败"))
        warnings = logger.of("warning")
        check(len(warnings) == 1, "首次失败必须输出一条 warning")
        check("SnowLuma 适配器连接失败:ws://127.0.0.1:3001/" in warnings[0], "失败日志前缀被改写")
        check("将在 5 秒后重连" in warnings[0], "首次失败日志丢失重连提示")
        check(not logger.of("debug"), "首次失败不应走 debug")

        for attempt, step in ((1, 5.0), (2, 5.0)):
            client._reconnect_attempt = attempt
            clock.advance(step)
            client._log_connection_failure("ws://127.0.0.1:3001/", client._server_config, RuntimeError("模拟失败"))
        check(len(logger.of("warning")) == 1, "窗口内的失败仍然输出了 warning")
        check(len(logger.of("debug")) == 2, "窗口内的失败没有降级为 debug")
        check(client._failure_log_suppressed == 2, "被节流的失败次数统计不准")

        client._reconnect_attempt = 3
        clock.advance(300)
        client._log_connection_failure("ws://127.0.0.1:3001/", client._server_config, RuntimeError("模拟失败"))
        warnings = logger.of("warning")
        check(len(warnings) == 2, "跨过节流窗口后应恢复完整 warning")
        check("此前的 2 次同类失败已省略" in warnings[1], "恢复的 warning 未汇报省略次数")
        check("将在 40 秒后重连" in warnings[1], "跨窗口后的重连提示未体现退避")
        check(client._failure_log_suppressed == 0, "恢复输出后计数未清零")
    finally:
        transport.time = original_time


def run_loop(transport, plan: List[str], iterations: int, start_attempt: int = 0) -> List[float]:
    """用真实 _connection_loop 跑若干轮，返回实际 sleep 的延迟序列。"""
    delays: List[float] = []
    client = make_client(transport, RecordingLogger(), FakeServerConfig())
    client._reconnect_attempt = start_attempt

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= iterations:
            client._stop_requested = True

    original_client_session = transport.ClientSession
    original_client_timeout = transport.ClientTimeout
    original_asyncio = transport.asyncio
    transport.ClientSession = build_client_session(plan)
    transport.ClientTimeout = lambda **kwargs: None
    transport.asyncio = AsyncioProxy(fake_sleep)
    try:
        asyncio.run(client._connection_loop())
    finally:
        transport.ClientSession = original_client_session
        transport.ClientTimeout = original_client_timeout
        transport.asyncio = original_asyncio
    return delays


def test_connection_loop(transport) -> List[float]:
    """端到端：真实 _connection_loop 的 sleep 间隔按退避阶梯增长，并在连接成功后重置。"""
    fail_delays = run_loop(transport, ["fail"] * 5, iterations=5)
    check(fail_delays == [5.0, 10.0, 20.0, 40.0, 80.0], "连续失败的重连间隔不符: " + repr(fail_delays))

    reset_delays = run_loop(transport, ["ok", "fail"], iterations=2, start_attempt=5)
    check(reset_delays == [5.0, 10.0], "连接成功后未重置退避阶梯: " + repr(reset_delays))
    return fail_delays


def test_plugin_test_parity(transport) -> None:
    """复刻 tests/test_transport_errors.py 的关键断言。

    插件自带测试依赖「将在 5 秒后重连」文案与 warning 的单参数调用方式，
    并在失败后通过 logger 的副作用置位停止标志，这里用等价驱动方式核对。
    """

    async def noop() -> None:
        return None

    logger = RecordingLogger()
    client = transport.QQTransportClient(logger, noop, noop, noop)
    # 带 token 以避免「未配置 client.token」的额外 warning，与自带测试的 token 用例一致。
    client.configure(FakeServerConfig(token="t0ken"))

    def stop_after_failure(message: str) -> None:
        if "连接失败:" in message:
            client._stop_requested = True

    logger.on_warning = stop_after_failure
    original_client_session = transport.ClientSession
    original_client_timeout = transport.ClientTimeout
    transport.ClientSession = build_client_session(["fail"])
    transport.ClientTimeout = lambda **kwargs: None
    try:
        asyncio.run(client._connection_loop())
    finally:
        transport.ClientSession = original_client_session
        transport.ClientTimeout = original_client_timeout

    warnings = logger.of("warning")
    check(len(warnings) == 1, "单次失败应只产生一条 warning")
    message = warnings[-1]
    check("；将在 5 秒后重连" in message, "自带测试依赖的「将在 5 秒后重连」文案不再满足")
    check("SnowLuma 适配器连接失败:" in message, "失败日志前缀被改写")
    check("连接或通信发生异常" in message, "通用异常分支的错误描述丢失")
    check(client._stop_requested, "日志副作用置位停止标志后循环未退出")


def main() -> int:
    """依次执行全部验证并打印结果。"""
    if not TRANSPORT_PATH.is_file():
        print("缺少待验证文件: " + str(TRANSPORT_PATH))
        return 1

    transport = load_transport()
    delays = test_backoff_sequence(transport)
    test_reconnect_hint(transport)
    test_failure_log_throttle(transport)
    test_plugin_test_parity(transport)
    loop_delays = test_connection_loop(transport)

    print("base=5s 退避序列: " + ", ".join(format(delay, "g") for delay in delays))
    print("_connection_loop 实际间隔: " + ", ".join(format(delay, "g") for delay in loop_delays))
    print("连接成功后重置为: 5, 10（第二段重新按阶梯增长）")
    print("失败日志节流: 首次完整 warning，300 秒窗口内 debug 计数，跨窗口恢复并汇报省略次数")
    print("OK: 全部 " + str(_checks) + " 项断言通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())