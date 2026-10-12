"""Tests for the Persona Provider Plan B A2A HTTP Service."""

import pytest
from fastapi.testclient import TestClient

from persona_plan_b.service import create_app

SAMPLE_VALID_REQUEST = {
    "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "今天好累啊"}],
    },
    "group_context": {
        "platform": "qq",
        "conversation_id": "group:123",
        "at_me": False,
    },
    "recalled_memory": {
        "fragments": [
            {
                "uri": "viking://memories/users/names/preferences.md",
                "summary": "用户偏好简洁",
                "level": "L1",
            }
        ]
    },
}


def test_health_endpoint():
    client = TestClient(create_app())
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {
        "status": "ok",
        "provider": "persona-plan-b",
        "version": "0.1.0",
    }


def test_direct_contract_request_reply_true():
    app = create_app(
        trigger_model=lambda _: '{"should_reply": true, "emotion": "happy"}',
        chat_model=lambda _: "在呢，辛苦啦～",
    )
    client = TestClient(app)
    res = client.post("/", json=SAMPLE_VALID_REQUEST)
    assert res.status_code == 200
    data = res.json()
    assert data["should_reply"] is True
    assert data["text"] == "在呢，辛苦啦～"
    assert data["emotion"] == "happy"


def test_direct_contract_request_reply_false_p1_invariant():
    app = create_app(
        trigger_model=lambda _: '{"should_reply": false, "emotion": "neutral"}',
        chat_model=lambda _: "这条应该被跳过",
    )
    client = TestClient(app)
    res = client.post("/", json=SAMPLE_VALID_REQUEST)
    assert res.status_code == 200
    data = res.json()
    assert data["should_reply"] is False
    assert data["text"] == ""  # P1 invariant: text must be empty
    assert data["emotion"] == "neutral"


def test_direct_contract_invalid_schema_returns_422():
    client = TestClient(create_app())
    bad_req = {"message": {"role": "agent", "parts": []}}
    res = client.post("/", json=bad_req)
    assert res.status_code == 422


def test_a2a_wrapped_message_send_success():
    app = create_app(
        trigger_model=lambda _: '{"should_reply": true, "emotion": "excited"}',
        chat_model=lambda _: "太棒了！",
    )
    client = TestClient(app)
    a2a_req = {
        "jsonrpc": "2.0",
        "id": "req-999",
        "method": "message/send",
        "params": SAMPLE_VALID_REQUEST,
    }
    res = client.post("/a2a", json=a2a_req)
    assert res.status_code == 200
    data = res.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == "req-999"
    result = data["result"]
    assert result["status"]["state"] == "completed"
    assert result["artifacts"][0]["text"] == "太棒了！"
    meta = result["artifacts"][0]["metadata"]
    assert meta["should_reply"] is True
    assert meta["emotion"] == "excited"


def test_a2a_wrapped_invalid_schema_returns_failed_task():
    client = TestClient(create_app())
    a2a_req = {
        "jsonrpc": "2.0",
        "id": "req-err",
        "method": "message/send",
        "params": {"invalid": "payload"},
    }
    res = client.post("/", json=a2a_req)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "req-err"
    assert data["result"]["status"]["state"] == "failed"
    assert "Schema validation error" in data["result"]["status"]["message"]


def test_chat_model_exception_triggers_fallback():
    def broken_chat(_):
        raise RuntimeError("model timeout")

    app = create_app(
        trigger_model=lambda _: '{"should_reply": true, "emotion": "happy"}',
        chat_model=broken_chat,
    )
    client = TestClient(app)
    res = client.post("/", json=SAMPLE_VALID_REQUEST)
    assert res.status_code == 200
    data = res.json()
    assert data["should_reply"] is True
    assert data["text"] == "我卡住了…"
    assert data["emotion"] == "thinking"
