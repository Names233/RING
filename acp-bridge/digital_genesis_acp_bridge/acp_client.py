"""Minimal ACP JSON-RPC client."""

from __future__ import annotations

import itertools
from typing import Any

import httpx

from .models import A2ARequest


class ACPError(RuntimeError):
    """Raised when an ACP JSON-RPC call returns an error."""


class ACPClient:
    """HTTP JSON-RPC client for Agent Client Protocol v1."""

    _ids = itertools.count(1)

    def __init__(
        self,
        endpoint: str,
        protocol_version: int = 1,
        cwd: str = "/workspace",
        timeout: float = 300.0,
    ) -> None:
        self.endpoint = endpoint
        self.protocol_version = protocol_version
        self.cwd = cwd
        self.timeout = timeout

    async def _call(self, client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> Any:
        request_id = next(self._ids)
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        response = await client.post(self.endpoint, json=payload)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            error = body["error"]
            raise ACPError(f"{method} failed: {error.get('code')}: {error.get('message')}")
        return body.get("result")

    async def initialize(self, http: httpx.AsyncClient) -> dict[str, Any]:
        return await self._call(
            http,
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                    "elicitation": {},
                },
                "clientInfo": {"name": "digital-genesis-acp-bridge", "version": "0.1.0"},
            },
        )

    async def new_session(self, http: httpx.AsyncClient) -> str:
        result = await self._call(http, "session/new", {"cwd": self.cwd, "mcpServers": []})
        session_id = result.get("sessionId")
        if not session_id:
            raise ACPError("session/new did not return sessionId")
        return str(session_id)

    async def cancel_session(self, http: httpx.AsyncClient, session_id: str) -> None:
        """Best-effort session/cancel used when the A2A client disconnects."""
        await self._call(http, "session/cancel", {"sessionId": session_id})

    async def prompt(
        self,
        http: httpx.AsyncClient,
        session_id: str,
        message: str,
    ) -> dict[str, Any]:
        # ACP requires ContentBlock::Text for all agents.
        prompt = [{"type": "text", "text": message}]
        return await self._call(
            http,
            "session/prompt",
            {"sessionId": session_id, "prompt": prompt},
        )

    async def run_task(self, request: A2ARequest, http: httpx.AsyncClient | None = None) -> dict[str, Any]:
        """Run one A2A message as a fresh ACP session and return bridge result."""
        message = request.params.get("message") or {}
        if message.get("role", "user") != "user":
            raise ValueError("Only role=user messages are supported")
        parts = message.get("parts") or []
        texts = [part.get("text") for part in parts if part.get("type") == "text"]
        if not texts or not all(texts):
            raise ValueError("A2A message must contain at least one non-empty text part")

        own_client = http is None
        if own_client:
            http = httpx.AsyncClient(timeout=self.timeout)
        assert http is not None
        try:
            await self.initialize(http)
            session_id = await self.new_session(http)
            result = await self.prompt(http, session_id, "\n\n".join(str(t) for t in texts))
            return {
                "session_id": session_id,
                "stop_reason": result.get("stopReason", "end_turn"),
                "text": str(request.params.get("text", "")),
            }
        finally:
            if own_client:
                await http.aclose()
