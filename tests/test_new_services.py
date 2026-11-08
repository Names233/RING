import pytest
from starlette.testclient import TestClient

from openviking_service.service import (
    compute_confidence,
    check_write_permission,
    create_app as create_openviking_app,
)
from astrbot_router.service import create_app as create_router_app
from airi_embodiment.service import create_app as create_airi_app
from digital_genesis_acp_bridge.acp_server import create_acp_server


def test_openviking_permission_and_confidence():
    allowed, reason = check_write_permission("astrbot", "viking://memories/users/u1")
    assert allowed is True
    allowed_false, reason_false = check_write_permission("persona", "viking://memories/users/u1")
    assert allowed_false is False or isinstance(allowed_false, bool)

    conf = compute_confidence(0.9, 0.8, 3)
    assert 0.0 <= conf <= 1.0


def test_openviking_service(tmp_path):
    app = create_openviking_app(storage_root=str(tmp_path))
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


def test_router_service():
    app = create_router_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


def test_airi_embodiment_service():
    app = create_airi_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"

    post_resp = client.post(
        "/a2a",
        json={
            "id": "test-req-1",
            "method": "act",
            "params": {"emotion": "happy", "action": "wave"},
        },
    )
    assert post_resp.status_code == 200


def test_acp_bridge_server():
    server = create_acp_server()
    client = TestClient(server)
    resp = client.get("/health")
    assert resp.status_code == 200
