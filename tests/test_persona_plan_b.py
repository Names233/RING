from pathlib import Path

import pytest

from persona_plan_b import (
    FALLBACK_EMOTION,
    FALLBACK_TEXT,
    PlanBError,
    build_chat_prompt,
    build_trigger_prompt,
    enforce_length,
    parse_trigger_output,
    run_plan_b,
    validate_response,
)


def make_request(**overrides):
    request = {
        "message": {"role": "user", "parts": [{"type": "text", "text": "今天好累啊"}]},
        "group_context": {
            "platform": "qq",
            "conversation_id": "group:123",
            "at_me": False,
            "recent_messages": ["群友A: 刚部署完"],
        },
        "recalled_memory": {
            "fragments": [
                {
                    "uri": "viking://memories/users/names/preferences.md",
                    "summary": "偏好简洁回复",
                    "level": "L1",
                }
            ]
        },
    }
    request.update(overrides)
    return request


def test_trigger_prompt_contains_rules_and_memory():
    prompt = build_trigger_prompt(make_request())
    assert "是否被 @：否" in prompt
    assert "viking://memories/users/names/preferences.md" in prompt
    assert "输出严格 JSON" in prompt


def test_trigger_prompt_at_me_is_reflected():
    request = make_request()
    request["group_context"]["at_me"] = True
    prompt = build_trigger_prompt(request)
    assert "是否被 @：是" in prompt


def test_parse_trigger_output_accepts_clean_json():
    should_reply, emotion, degraded = parse_trigger_output('{"should_reply": true, "emotion": "happy"}')
    assert (should_reply, emotion, degraded) == (True, "happy", False)


def test_parse_trigger_output_extracts_json_from_wrapped_text():
    should_reply, emotion, degraded = parse_trigger_output("结果：\n```json\n{\"should_reply\":true,\"emotion\":\"shy\"}\n```")
    assert (should_reply, emotion, degraded) == (True, "shy", False)


def test_parse_trigger_output_degrades_on_invalid_json():
    should_reply, emotion, degraded = parse_trigger_output("not-json")
    assert (should_reply, emotion, degraded) == (False, FALLBACK_EMOTION, True)


def test_parse_trigger_output_degrades_on_invalid_enum():
    should_reply, emotion, degraded = parse_trigger_output('{"should_reply":true,"emotion":"curious"}')
    assert (should_reply, emotion, degraded) == (False, FALLBACK_EMOTION, True)


def test_chat_prompt_contains_persona_style_and_emotion():
    prompt = build_chat_prompt(make_request(), "happy", {"tone": "casual", "traits": ["懂梗"]}, max_length=80)
    assert "当前情绪：happy" in prompt
    assert "不超过 80 字" in prompt
    assert "偏好简洁回复" in prompt
    assert "懂梗" in prompt


def test_enforce_length_truncates_and_strips():
    assert enforce_length("  好的  ") == "好的"
    assert enforce_length("一二三四五", 3) == "一二三"


def test_run_plan_b_skips_stage_2_when_no_reply():
    calls = []

    def trigger_model(prompt):
        calls.append(("trigger", prompt))
        return '{"should_reply": false, "emotion": "neutral"}'

    def chat_model(prompt):
        calls.append(("chat", prompt))
        raise AssertionError("Stage 2 must not run")

    response = run_plan_b(make_request(), trigger_model, chat_model)
    assert [name for name, _ in calls] == ["trigger"]
    assert response.as_dict() == {"should_reply": False, "text": "", "emotion": "neutral"}
    validate_response(response)


def test_run_plan_b_parses_and_merges_stage_outputs():
    response = run_plan_b(
        make_request(),
        lambda prompt: '{"should_reply":true,"emotion":"happy"}',
        lambda prompt: " 抱抱，先歇会儿 ",
        trace_id="lf-001",
    )
    assert response.as_dict() == {
        "should_reply": True,
        "text": "抱抱，先歇会儿",
        "emotion": "happy",
        "trace_id": "lf-001",
    }
    validate_response(response)


def test_run_plan_b_trigger_exception_degrades_to_no_reply():
    response = run_plan_b(make_request(), lambda prompt: (_ for _ in ()).throw(RuntimeError("boom")), lambda prompt: "不该被调用")
    assert response.as_dict() == {"should_reply": False, "text": "", "emotion": FALLBACK_EMOTION}
    assert response.degraded is True


def test_run_plan_b_chat_exception_uses_fallback_text():
    response = run_plan_b(
        make_request(),
        lambda prompt: '{"should_reply":true,"emotion":"thinking"}',
        lambda prompt: (_ for _ in ()).throw(RuntimeError("model down")),
    )
    assert response.should_reply is True
    assert response.text == FALLBACK_TEXT
    assert response.emotion == FALLBACK_EMOTION
    assert response.degraded is True
    validate_response(response)


def test_run_plan_b_empty_chat_output_uses_fallback_text():
    response = run_plan_b(
        make_request(),
        lambda prompt: '{"should_reply":true,"emotion":"happy"}',
        lambda prompt: "   ",
    )
    assert response.text == FALLBACK_TEXT


def test_run_plan_b_enforces_length():
    response = run_plan_b(
        make_request(),
        lambda prompt: '{"should_reply":true,"emotion":"happy"}',
        lambda prompt: "一二三四五",
        max_length=3,
    )
    assert response.text == "一二三"


def test_validate_response_rejects_p1_violation():
    with pytest.raises(PlanBError, match="P1"):
        validate_response({"should_reply": False, "text": "不该说话", "emotion": "neutral"})


def test_validate_response_rejects_invalid_emotion():
    with pytest.raises(PlanBError, match="invalid emotion"):
        validate_response({"should_reply": True, "text": "好", "emotion": "curious"})


def test_invalid_memory_uri_is_rejected():
    request = make_request(recalled_memory={"fragments": [{"uri": "http://example.com", "summary": "", "level": "L1"}]})
    with pytest.raises(PlanBError, match="invalid memory uri"):
        build_trigger_prompt(request)


def test_non_user_message_is_rejected():
    request = make_request(message={"role": "agent", "parts": [{"type": "text", "text": "hi"}]})
    with pytest.raises(PlanBError, match="message.role"):
        build_trigger_prompt(request)
