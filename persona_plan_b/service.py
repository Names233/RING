"""A2A HTTP Service for Persona Provider Plan B.

Exposes a FastAPI service implementing the A2A message/send contract
defined in docs/PERSONA_PROVIDER_CONTRACT.md and validated against
schemas/persona-provider.schema.json and schemas/persona-provider-response.schema.json.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .core import (
    FALLBACK_EMOTION,
    FALLBACK_TEXT,
    PlanBError,
    PlanBResponse,
    run_plan_b,
    validate_response,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCHEMA_PATH = REPO_ROOT / "schemas" / "persona-provider.schema.json"
RESPONSE_SCHEMA_PATH = REPO_ROOT / "schemas" / "persona-provider-response.schema.json"

try:
    import jsonschema
    _REQ_SCHEMA = json.loads(REQUEST_SCHEMA_PATH.read_text(encoding="utf-8")) if REQUEST_SCHEMA_PATH.is_file() else None
    _RESP_SCHEMA = json.loads(RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8")) if RESPONSE_SCHEMA_PATH.is_file() else None
    _req_validator = jsonschema.Draft202012Validator(_REQ_SCHEMA) if _REQ_SCHEMA else None
    _resp_validator = jsonschema.Draft202012Validator(_RESP_SCHEMA) if _RESP_SCHEMA else None
except Exception:  # pragma: no cover
    _req_validator = None
    _resp_validator = None


def default_trigger_model(prompt: str) -> str:
    """Offline default trigger model used when no external model is provided."""
    lower = prompt.lower()
    if "@" in prompt or "at_me: true" in lower:
        return '{"should_reply": true, "emotion": "happy"}'
    if any(word in prompt for word in ("累", "想你", "好玩", "哈哈", "失恋", "生病")):
        return '{"should_reply": true, "emotion": "sad" if "失恋" in prompt or "累" in prompt else "happy"}'
    return '{"should_reply": false, "emotion": "neutral"}'


def default_chat_model(prompt: str) -> str:
    """Offline default chat generator used when no external model is provided."""
    if "累" in prompt:
        return "抱抱你，辛苦啦，歇会儿吧～"
    if "早上好" in prompt:
        return "早上好呀！今天也要元气满满～"
    return "在呢！随时找我聊呀～"


def create_app(
    trigger_model: Callable[[str], str] | None = None,
    chat_model: Callable[[str], str] | None = None,
    speaking_style: dict[str, Any] | None = None,
    max_length: int = 100,
) -> FastAPI:
    """Create a configured FastAPI application for Persona Provider Plan B."""
    app = FastAPI(title="Digital Genesis Persona Provider Plan B", version="0.1.0")

    app.state.trigger_model = trigger_model or default_trigger_model
    app.state.chat_model = chat_model or default_chat_model
    app.state.speaking_style = speaking_style or {"tone": "casual", "traits": ["自然", "有温度"]}
    app.state.max_length = max_length

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": "persona-plan-b",
            "version": "0.1.0",
        }

    @app.post("/")
    @app.post("/a2a")
    async def handle_request(req_data: dict[str, Any]) -> dict[str, Any]:
        """Handle incoming A2A message/send or raw contract request."""
        # Detect whether the request is wrapped in A2A JSON-RPC 2.0 envelope
        is_a2a = (
            isinstance(req_data, dict)
            and req_data.get("jsonrpc") == "2.0"
            and req_data.get("method") == "message/send"
        )

        request_id = req_data.get("id", str(uuid.uuid4())) if is_a2a else None
        contract_payload = req_data.get("params", req_data) if is_a2a else req_data
        if isinstance(contract_payload, dict) and "recalled_memory" not in contract_payload:
            contract_payload["recalled_memory"] = {"fragments": []}

        # Inbound Schema Validation
        if _req_validator is not None:
            try:
                _req_validator.validate(contract_payload)
            except Exception as exc:
                if is_a2a:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "id": str(uuid.uuid4()),
                            "status": {"state": "failed", "message": f"Schema validation error: {exc}"},
                            "artifacts": [],
                        },
                    }
                raise HTTPException(status_code=422, detail=f"Request schema error: {exc}") from exc

        # Execute Plan B pipeline
        trace_id = contract_payload.get("trace_id")
        try:
            plan_b_resp: PlanBResponse = run_plan_b(
                request=contract_payload,
                trigger_model=app.state.trigger_model,
                chat_model=app.state.chat_model,
                speaking_style=app.state.speaking_style,
                max_length=app.state.max_length,
                trace_id=trace_id,
            )
        except Exception as exc:
            plan_b_resp = PlanBResponse(
                should_reply=True,
                text=FALLBACK_TEXT,
                emotion=FALLBACK_EMOTION,
                trace_id=trace_id,
                degraded=True,
            )

        resp_dict = plan_b_resp.as_dict()

        # Validate against Persona Provider Response Schema & Contract Invariants
        validate_response(resp_dict)
        if _resp_validator is not None:
            _resp_validator.validate(resp_dict)

        if not is_a2a:
            return resp_dict

        # Format A2A Task Response
        task_id = str(uuid.uuid4())
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "id": task_id,
                "status": {
                    "state": "completed",
                    "message": "persona response generated",
                },
                "artifacts": [
                    {
                        "type": "text",
                        "text": plan_b_resp.text,
                        "metadata": {
                            "should_reply": plan_b_resp.should_reply,
                            "emotion": plan_b_resp.emotion,
                            "degraded": plan_b_resp.degraded,
                            "trace_id": plan_b_resp.trace_id,
                        },
                    }
                ],
            },
        }

    return app


# Default app instance
app = create_app()
