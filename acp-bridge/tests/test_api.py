import json

import httpx
import pytest
from fastapi.testclient import TestClient

from digital_genesis_acp_bridge.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def _mock_acp_success(monkeypatch):
    class FakeClient:
        async def run_task(self, request):
            return {
                "session_id": "session-abc",
                "stop_reason": "end_turn",
                "text": "deployment complete",
            }

    monkeypatch.setattr("digital_genesis_acp_bridge.main._build_client", lambda: FakeClient())


def test_message_send_completes(monkeypatch):
    _mock_acp_success(monkeypatch)
    payload = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "deploy"}]}},
    }
    response = client.post("/", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["result"]["status"]["state"] == "completed"
    assert body["result"]["artifacts"][0]["text"] == "deployment complete"
    assert body["result"]["artifacts"][0]["metadata"]["acpSessionId"] == "session-abc"


def test_message_send_failure_is_task_failure(monkeypatch):
    from digital_genesis_acp_bridge.acp_client import ACPError

    class FailingClient:
        async def run_task(self, request):
            raise ACPError("session/new failed: -1: no capacity")

    monkeypatch.setattr("digital_genesis_acp_bridge.main._build_client", lambda: FailingClient())
    payload = {
        "jsonrpc": "2.0",
        "id": 43,
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "deploy"}]}},
    }
    response = client.post("/", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"]["state"] == "failed"
    assert "no capacity" in body["result"]["status"]["message"]
