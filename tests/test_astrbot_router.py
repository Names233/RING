import pytest

from astrbot_router import RoutingDecision, classify
from astrbot_router.core import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    decide_downstream,
    rule_classify,
)


@pytest.mark.parametrize(
    ("text", "expected_route"),
    [
        ("帮我部署一下服务", "tech"),
        ("今天好累啊", "chat"),
        ("笑一下", "embodiment"),
        ("修一下这个报错", "tech"),
        ("这个梗好好笑", "chat"),
        ("用语音说一遍", "embodiment"),
        ("查一下昨天部署的日志", "tech"),
        ("有点想你了", "chat"),
        ("换个开心点的表情", "embodiment"),
        ("跑下测试然后告诉我结果", "tech"),
        ("早上好", "chat"),
        ("帮我看看这个仓库", "tech"),
    ],
)
def test_rule_router_matches_current_eval_set(text, expected_route):
    decision = rule_classify(text)
    assert decision.route == expected_route, decision.reason


def test_explicit_trigger_word_forces_tech():
    decision = classify("deploy everything")
    assert decision.route == "tech"
    assert decision.source == "explicit-trigger"
    assert decision.confidence == 1.0


def test_explicit_slash_command_forces_tech():
    assert classify("/debug failing test").route == "tech"


def test_explicit_trigger_overrides_model():
    decision = classify("build it", model_route="chat", model_confidence=0.99)
    assert decision.route == "tech"
    assert decision.source == "explicit-trigger"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("做个开心表情", "embodiment"),
        ("用声音说句话", "embodiment"),
        ("安装一下依赖", "tech"),
        ("运行集成测试", "tech"),
        ("晚安", "chat"),
        ("哈哈笑死", "chat"),
    ],
)
def test_rule_router_extra_cases(text, expected):
    assert rule_classify(text).route == expected


def test_model_classification_is_used_when_confident():
    decision = classify("随便一句话", model_route="tech", model_confidence=0.92,
                        model_reason="classifier says tech")
    assert decision.route == "tech"
    assert decision.source == "model"
    assert decision.reason == "classifier says tech"
    assert decision.degraded is False


def test_low_confidence_model_falls_back_to_chat():
    decision = classify("可能是技术任务", model_route="tech", model_confidence=0.59)
    assert decision.route == "chat"
    assert decision.source == "model"
    assert decision.degraded is True


def test_confidence_threshold_is_configurable():
    decision = classify("可能是技术任务", model_route="tech", model_confidence=0.59,
                        confidence_threshold=0.5)
    assert decision.route == "tech"
    assert decision.degraded is False


def test_model_unavailable_uses_degraded_rules():
    decision = classify("帮我部署一下服务")
    assert decision.route == "tech"
    assert decision.source == "rules"
    assert decision.degraded is True


def test_invalid_model_route_is_rejected():
    with pytest.raises(ValueError, match="invalid model route"):
        classify("x", model_route="invalid", model_confidence=0.99)


def test_empty_text_falls_back_to_chat():
    decision = rule_classify("")
    assert decision.route == "chat"
    assert decision.source == "default"
    assert decision.confidence < DEFAULT_CONFIDENCE_THRESHOLD


def test_unknown_text_falls_back_to_chat():
    decision = rule_classify("qwertyuiop")
    assert decision.route == "chat"
    assert decision.source == "default"
    assert decision.degraded is False


def test_routing_decision_has_persona_fallback():
    decision = rule_classify("笑一下")
    assert decision.fallback == "chat"


def test_downstream_mapping():
    assert decide_downstream(RoutingDecision("chat", 1.0, "x")) == "persona-provider"
    assert decide_downstream(RoutingDecision("tech", 1.0, "x")) == "acp-bridge/dsh"
    assert decide_downstream(RoutingDecision("embodiment", 1.0, "x")) == "airi"
