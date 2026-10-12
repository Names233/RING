"""AIRI Embodiment Provider pure-function prototype.

Implements emotion -> Live2D expression / MAGIC motion mapping, degradation
matrix, and A2A wire formatting per docs/AIRI_EMBODIMENT_DESIGN.md.
"""

from .core import (
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

__all__ = [
    "DEFAULT_EMOTION_MAPPINGS",
    "VALID_EMOTIONS",
    "EmbodimentPlan",
    "build_a2a_response",
    "build_emotion_changed_event",
    "build_motion_completed_event",
    "build_motion_failed_event",
    "parse_a2a_request",
    "plan_embodiment",
]
