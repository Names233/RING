"""Pure-function prototype for the two-stage Persona Provider Plan B.

The module intentionally contains no network or model calls. Callers inject
Stage 1 / Stage 2 callables; this module owns prompt assembly, JSON parsing,
degradation, contract invariants, and response validation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

EMOTIONS = {"neutral", "happy", "excited", "sad", "angry", "thinking", "shy", "sleepy"}
FALLBACK_TEXT = "我卡住了…"
FALLBACK_EMOTION = "thinking"


class PlanBError(RuntimeError):
    """Malformed request or unsupported model callback result."""


class TriggerModel(Protocol):
    def __call__(self, prompt: str) -> str: ...


class ChatModel(Protocol):
    def __call__(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class PlanBResponse:
    should_reply: bool
    text: str
    emotion: str
    trace_id: str | None = None
    degraded: bool = False

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "should_reply": self.should_reply,
            "text": self.text,
            "emotion": self.emotion,
        }
        if self.trace_id is not None:
            result["trace_id"] = self.trace_id
        return result


def extract_text(message: dict[str, Any]) -> str:
    if not isinstance(message, dict) or message.get("role") != "user":
        raise PlanBError("message.role must be user")
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise PlanBError("message.parts must be a non-empty list")

    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != "text":
            raise PlanBError("only text parts are supported")
        text = part.get("text")
        if not isinstance(text, str) or not text.strip():
            raise PlanBError("text parts must contain non-empty text")
        texts.append(text.strip())
    return "\n".join(texts)


def normalize_memory_fragments(recalled_memory: dict[str, Any] | None) -> list[dict[str, str]]:
    if recalled_memory is None:
        return []
    fragments = recalled_memory.get("fragments", [])
    if not isinstance(fragments, list):
        raise PlanBError("recalled_memory.fragments must be a list")

    normalized: list[dict[str, str]] = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            raise PlanBError("memory fragment must be an object")
        uri = fragment.get("uri")
        summary = fragment.get("summary", "")
        level = fragment.get("level")
        if not isinstance(uri, str) or not uri.startswith("viking://"):
            raise PlanBError(f"invalid memory uri: {uri!r}")
        if level not in {"L0", "L1", "L2"}:
            raise PlanBError(f"invalid memory level: {level!r}")
        if not isinstance(summary, str):
            raise PlanBError("memory summary must be a string")
        normalized.append({"uri": uri, "summary": summary, "level": level})
    return normalized


def build_trigger_prompt(request: dict[str, Any]) -> str:
    text = extract_text(request.get("message"))
    context = request.get("group_context", {})
    at_me = bool(context.get("at_me", False)) if isinstance(context, dict) else False
    fragments = normalize_memory_fragments(request.get("recalled_memory"))
    memory_lines = "\n".join(
        f"- [{fragment['level']}] {fragment['uri']}: {fragment['summary'] or '(no summary)'}"
        for fragment in fragments
    ) or "- (empty)"

    return f"""你是一个群聊触发判断器。判断数字生命“麦麦”是否应该回复这条消息。

规则：
- 被 @ 时必须回复
- 直接对话时必须回复
- 情感浓度高的消息倾向回复
- 纯技术问题倾向不回复（由路由层处理）
- 群聊闲聊但不相关时倾向不回复
- 拿不准时不回复

用户消息：{text}
是否被 @：{'是' if at_me else '否'}
召回记忆：
{memory_lines}

输出严格 JSON，不要输出其他内容：
{{"should_reply": true, "emotion": "neutral"}}"""


def parse_trigger_output(raw: str) -> tuple[bool, str, bool]:
    """Parse Stage 1 JSON; on any parse failure silently degrade to no reply."""
    if not isinstance(raw, str):
        return False, FALLBACK_EMOTION, True

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return False, FALLBACK_EMOTION, True
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False, FALLBACK_EMOTION, True
    if not isinstance(value, dict):
        return False, FALLBACK_EMOTION, True

    should_reply = value.get("should_reply")
    emotion = value.get("emotion", FALLBACK_EMOTION)
    if not isinstance(should_reply, bool) or emotion not in EMOTIONS:
        return False, FALLBACK_EMOTION, True
    return should_reply, emotion, False


def build_chat_prompt(
    request: dict[str, Any],
    emotion: str,
    speaking_style: dict[str, Any] | None = None,
    max_length: int = 100,
) -> str:
    if emotion not in EMOTIONS:
        raise PlanBError(f"invalid emotion: {emotion!r}")
    if max_length <= 0:
        raise PlanBError("max_length must be positive")

    text = extract_text(request.get("message"))
    context = request.get("group_context", {})
    if not isinstance(context, dict):
        raise PlanBError("group_context must be an object")
    fragments = normalize_memory_fragments(request.get("recalled_memory"))
    style = speaking_style or {}
    traits = "、".join(style.get("traits", [])) if isinstance(style.get("traits", []), list) else str(style.get("traits", ""))
    tone = style.get("tone", "casual")
    recent_messages = context.get("recent_messages", [])
    if not isinstance(recent_messages, list):
        raise PlanBError("recent_messages must be a list")
    recent_lines = "\n".join(str(item) for item in recent_messages) or "- (empty)"
    memory_lines = "\n".join(
        f"- [{fragment['level']}] {fragment['summary'] or fragment['uri']}" for fragment in fragments
    ) or "- (empty)"

    return f"""你是数字生命“麦麦”，保持自然、有温度的群聊人格。

人格设定：
- 语气：{tone}
- 特质：{traits or '自然、懂梗、会犯错'}

群聊上下文：
{recent_lines}

召回记忆：
{memory_lines}

当前情绪：{emotion}

请回复下面这条用户消息。必须遵守：
- 不超过 {max_length} 字
- 不要客服腔，不要格式化回复
- 不要编造事实；不知道就说不知道
- 直接输出现成的回复文本，不要解释

用户消息：{text}"""


def enforce_length(text: str, max_length: int = 100) -> str:
    if max_length <= 0:
        raise PlanBError("max_length must be positive")
    stripped = text.strip()
    if len(stripped) <= max_length:
        return stripped
    return stripped[:max_length]


def run_plan_b(
    request: dict[str, Any],
    trigger_model: TriggerModel,
    chat_model: ChatModel,
    speaking_style: dict[str, Any] | None = None,
    max_length: int = 100,
    trace_id: str | None = None,
) -> PlanBResponse:
    """Run the two-stage pipeline with deterministic degradation rules."""
    if not isinstance(request, dict):
        raise PlanBError("request must be an object")

    prompt = build_trigger_prompt(request)
    try:
        raw_trigger = trigger_model(prompt)
    except Exception:
        return PlanBResponse(False, "", FALLBACK_EMOTION, trace_id, True)

    should_reply, emotion, degraded = parse_trigger_output(raw_trigger)
    if not should_reply:
        return PlanBResponse(False, "", emotion, trace_id, degraded)

    chat_prompt = build_chat_prompt(request, emotion, speaking_style, max_length)
    try:
        raw_reply = chat_model(chat_prompt)
    except Exception:
        return PlanBResponse(True, FALLBACK_TEXT, FALLBACK_EMOTION, trace_id, True)
    if not isinstance(raw_reply, str) or not raw_reply.strip():
        return PlanBResponse(True, FALLBACK_TEXT, FALLBACK_EMOTION, trace_id, True)

    return PlanBResponse(True, enforce_length(raw_reply, max_length), emotion, trace_id, degraded)


def validate_response(response: PlanBResponse | dict[str, Any]) -> None:
    """Validate Plan B output against the frozen persona contract invariants."""
    value = response.as_dict() if isinstance(response, PlanBResponse) else response
    if not isinstance(value, dict):
        raise PlanBError("response must be an object")
    for key in ("should_reply", "text", "emotion"):
        if key not in value:
            raise PlanBError(f"response missing required key: {key}")
    if not isinstance(value["should_reply"], bool):
        raise PlanBError("should_reply must be a boolean")
    if not isinstance(value["text"], str):
        raise PlanBError("text must be a string")
    if value["emotion"] not in EMOTIONS:
        raise PlanBError(f"invalid emotion: {value['emotion']!r}")
    if not value["should_reply"] and value["text"]:
        raise PlanBError("P1 violation: text must be empty when should_reply is false")
    if value.get("trace_id") is not None and not isinstance(value["trace_id"], str):
        raise PlanBError("trace_id must be a string when present")
