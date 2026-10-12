import pytest

from digital_genesis_acp_bridge.streaming import (
    A2AStreamEvent,
    StreamMapper,
    parse_notification,
)


def make_mapper() -> StreamMapper:
    return StreamMapper(
        task_id="task-1",
        acp_session_id="session-1",
        langfuse_trace_id="lf_01hx",
    )


def update(kind: str, **fields):
    return {"sessionUpdate": kind, **fields}


def test_parse_session_update_notification():
    notification = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "session-1",
            "update": {"sessionUpdate": "plan", "plan": []},
        },
    }
    assert parse_notification(notification) == (
        "session-1",
        "plan",
        {"sessionUpdate": "plan", "plan": []},
    )


@pytest.mark.parametrize(
    "notification",
    [
        {"jsonrpc": "2.0", "method": "session/foo", "params": {}},
        {"jsonrpc": "1.0", "method": "session/update", "params": {}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s"}},
        {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {}}},
    ],
)
def test_parse_notification_ignores_malformed_or_other_methods(notification):
    assert parse_notification(notification) is None


def test_agent_message_chunk_appends_text_and_emits_working():
    mapper = make_mapper()
    events = mapper.handle_update(update("agent_message_chunk", content={"text": "hello "}))
    events += mapper.handle_update(update("agent_message_chunk", content={"text": "world"}))

    assert [e.status for e in events] == ["working", "working"]
    assert [e.message for e in events] == ["hello ", "world"]
    assert mapper.text == "hello world"
    assert events[0].metadata["event_kind"] == "agent_message_chunk"
    assert events[0].metadata["langfuse_trace_id"] == "lf_01hx"


def test_agent_thought_chunk_is_internal_only():
    mapper = make_mapper()
    assert mapper.handle_update(update("agent_thought_chunk", content={"text": "secret"})) == []
    assert [span.event_kind for span in mapper.internal_spans] == ["agent_thought_chunk"]
    assert mapper.text == ""


def test_user_message_chunk_is_not_forwarded():
    mapper = make_mapper()
    assert mapper.handle_update(update("user_message_chunk", content={"text": "echo"})) == []
    assert mapper.internal_spans[0].event_kind == "user_message_chunk"


def test_tool_call_and_update_emit_working_events():
    mapper = make_mapper()
    first = mapper.handle_update(update("tool_call", toolCallId="tc-1", title="run tests"))
    second = mapper.handle_update(update("tool_call_update", toolCallId="tc-1", status="completed"))

    assert first[0].status == second[0].status == "working"
    assert first[0].message == "run tests"
    assert first[0].metadata["tool_call_id"] == "tc-1"
    assert second[0].metadata["event_kind"] == "tool_call_update"
    assert second[0].metadata["tool_status"] == "completed"


def test_plan_is_full_snapshot():
    plan = [{"content": "run pytest", "status": "in-progress"}]
    events = make_mapper().handle_update(update("plan", plan=plan))
    assert events[0].message == "plan updated"
    assert events[0].metadata["plan"] == plan


def test_usage_update_is_internal_only():
    mapper = make_mapper()
    assert mapper.handle_update(update("usage_update", inputTokens=10, outputTokens=3)) == []
    assert mapper.internal_spans[0].data == {
        "sessionUpdate": "usage_update",
        "inputTokens": 10,
        "outputTokens": 3,
    }


def test_notice_info_is_working_and_error_is_input_required():
    mapper = make_mapper()
    info = mapper.handle_update(update("notice", level="info", message="adjusting paths"))
    error = mapper.handle_update(update("notice", level="error", message="need credentials"))

    assert info[0].status == "working"
    assert error[0].status == "input-required"
    assert error[0].message == "need credentials"


def test_compaction_update_is_internal_only():
    mapper = make_mapper()
    assert mapper.handle_update(update("compaction_update", usage={"bytes": 100})) == []
    assert mapper.internal_spans[0].event_kind == "compaction_update"


def test_unknown_update_is_ignored_with_warning():
    mapper = make_mapper()
    assert mapper.handle_update(update("future_update_kind")) == []
    assert mapper.warnings == ["ignored unknown sessionUpdate kind: 'future_update_kind'"]


def test_all_nine_documented_kinds_are_covered():
    documented = {
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
    from digital_genesis_acp_bridge.streaming import KNOWN_UPDATE_KINDS

    assert KNOWN_UPDATE_KINDS == documented


def test_order_is_preserved():
    mapper = make_mapper()
    batch = [
        update("agent_message_chunk", content={"text": "a"}),
        update("tool_call", toolCallId="tc", title="test"),
        update("plan", plan=[]),
        update("notice", level="info", message="ok"),
    ]
    emitted = [event for item in batch for event in mapper.handle_update(item)]
    assert [e.metadata["event_kind"] for e in emitted] == [
        "agent_message_chunk",
        "tool_call",
        "plan",
        "notice",
    ]


def test_terminal_event_is_sent_once_and_closes_stream():
    mapper = make_mapper()
    terminal = mapper.close("completed", "done")
    assert terminal.status == "completed"
    assert terminal.metadata["terminal"] is True
    assert mapper.handle_update(update("agent_message_chunk", content={"text": "late"})) == []

    with pytest.raises(RuntimeError, match="already closed"):
        mapper.close("failed", "double close")


@pytest.mark.parametrize("status", ["working", "input-required"])
def test_close_rejects_non_terminal_status(status):
    with pytest.raises(ValueError, match="terminal status"):
        make_mapper().close(status, "bad")


def test_events_carry_task_and_context_ids():
    events = make_mapper().handle_update(update("tool_call", toolCallId="tc"))
    assert events[0].type == "status-update"
    assert events[0].task_id == "task-1"
    assert events[0].context_id == "session-1"
    assert events[0].metadata["acp_session_id"] == "session-1"


def test_a2a_stream_event_defaults():
    event = A2AStreamEvent()
    assert event.type == "status-update"
    assert event.status == "working"
    assert event.metadata == {}
