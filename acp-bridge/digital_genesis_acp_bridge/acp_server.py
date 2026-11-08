from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, Request
from ring_common.llm_client import AGTClient


def create_acp_server() -> FastAPI:
    app = FastAPI(title="dsh-acp-server", version="0.3.0")
    sessions: dict[str, dict[str, Any]] = {}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "dsh-acp-server",
            "protocolVersion": 1,
            "activeSessions": len(sessions),
        }

    @app.post("/")
    async def jsonrpc_endpoint(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }

        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params", {}) or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {"loadSession": True},
                    "agentInfo": {"name": "dsh-acp-runtime", "version": "0.3.0"},
                },
            }

        if method == "session/new":
            session_id = f"acp-{uuid.uuid4().hex[:12]}"
            sessions[session_id] = {"status": "active"}
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"sessionId": session_id},
            }

        if method == "session/cancel":
            session_id = params.get("sessionId")
            if session_id and session_id in sessions:
                sessions[session_id]["status"] = "cancelled"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"cancelled": True},
            }

        if method == "session/prompt":
            prompt_input = params.get("prompt", [])
            if isinstance(prompt_input, list):
                prompt_texts = []
                for item in prompt_input:
                    if isinstance(item, dict):
                        prompt_texts.append(str(item.get("text", "")))
                    elif isinstance(item, str):
                        prompt_texts.append(item)
                prompt_text = " ".join(t for t in prompt_texts if t).strip()
            elif isinstance(prompt_input, str):
                prompt_text = prompt_input.strip()
            else:
                prompt_text = str(prompt_input).strip()

            reply_text = f"[ACP Executed] {prompt_text}"
            try:
                client = AGTClient.from_env()
                if client.is_configured():
                    resp = await asyncio.to_thread(
                        client.chat_completion,
                        [
                            {
                                "role": "system",
                                "content": "You are the dsh headless execution runtime over ACP. Provide a concise technical execution result (under 150 words).",
                            },
                            {"role": "user", "content": prompt_text},
                        ],
                        temperature=0.2,
                        max_tokens=512,
                    )
                    if resp:
                        reply_text = resp
            except Exception:
                pass

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "stopReason": "end_turn",
                    "output": reply_text,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    return app


app = create_acp_server()
