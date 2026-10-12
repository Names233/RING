"""Core embodiment mapping logic for AIRI.

Pure-function implementation of emotion-to-expression/motion translation,
graceful degradation when assets are missing, and event payload serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VALID_EMOTIONS: frozenset[str] = frozenset({
    "neutral",
    "happy",
    "excited",
    "sad",
    "angry",
    "thinking",
    "shy",
    "sleepy",
})

DegradedMode = Literal["none", "expression_only", "idle"]


@dataclass(frozen=True)
class EmotionPreset:
    expression: str
    motion: str
    voice_speed: float


DEFAULT_EMOTION_MAPPINGS: dict[str, EmotionPreset] = {
    "happy": EmotionPreset(expression="smile_open", motion="happy_wave", voice_speed=1.1),
    "excited": EmotionPreset(expression="smile_open", motion="celebrate", voice_speed=1.2),
    "sad": EmotionPreset(expression="sad_down", motion="sad_head", voice_speed=0.9),
    "angry": EmotionPreset(expression="angry_brow", motion="shake_head", voice_speed=1.0),
    "thinking": EmotionPreset(expression="eyes_up", motion="thinking_pose", voice_speed=0.95),
    "shy": EmotionPreset(expression="blush", motion="cover_face", voice_speed=0.9),
    "sleepy": EmotionPreset(expression="eyes_half", motion="yawn", voice_speed=0.85),
    "neutral": EmotionPreset(expression="default", motion="idle", voice_speed=1.0),
}


@dataclass(frozen=True)
class EmbodimentPlan:
    """The concrete visual and vocal actions AIRI should execute."""

    emotion: str
    expression: str
    motion: str
    voice_speed: float
    voice_enabled: bool = False
    voice_text: str = ""
    degraded_to: DegradedMode = "none"
    warnings: list[str] = field(default_factory=list)


def plan_embodiment(
    emotion: str,
    requested_action: str | None = None,
    voice: dict[str, Any] | None = None,
    available_motions: set[str] | None = None,
    available_expressions: set[str] | None = None,
    mapping_override: dict[str, EmotionPreset] | None = None,
) -> EmbodimentPlan:
    """Compute embodiment actions with fallback degradation.

    Rules:
    1. Unknown emotion -> fallback to neutral with warning.
    2. requested_action overrides the default motion for that emotion.
    3. If motion is unavailable -> fallback to expression only (degraded_to='expression_only').
    4. If expression is also unavailable -> fallback to idle (degraded_to='idle').
    5. If voice.enabled is False -> voice text is not read.
    """
    warnings: list[str] = []
    mappings = mapping_override or DEFAULT_EMOTION_MAPPINGS

    norm_emotion = emotion.lower().strip() if emotion else "neutral"
    if norm_emotion not in VALID_EMOTIONS:
        warnings.append(f"unknown emotion {norm_emotion!r}, falling back to neutral")
        norm_emotion = "neutral"

    preset = mappings.get(norm_emotion, mappings["neutral"])
    expression = preset.expression
    motion = requested_action.strip() if requested_action and requested_action.strip() else preset.motion
    voice_speed = preset.voice_speed

    degraded_to: DegradedMode = "none"

    # Motion asset availability check
    if available_motions is not None and motion not in available_motions:
        warnings.append(f"motion {motion!r} not available in assets")
        motion = "idle"
        degraded_to = "expression_only"

    # Expression asset availability check
    if available_expressions is not None and expression not in available_expressions:
        warnings.append(f"expression {expression!r} not available in assets")
        expression = "default"
        motion = "idle"
        degraded_to = "idle"

    # Voice config
    v = voice or {}
    voice_enabled = bool(v.get("enabled", False))
    voice_text = str(v.get("text", "")) if voice_enabled else ""

    return EmbodimentPlan(
        emotion=norm_emotion,
        expression=expression,
        motion=motion,
        voice_speed=voice_speed,
        voice_enabled=voice_enabled,
        voice_text=voice_text,
        degraded_to=degraded_to,
        warnings=warnings,
    )


def parse_a2a_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse inbound A2A embodiment message/send request."""
    params = payload.get("params") or {}
    metadata = params.get("metadata") or {}
    message = params.get("message") or {}

    parts = message.get("parts") or []
    text_content = ""
    for part in parts:
        if part.get("type") == "text":
            text_content = part.get("text", "")
            break

    return {
        "id": payload.get("id"),
        "text": text_content,
        "emotion": str(metadata.get("emotion", "neutral")),
        "requested_action": metadata.get("requested_action"),
        "voice": metadata.get("voice"),
        "trace_id": metadata.get("trace_id", ""),
    }


def build_a2a_response(
    request_id: int | str | None,
    task_id: str,
    plan: EmbodimentPlan,
    duration_ms: int = 1500,
) -> dict[str, Any]:
    """Build outbound A2A task response from embodiment plan."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "id": task_id,
            "status": {
                "state": "completed",
                "message": f"played motion {plan.motion}",
            },
            "artifacts": [
                {
                    "type": "text",
                    "text": plan.motion,
                    "metadata": {
                        "motion": plan.motion,
                        "expression": plan.expression,
                        "duration_ms": duration_ms,
                        "voice_played": plan.voice_enabled,
                        "degraded_to": plan.degraded_to,
                    },
                }
            ],
        },
    }


def build_motion_completed_event(
    trace_id: str,
    task_id: str,
    plan: EmbodimentPlan,
    duration_ms: int = 1500,
) -> dict[str, Any]:
    """Serialize embodiment.motion.completed NATS event."""
    return {
        "event": "embodiment.motion.completed",
        "trace_id": trace_id,
        "task_id": task_id,
        "motion": plan.motion,
        "expression": plan.expression,
        "duration_ms": duration_ms,
        "voice_played": plan.voice_enabled,
    }


def build_motion_failed_event(
    trace_id: str,
    task_id: str,
    emotion: str,
    requested_action: str | None,
    error: str,
    degraded_to: DegradedMode,
) -> dict[str, Any]:
    """Serialize embodiment.motion.failed NATS event."""
    return {
        "event": "embodiment.motion.failed",
        "trace_id": trace_id,
        "task_id": task_id,
        "requested_action": requested_action,
        "emotion": emotion,
        "error": error,
        "degraded_to": degraded_to,
    }


def build_emotion_changed_event(
    trace_id: str,
    session_id: str,
    user_id: str,
    from_emotion: str,
    to_emotion: str,
    reason: str,
) -> dict[str, Any]:
    """Serialize persona.emotion.changed NATS event."""
    return {
        "event": "persona.emotion.changed",
        "trace_id": trace_id,
        "session_id": session_id,
        "user_id": user_id,
        "from": from_emotion,
        "to": to_emotion,
        "reason": reason,
    }
