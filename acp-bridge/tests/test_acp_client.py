import json

import httpx
import pytest

from digital_genesis_acp_bridge.acp_client import ACPClient, ACPError
from digital_genesis_acp_bridge.models import A2ARequest


class ACPHandler(httpx.MockTransport):
    def __init__(self):
        super().__init__(self.handle)
        self.calls: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        self.calls.append(body)
        method = body["method"]

        if method == "initialize":
            result = {"protocolVersion": 1, "agentCapabilities": {}}
        elif method == "session/new":
            result = {"sessionId": "session-123"}
        elif method == "session/cancel":
            assert body["params"] == {"sessionId": "session-123"}
            result = {"ok": True}
        elif method == "session/prompt":
            assert body["params"]["prompt"] == [{"type": "text", "text": "deploy service"}]
            result = {"stopReason": "end_turn"}
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


def make_request(text: str = "deploy service") -> A2ARequest:
    return A2ARequest(
        id=7,
        params={"message": {"role": "user", "parts": [{"type": "text", "text": text}]}},
    )


async def test_run_task_uses_acp_handshake_and_prompt():
    handler = ACPHandler()
    async with httpx.AsyncClient(transport=handler, timeout=5) as http:
        client = ACPClient("http://dsh.test/rpc")
        result = await client.run_task(make_request(), http=http)

    assert result == {
        "session_id": "session-123",
        "stop_reason": "end_turn",
        "text": "",
    }
    assert [call["method"] for call in handler.calls] == [
        "initialize",
        "session/new",
        "session/prompt",
    ]
    assert handler.calls[0]["params"]["protocolVersion"] == 1
    assert handler.calls[1]["params"] == {"cwd": "/workspace", "mcpServers": []}


async def test_run_task_rejects_non_user_role():
    client = ACPClient("http://dsh.test/rpc")
    request = A2ARequest(
        id=1,
        params={"message": {"role": "agent", "parts": [{"type": "text", "text": "x"}]}},
    )
    with pytest.raises(ValueError, match="role=user"):
        await client.run_task(request)


async def test_run_task_requires_text_part():
    client = ACPClient("http://dsh.test/rpc")
    request = A2ARequest(id=1, params={"message": {"role": "user", "parts": []}})
    with pytest.raises(ValueError, match="non-empty text"):
        await client.run_task(request)


async def test_rpc_error_is_wrapped():
    def error_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32000, "message": "boom"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(error_handler), timeout=5) as http:
        client = ACPClient("http://dsh.test/rpc")
        with pytest.raises(ACPError, match="initialize failed"):
            await client.run_task(make_request(), http=http)


async def test_cancel_session_sends_session_cancel():
    handler = ACPHandler()
    async with httpx.AsyncClient(transport=handler, timeout=5) as http:
        client = ACPClient("http://dsh.test/rpc")
        await client.initialize(http)
        await client.new_session(http)
        await client.cancel_session(http, "session-123")

    assert handler.calls[-1]["method"] == "session/cancel"
    assert handler.calls[-1]["params"] == {"sessionId": "session-123"}
