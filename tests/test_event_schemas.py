"""Tests for the Event Bus JSON Schema."""

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "event-bus-events.schema.json"

try:
    import jsonschema
except ImportError:
    jsonschema = None


@pytest.fixture
def validator():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def test_schema_itself_is_valid():
    if jsonschema is None:
        pytest.skip("jsonschema not installed")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    "event_payload",
    [
        {
            "event": "persona.emotion.changed",
            "trace_id": "lf_01",
            "session_id": "group:100",
            "user_id": "u:names",
            "from": "neutral",
            "to": "happy",
            "reason": "good news",
        },
        {
            "event": "persona.response.completed",
            "trace_id": "lf_02",
            "session_id": "group:100",
            "user_id": "u:names",
            "should_reply": True,
            "emotion": "excited",
            "text": "干得漂亮！",
        },
        {
            "event": "embodiment.motion.requested",
            "trace_id": "lf_03",
            "task_id": "task_1",
            "emotion": "happy",
            "requested_action": "wave",
            "voice": {"enabled": True, "text": "你好！"},
            "source": "astrbot",
        },
        {
            "event": "embodiment.motion.completed",
            "trace_id": "lf_04",
            "task_id": "task_1",
            "motion": "happy_wave",
            "expression": "smile_open",
            "duration_ms": 1800,
            "voice_played": True,
        },
        {
            "event": "embodiment.motion.failed",
            "trace_id": "lf_05",
            "task_id": "task_1",
            "requested_action": "fly",
            "emotion": "sad",
            "error": "asset_missing",
            "degraded_to": "expression_only",
        },
        {
            "event": "deploy.completed",
            "trace_id": "lf_06",
            "service": "fastapi-app",
            "url": "http://127.0.0.1:8000",
            "status": "success",
            "elapsed_seconds": 12.5,
        },
        {
            "event": "deploy.failed",
            "trace_id": "lf_07",
            "service": "fastapi-app",
            "status": "failed",
            "error": "port 8000 already in use",
        },
    ],
)
def test_all_seven_events_validate(validator, event_payload):
    validator.validate(event_payload)


def test_invalid_event_kind_fails(validator):
    bad = {
        "event": "unknown.event",
        "trace_id": "lf_01",
    }
    assert not validator.is_valid(bad)


def test_invalid_emotion_fails(validator):
    bad = {
        "event": "persona.emotion.changed",
        "trace_id": "lf_01",
        "session_id": "g:1",
        "user_id": "u:1",
        "from": "happy",
        "to": "super_happy_unknown",  # invalid
    }
    assert not validator.is_valid(bad)


def test_airi_embodiment_serializers_match_schema(validator):
    from airi_embodiment import (
        build_emotion_changed_event,
        build_motion_completed_event,
        build_motion_failed_event,
        plan_embodiment,
    )

    plan = plan_embodiment("excited")
    ev1 = build_motion_completed_event("lf_trace", "t-1", plan, 2000)
    validator.validate(ev1)

    ev2 = build_motion_failed_event(
        "lf_trace", "t-1", "sad", "dance", "missing", "expression_only"
    )
    validator.validate(ev2)

    ev3 = build_emotion_changed_event(
        "lf_trace", "g-1", "u-1", "neutral", "happy", "user praise"
    )
    validator.validate(ev3)
