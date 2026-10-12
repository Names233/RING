"""FastAPI adapter exposing an A2A-compatible message/send endpoint."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from .acp_client import ACPClient, ACPError
from .models import A2AArtifactPart, A2ARequest, A2AResponse, A2AStatus, A2ATask

app = FastAPI(title="Digital Genesis ACP-A2A Bridge", version="0.1.0")


def _build_client() -> ACPClient:
    return ACPClient(
        endpoint=os.getenv("ACP_ENDPOINT", "http://dsh:3080"),
        protocol_version=int(os.getenv("ACP_PROTOCOL_VERSION", "1")),
        cwd=os.getenv("ACP_SESSION_CWD", "/workspace"),
        timeout=float(os.getenv("ACP_TIMEOUT_SECONDS", "300")),
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "acp_endpoint": os.getenv("ACP_ENDPOINT", "http://dsh:3080")}


@app.post("/")
async def a2a_message_send(request: A2ARequest) -> A2AResponse:
    if request.method != "message/send":
        raise HTTPException(status_code=400, detail=f"Unsupported method: {request.method}")

    task_id = str(uuid.uuid4())
    started = time.monotonic()
    client = _build_client()
    try:
        result = await asyncio.wait_for(
            client.run_task(request),
            timeout=float(os.getenv("BRIDGE_TIMEOUT_SECONDS", "3600")),
        )
        status = A2AStatus(state="completed", message="ACP prompt completed")
        artifacts = [A2AArtifactPart(
            text=result["text"] or "ACP execution completed.",
            metadata={
                "acpSessionId": result["session_id"],
                "stopReason": result["stop_reason"],
                "elapsedSeconds": round(time.monotonic() - started, 3),
            },
        )]
    except (ACPError, ValueError) as exc:
        status = A2AStatus(state="failed", message=str(exc))
        artifacts = []
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        status = A2AStatus(state="failed", message=f"ACP transport error: {exc}")
        artifacts = []
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    task = A2ATask(id=task_id, status=status, artifacts=artifacts)
    return A2AResponse(id=request.id, result=task)
