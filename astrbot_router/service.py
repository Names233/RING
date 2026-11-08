from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ring_common.llm_client import AGTClient
from .core import classify_with_agt, decide_downstream


class HeartbeatRegistry:
    def __init__(self, timeout_seconds: float = 45.0, secret_token: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.secret_token = secret_token
        self.last_heartbeat_ts: float | None = None
        self.last_seq: int = -1
        self.seen_nonces: set[str] = set()
        self.local_status: str = "offline"
        self.capabilities: list[str] = []
        self.endpoints: dict[str, str] = {}
        self.pending_tasks: list[dict[str, Any]] = []

    def record_heartbeat(self, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        if self.secret_token and token != self.secret_token:
            raise PermissionError("invalid heartbeat token")

        nonce = str(payload.get("nonce", "")).strip()
        if not nonce or nonce in self.seen_nonces:
            raise ValueError("invalid or duplicate nonce")

        seq = int(payload.get("seq", 0))
        if seq <= self.last_seq and payload.get("status") != "reset":
            raise ValueError("stale seq")

        self.seen_nonces.add(nonce)
        self.last_seq = seq

        if payload.get("status") == "going_offline":
            self.local_status = "offline"
            self.last_heartbeat_ts = None
        else:
            self.local_status = "online"
            self.last_heartbeat_ts = time.time()
            if "capabilities" in payload and isinstance(payload["capabilities"], list):
                self.capabilities = list(payload["capabilities"])
            if "endpoints" in payload and isinstance(payload["endpoints"], dict):
                self.endpoints = dict(payload["endpoints"])

        return self.get_mode_status(now=time.time())

    def get_mode_status(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        online = (
            self.local_status == "online"
            and self.last_heartbeat_ts is not None
            and (now - self.last_heartbeat_ts) <= self.timeout_seconds
        )
        mode = "FULL_EMBODIMENT" if online else "CLOUD_COMPANION"
        pending_count = len([t for t in self.pending_tasks if t.get("status") == "pending"])
        return {
            "mode": mode,
            "local_online": online,
            "last_heartbeat_ts": self.last_heartbeat_ts,
            "last_seq": self.last_seq,
            "pending_tasks_count": pending_count,
        }


class RouteRequest(BaseModel):
    text: str
    user_id: str = "u_default"
    conversation_id: str = "c_default"
    platform: str = "qq"
    at_me: bool = True
    dispatch: bool = False


class TaskCompleteRequest(BaseModel):
    result: Any = None


def create_app(
    timeout_seconds: float = 45.0,
    secret_token: str | None = None,
    agt_client: AGTClient | None = None,
) -> FastAPI:
    app = FastAPI(title="astrbot-router", version="0.1.0")
    registry = HeartbeatRegistry(timeout_seconds=timeout_seconds, secret_token=secret_token)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "astrbot-router",
            **registry.get_mode_status(),
        }

    @app.post("/heartbeat")
    async def heartbeat(request: Request, x_heartbeat_token: str | None = Header(None, alias="X-Heartbeat-Token")) -> dict[str, Any]:
        token = request.headers.get("X-Heartbeat-Token") or x_heartbeat_token
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            return registry.record_heartbeat(body, token=token)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/mode")
    def mode() -> dict[str, Any]:
        return registry.get_mode_status()

    @app.get("/tasks/pending")
    def tasks_pending() -> dict[str, Any]:
        return {"tasks": [t for t in registry.pending_tasks if t.get("status") == "pending"]}

    @app.post("/tasks/{task_id}/complete")
    async def complete_task(task_id: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        for t in registry.pending_tasks:
            if t.get("task_id") == task_id:
                t["status"] = "completed"
                t["result"] = body.get("result")
                return {"status": "ok", "task": t}
        raise HTTPException(status_code=404, detail="task not found")

    @app.post("/route")
    async def route_endpoint(req: RouteRequest) -> dict[str, Any]:
        decision = await asyncio.to_thread(classify_with_agt, req.text, agt_client)
        downstream = decide_downstream(decision)
        mode_info = registry.get_mode_status()
        mode = mode_info["mode"]

        if decision.route == "tech" and mode == "CLOUD_COMPANION":
            task = {
                "task_id": str(uuid.uuid4()),
                "text": req.text,
                "user_id": req.user_id,
                "status": "pending",
                "created_at": time.time(),
            }
            registry.pending_tasks.append(task)
            return {
                "route": "tech",
                "downstream": "persona-provider",
                "mode": "CLOUD_COMPANION",
                "degraded_to_companion": True,
                "queued_task_id": task["task_id"],
                "reply_text": "我现在不在电脑旁边，先把这个技术任务记在云端待办里啦，等本地算力上线马上帮你跑～",
                "confidence": decision.confidence,
                "reason": decision.reason,
                "source": decision.source,
            }

        if decision.route == "embodiment" and mode == "CLOUD_COMPANION":
            return {
                "route": "embodiment",
                "downstream": "persona-provider",
                "mode": "CLOUD_COMPANION",
                "degraded_to_companion": True,
                "reply_text": "我现在是云端伴生状态，暂时没办法做动作，不过一直陪着你呢～",
                "confidence": decision.confidence,
                "reason": decision.reason,
                "source": decision.source,
            }

        result: dict[str, Any] = {
            "route": decision.route,
            "downstream": downstream,
            "mode": mode,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "source": decision.source,
        }

        if req.dispatch:
            import httpx

            if decision.route == "chat":
                openviking_url = os.getenv("OPENVIKING_URL", "http://127.0.0.1:18080").rstrip("/")
                memory_fragments: list[dict[str, Any]] = []
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        r = await client.post(
                            f"{openviking_url}/recall",
                            json={
                                "agent_id": "astrbot",
                                "query": req.text,
                                "namespaces": [f"viking://memories/users/{req.user_id}"],
                                "max_level": "L1",
                                "top_k": 3,
                            },
                        )
                        if r.status_code == 200:
                            memory_fragments = [
                                {
                                    "uri": item["uri"],
                                    "summary": item.get("summary") or item.get("content", ""),
                                    "level": item["level"],
                                }
                                for item in r.json().get("fragments", [])
                            ]
                except Exception:
                    memory_fragments = []

                persona_url = os.getenv("PERSONA_PROVIDER_URL", "http://127.0.0.1:18081").rstrip("/") + "/a2a"
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            persona_url,
                            json={
                                "jsonrpc": "2.0",
                                "id": str(uuid.uuid4()),
                                "method": "message/send",
                                "params": {
                                    "message": {
                                        "role": "user",
                                        "parts": [{"type": "text", "text": req.text}],
                                    },
                                    "group_context": {
                                        "platform": req.platform,
                                        "conversation_id": req.conversation_id,
                                        "speaker_id": req.user_id,
                                        "speaker_name": req.user_id,
                                        "recent_messages": [],
                                        "at_me": req.at_me,
                                    },
                                    "recalled_memory": {"fragments": memory_fragments},
                                },
                            },
                        )
                        result["downstream_result"] = resp.json()
                        result["recalled_memory_count"] = len(memory_fragments)
                except Exception as e:
                    result["downstream_result"] = {"error": str(e)}

            elif decision.route == "tech" and mode == "FULL_EMBODIMENT":
                acp_bridge_url = (
                    registry.endpoints.get("acp_bridge")
                    or os.getenv("ACP_BRIDGE_URL", "http://127.0.0.1:18090")
                ).rstrip("/") + "/"
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            acp_bridge_url,
                            json={
                                "jsonrpc": "2.0",
                                "id": str(uuid.uuid4()),
                                "method": "message/send",
                                "params": {
                                    "message": {
                                        "role": "user",
                                        "parts": [{"type": "text", "text": req.text}],
                                    }
                                },
                            },
                        )
                        result["downstream_result"] = resp.json()
                except Exception as e:
                    result["downstream_result"] = {"error": str(e)}

            elif decision.route == "embodiment" and mode == "FULL_EMBODIMENT":
                airi_url = (
                    registry.endpoints.get("airi")
                    or os.getenv("AIRI_EMBODIMENT_URL", "http://127.0.0.1:18092")
                ).rstrip("/") + "/a2a"
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            airi_url,
                            json={
                                "jsonrpc": "2.0",
                                "id": str(uuid.uuid4()),
                                "method": "message/send",
                                "params": {
                                    "emotion": "happy",
                                    "requested_action": req.text,
                                    "message": {
                                        "role": "user",
                                        "parts": [{"type": "text", "text": req.text}],
                                    },
                                },
                            },
                        )
                        result["downstream_result"] = resp.json()
                except Exception as e:
                    result["downstream_result"] = {"error": str(e)}

        return result

    return app


app = create_app()
