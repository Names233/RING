"""Wire models for the ACP <-> A2A bridge."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class A2ATextPart(BaseModel):
    """A2A text part, compatible with Google A2A message/send."""

    type: Literal["text"] = "text"
    text: str


class A2AArtifactPart(BaseModel):
    """A2A artifact part used for final bridge output."""

    type: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2AMessage(BaseModel):
    role: Literal["user", "agent"] = "user"
    parts: list[A2ATextPart]


class A2ARequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str
    method: Literal["message/send"] = "message/send"
    params: dict[str, Any] = Field(default_factory=dict)


class A2AStatus(BaseModel):
    state: Literal["submitted", "working", "input-required", "completed", "failed", "canceled"]
    message: str | None = None


class A2ATask(BaseModel):
    id: str
    context_id: str | None = None
    status: A2AStatus
    artifacts: list[A2AArtifactPart] = Field(default_factory=list)


class A2AResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None
    result: A2ATask
