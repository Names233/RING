"""Unit tests for the AIRI Embodiment Provider prototype."""

import pytest
from airi_embodiment import (
    DEFAULT_EMOTION_MAPPINGS,
    VALID_EMOTIONS,
    EmbodimentPlan,
    build_a2a_response,
    build_emotion_changed_event,
    build_motion_completed_event,
    build_motion_failed_event,
    parse_a2a_request,
    plan_embodiment,
)


def test_all_eight_emotions_covered_in_mappings():
    assert set(DEFAULT_EMOTION_MAPPINGS.keys()) == VALID_EMOTIONS


@pytest.mark.parametrize(
    ("emotion", "expected_expr", "expected_motion", "expected_speed"),
    [
        ("happy", "smile_open", "happy_wave", 1.1),
        ("excited", "smile_open", "celebrate", 1.2),
        ("sad", "sad_down", "sad_head", 0.9),
        ("angry", "angry_brow", "shake_head", 1.0),
        ("thinking", "eyes_up", "thinking_pose", 0.95),
        ("shy", "blush", "cover_face", 0.9),
        ("sleepy", "eyes_half", "yawn", 0.85),
        ("neutral", "default", "idle", 1.0),
    ],
)
def test_default_emotion_mappings(emotion, expected_expr, expected_motion, expected_speed):
    plan = plan_embodiment(emotion)
    assert plan.emotion == emotion
    assert plan.expression == expected_expr
    assert plan.motion == expected_motion
    assert plan.voice_speed == pytest.approx(expected_speed)
    assert plan.degraded_to == "none"
    assert not plan.warnings


def test_unknown_emotion_falls_back_to_neutral():
    plan = plan_embodiment("confused")
    assert plan.emotion == "neutral"
    assert plan.expression == "default"
    assert plan.motion == "idle"
    assert any("falling back to neutral" in w for w in plan.warnings)


def test_requested_action_overrides_motion():
    plan = plan_embodiment("happy", requested_action="jump_cheer")
    assert plan.expression == "smile_open"
    assert plan.motion == "jump_cheer"


def test_missing_motion_degrades_to_expression_only():
    available_motions = {"idle", "walk"}
    plan = plan_embodiment("happy", available_motions=available_motions)
    assert plan.expression == "smile_open"
    assert plan.motion == "idle"
    assert plan.degraded_to == "expression_only"
    assert any("not available" in w for w in plan.warnings)


def test_missing_expression_degrades_to_idle():
    available_expressions = {"default"}
    available_motions = {"idle", "happy_wave"}
    plan = plan_embodiment(
        "happy",
        available_motions=available_motions,
        available_expressions=available_expressions,
    )
    assert plan.expression == "default"
    assert plan.motion == "idle"
    assert plan.degraded_to == "idle"
    assert any("expression" in w and "not available" in w for w in plan.warnings)


def test_voice_disabled_by_default():
    plan = plan_embodiment("happy")
    assert plan.voice_enabled is False
    assert plan.voice_text == ""


def test_voice_enabled_reads_text():
    plan = plan_embodiment("happy", voice={"enabled": True, "text": "你好呀！"})
    assert plan.voice_enabled is True
    assert plan.voice_text == "你好呀！"


def test_parse_a2a_request():
    req = {
        "jsonrpc": "2.0",
        "id": 101,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "笑一下"}],
            },
            "metadata": {
                "route": "embodiment",
                "emotion": "happy",
                "requested_action": "laugh",
                "voice": {"enabled": True, "text": "嘿嘿"},
                "trace_id": "lf_01hx",
            },
        },
    }
    parsed = parse_a2a_request(req)
    assert parsed["id"] == 101
    assert parsed["text"] == "笑一下"
    assert parsed["emotion"] == "happy"
    assert parsed["requested_action"] == "laugh"
    assert parsed["voice"] == {"enabled": True, "text": "嘿嘿"}
    assert parsed["trace_id"] == "lf_01hx"


def test_build_a2a_response():
    plan = plan_embodiment("happy", voice={"enabled": True, "text": "好呀"})
    resp = build_a2a_response(101, "task-abc", plan, duration_ms=1800)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 101
    result = resp["result"]
    assert result["id"] == "task-abc"
    assert result["status"]["state"] == "completed"
    assert result["artifacts"][0]["metadata"]["motion"] == "happy_wave"
    assert result["artifacts"][0]["metadata"]["expression"] == "smile_open"
    assert result["artifacts"][0]["metadata"]["voice_played"] is True
    assert result["artifacts"][0]["metadata"]["duration_ms"] == 1800


def test_event_serializers_produce_valid_payloads():
    plan = plan_embodiment("excited")
    completed = build_motion_completed_event("lf_trace", "t-1", plan, 2000)
    assert completed["event"] == "embodiment.motion.completed"
    assert completed["trace_id"] == "lf_trace"
    assert completed["motion"] == "celebrate"

    failed = build_motion_failed_event(
        "lf_trace", "t-1", "happy", "dance", "missing_asset", "expression_only"
    )
    assert failed["event"] == "embodiment.motion.failed"
    assert failed["degraded_to"] == "expression_only"

    changed = build_emotion_changed_event(
        "lf_trace", "s-1", "u-1", "neutral", "happy", "user compliment"
    )
    assert changed["event"] == "persona.emotion.changed"
    assert changed["from"] == "neutral"
    assert changed["to"] == "happy"
