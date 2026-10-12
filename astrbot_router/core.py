"""Deterministic routing engine for the AstrBot thin router.

This is the offline/degraded-path implementation of
docs/ASTRBOT_ROUTER_DESIGN.md. The LLM intent classifier (intent-router
through LiteLLM) is the primary path; this module is its deterministic
fallback and CI regression baseline.

Design invariants:

- AstrBot does not execute tasks; it only picks a downstream target.
- Persona consistency beats routing precision: low confidence falls back
  to ``chat``.
- Explicit trigger words outrank model classification and can bypass the
  confidence gate.
- The router itself is stateless and never persists anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Route = Literal["chat", "tech", "embodiment"]

VALID_ROUTES: frozenset[str] = frozenset({"chat", "tech", "embodiment"})
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

EXPLICIT_TECH_TRIGGERS: tuple[str, ...] = (
    "deploy", "build", "fix", "run", "debug", "research",
    "/deploy", "/build", "/fix", "/run", "/debug", "/research",
)

EMBODIMENT_PATTERNS: tuple[tuple[str, float, str], ...] = (
    (r"^(?:请|帮我|给我)?(?:笑|哭|点头|摇头|挥手|鞠躬)(?:一下|一?会儿)?$", 0.95, "直接表演动作指令"),
    (r"(?:换|做个|做一个|来个|来一个|给个|给我)[^，。！？]{0,8}(?:表情|动作|动画|形象)", 0.9, "表现层对象请求"),
    (r"(?:用|以|通过)[^，。！？]{0,8}(?:语音|声音|唱歌|唱)", 0.9, "语音/唱歌请求"),
    (r"(?:表情|动作|动画|形象|跳舞|唱歌)", 0.8, "表现层关键词"),
)

TECH_PATTERNS: tuple[tuple[str, float, str], ...] = (
    (r"(?:部署|上线|发布)[^，。！？]{0,12}(?:服务|应用|项目|环境|版本)", 0.92, "部署动词 + 对象"),
    (r"(?:修|修复|修一下|修个|改|改一下|改个)[^，。！？]{0,12}(?:报错|错误|bug|issue|代码|文件|问题)", 0.92, "修复/修改 + 技术对象"),
    (r"(?:查|看看|查看|看一下)[^，。！？]{0,16}(?:日志|log)", 0.9, "查日志"),
    (r"(?:跑|运行|执行)[^，。！？]{0,12}(?:测试|单测|集成测试|脚本|命令)", 0.9, "运行测试/命令"),
    (r"(?:安装|装|升级|更新|卸载)[^，。！？]{0,16}(?:依赖|包|库|模块|环境)", 0.88, "依赖管理"),
    (r"(?:帮我|替我)[^，。！？]{0,16}(?:看看|查查|检查|分析|研究)[^，。！？]{0,16}(?:仓库|代码|项目|报错|日志)", 0.88, "技术分析请求"),
    (r"(?:代码|仓库|repo|分支|commit|merge|docker|fastapi|api|ci|测试|报错|日志|构建|编译|部署|调试)", 0.82, "技术关键词"),
)

EMOTION_PATTERNS: tuple[tuple[str, float, str], ...] = (
    (r"^(?:早上好|中午好|下午好|晚上好|早安|晚安|你好|hi|hello|嗨)[!！~～\\s]*$", 0.95, "问候"),
    (r"(?:好累|累了|困了|想你了|开心|难过|生气|烦|emo|想哭|抱抱|安慰)", 0.85, "情绪表达"),
    (r"(?:梗|笑话|搞笑|哈哈|笑死|好玩|有趣|可爱)", 0.8, "接梗/闲聊"),
)


@dataclass(frozen=True)
class RoutingDecision:
    route: Route
    confidence: float
    reason: str
    fallback: Route = "chat"
    source: Literal["explicit-trigger", "rules", "model", "default"] = "rules"
    degraded: bool = False


def _match_patterns(text, patterns):
    for pattern, confidence, reason in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return confidence, reason
    return None


def _explicit_trigger(text: str) -> str | None:
    normalized = text.strip().lower()
    for trigger in EXPLICIT_TECH_TRIGGERS:
        if normalized == trigger or normalized.startswith(trigger + " "):
            return trigger
    return None


def rule_classify(text: str) -> RoutingDecision:
    if not text or not text.strip():
        return RoutingDecision(
            route="chat", confidence=0.5,
            reason="empty message falls back to persona", source="default",
        )

    trigger = _explicit_trigger(text)
    if trigger is not None:
        return RoutingDecision(
            route="tech", confidence=1.0,
            reason=f"explicit trigger word: {trigger}",
            source="explicit-trigger",
        )

    embodiment = _match_patterns(text, EMBODIMENT_PATTERNS)
    if embodiment is not None:
        return RoutingDecision(
            route="embodiment", confidence=embodiment[0], reason=embodiment[1],
        )

    tech = _match_patterns(text, TECH_PATTERNS)
    if tech is not None:
        return RoutingDecision(route="tech", confidence=tech[0], reason=tech[1])

    emotion = _match_patterns(text, EMOTION_PATTERNS)
    if emotion is not None:
        return RoutingDecision(route="chat", confidence=emotion[0], reason=emotion[1])

    return RoutingDecision(
        route="chat", confidence=0.5,
        reason="no strong signal; persona fallback", source="default",
    )


def classify(
    text: str,
    model_route: Route | None = None,
    model_confidence: float = 0.0,
    model_reason: str = "",
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> RoutingDecision:
    if model_route is not None and model_route not in VALID_ROUTES:
        raise ValueError(f"invalid model route: {model_route!r}")

    trigger = _explicit_trigger(text)
    if trigger is not None:
        return RoutingDecision(
            route="tech", confidence=1.0,
            reason=f"explicit trigger word: {trigger}",
            source="explicit-trigger",
        )

    if model_route is not None and model_confidence >= confidence_threshold:
        return RoutingDecision(
            route=model_route, confidence=model_confidence,
            reason=model_reason or "model classification", source="model",
        )

    if model_route is not None:
        return RoutingDecision(
            route="chat", confidence=model_confidence,
            reason=f"model confidence below {confidence_threshold}; persona fallback",
            source="model", degraded=True,
        )

    decision = rule_classify(text)
    return RoutingDecision(
        route=decision.route, confidence=decision.confidence,
        reason=decision.reason, source=decision.source, degraded=True,
    )


def decide_downstream(decision: RoutingDecision) -> str:
    mapping = {
        "chat": "persona-provider",
        "tech": "acp-bridge/dsh",
        "embodiment": "airi",
    }
    return mapping[decision.route]
