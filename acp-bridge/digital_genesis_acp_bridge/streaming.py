"""ACP session/update to A2A stream event mapping.

Implements the mapping specified in docs/ACP_STREAMING_DESIGN.md as pure,
transport-independent logic so it can be unit tested without a real dsh
process. The bridge remains a thin layer: no business decisions, no event
reordering, no caching beyond the minimum required by the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


A2AState = Literal["working", "input-required", "completed", "failed"]

KNOWN_UPDATE_KINDS = frozenset(
    {
        "agent_message_chunk",
        "agent_thought_chunk",
        "user_message_chunk",
        "tool_call",
        "tool_call_update",
        "plan",
        "usage_update",
        "notice",
        "compaction_update",
    }
)


@dataclass(frozen=True)
class A2AStreamEvent:
    """One A2A status-update event emitted by the bridge."""

    type: Literal["status-update"] = "status-update"
    task_id: str = ""
    context_id: str = ""
    status: A2AState = "working"
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InternalSpan:
    """Observability-only event destined for Langfuse, never sent to A2A."""

    event_kind: str
    data: dict[str, Any]


class StreamMapper:
    """Map ACP session/update payloads to A2A stream events.

    The mapper preserves notification order, sends terminal events exactly
    once, and keeps thought/usage events internal (Langfuse spans only).
    """

    def __init__(
        self,
        task_id: str,
        acp_session_id: str,
        langfuse_trace_id: str | None = None,
    ) -> None:
        self.task_id = task_id
        self.acp_session_id = acp_session_id
        self.langfuse_trace_id = langfuse_trace_id
        self.text_buffer: list[str] = []
        self.internal_spans: list[InternalSpan] = []
        self.warnings: list[str] = []
        self._closed = False

    def _event(
        self,
        status: A2AState,
        message: str | None,
        event_kind: str,
        **metadata: Any,
    ) -> A2AStreamEvent:
        base_metadata: dict[str, Any] = {
            "acp_session_id": self.acp_session_id,
            "event_kind": event_kind,
        }
        if self.langfuse_trace_id:
            base_metadata["langfuse_trace_id"] = self.langfuse_trace_id
        base_metadata.update(metadata)
        return A2AStreamEvent(
            task_id=self.task_id,
            context_id=self.acp_session_id,
            status=status,
            message=message,
            metadata=base_metadata,
        )

    def _internal(self, event_kind: str, data: dict[str, Any]) -> None:
        self.internal_spans.append(InternalSpan(event_kind=event_kind, data=data))

    def handle_update(self, update: dict[str, Any]) -> list[A2AStreamEvent]:
        """Handle one ACP update object and return emitted A2A events.

        Unknown update kinds are ignored with a warning, as required by the
        design; they never break the stream.
        """
        if self._closed:
            return []

        kind = str(update.get("sessionUpdate", ""))
        if kind not in KNOWN_UPDATE_KINDS:
            self.warnings.append(f"ignored unknown sessionUpdate kind: {kind!r}")
            return []

        handler = getattr(self, f"_map_{kind}", None)
        if handler is None:
            self.warnings.append(f"no mapper for sessionUpdate kind: {kind!r}")
            return []
        event = handler(update)
        return [] if event is None else [event]

    def close(self, status: A2AState, message: str) -> A2AStreamEvent:
        """Emit the terminal event exactly once and close the stream."""
        if self._closed:
            raise RuntimeError("stream already closed")
        if status not in ("completed", "failed"):
            raise ValueError("terminal status must be completed or failed")
        self._closed = True
        return self._event(status, message, "terminal", terminal=True)

    @property
    def text(self) -> str:
        return "".join(self.text_buffer)

    # Update mappers -----------------------------------------------------

    def _map_agent_message_chunk(self, update: dict[str, Any]) -> A2AStreamEvent:
        content = update.get("content") or {}
        text = str(content.get("text", ""))
        self.text_buffer.append(text)
        return self._event("working", text, "agent_message_chunk")

    def _map_agent_thought_chunk(self, update: dict[str, Any]) -> None:
        # Internal reasoning must never leak to the IM-facing A2A stream.
        self._internal("agent_thought_chunk", dict(update))

    def _map_user_message_chunk(self, update: dict[str, Any]) -> None:
        # Echoed user content is bridge-internal and is not forwarded.
        self._internal("user_message_chunk", dict(update))

    def _map_tool_call(self, update: dict[str, Any]) -> A2AStreamEvent:
        return self._event(
            "working",
            str(update.get("title", update.get("toolCallId", "tool call"))),
            "tool_call",
            tool_call_id=str(update.get("toolCallId", "")),
        )

    def _map_tool_call_update(self, update: dict[str, Any]) -> A2AStreamEvent:
        return self._event(
            "working",
            str(update.get("title", update.get("toolCallId", "tool update"))),
            "tool_call_update",
            tool_call_id=str(update.get("toolCallId", "")),
            tool_status=str(update.get("status", "")),
        )

    def _map_plan(self, update: dict[str, Any]) -> A2AStreamEvent:
        # plan is a full snapshot: consumers replace local state wholesale.
        return self._event("working", "plan updated", "plan", plan=update.get("plan", []))

    def _map_usage_update(self, update: dict[str, Any]) -> None:
        # Cost/token accounting is observability-only.
        self._internal("usage_update", dict(update))

    def _map_notice(self, update: dict[str, Any]) -> A2AStreamEvent:
        level = str(update.get("level", "info")).lower()
        message = str(update.get("message", ""))
        if level == "error":
            return self._event("input-required", message, "notice", notice_level=level)
        return self._event("working", message, "notice", notice_level=level)

    def _map_compaction_update(self, update: dict[str, Any]) -> None:
        # Context compaction does not change the A2A-visible state.
        self._internal("compaction_update", dict(update))


def parse_notification(notification: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    """Parse a JSON-RPC session/update notification.

    Returns ``(session_id, update_kind, update)`` or ``None`` for any other
    notification (or a malformed payload), keeping the bridge resilient.
    """
    if notification.get("jsonrpc") != "2.0" or notification.get("method") != "session/update":
        return None
    params = notification.get("params") or {}
    session_id = str(params.get("sessionId", ""))
    update = params.get("update")
    if not session_id or not isinstance(update, dict):
        return None
    return session_id, str(update.get("sessionUpdate", "")), update
