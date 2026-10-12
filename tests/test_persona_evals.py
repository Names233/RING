import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "persona" / "cases.jsonl"
VALID_EMOTIONS = {"neutral", "happy", "excited", "sad", "angry", "thinking", "shy", "sleepy"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_persona_cases_are_valid():
    cases = load_jsonl(CASES)
    assert len(cases) >= 20

    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "persona case ids must be unique"

    for case in cases:
        message = case["input"]["message"]
        assert message["role"] == "user", case
        assert message["parts"], case
        assert all(part["type"] == "text" and part["text"].strip() for part in message["parts"]), case

        context = case["input"]["group_context"]
        assert context["platform"] in {"qq", "telegram", "discord"}, case
        assert context["conversation_id"], case

        assert case["expected_traits"], case
        assert case["forbidden"] is not None, case


def test_persona_cases_cover_difficulty_levels():
    cases = load_jsonl(CASES)
    difficulties = {case["difficulty"] for case in cases}
    assert {"easy", "medium", "hard"}.issubset(difficulties)


def test_persona_cases_cover_core_scenarios():
    cases = load_jsonl(CASES)
    texts = " ".join(case["input"]["message"]["parts"][0]["text"] for case in cases)
    for scenario in ["累", "好", "梗", "AI", "失恋", "晚安", "谢谢"]:
        assert scenario in texts


def test_judge_prompt_outputs_strict_json():
    prompt = (ROOT / "evals" / "persona" / "judge_prompt.md").read_text(encoding="utf-8")
    assert "严格输出以下 JSON" in prompt
    assert '"scores"' in prompt
    assert '"total"' in prompt
    assert '"violations"' in prompt
    assert "5 分" in prompt
    assert "1 分" in prompt


def test_streaming_design_maps_all_documented_updates():
    design = (ROOT / "docs" / "ACP_STREAMING_DESIGN.md").read_text(encoding="utf-8")
    for update in [
        "agent_message_chunk",
        "agent_thought_chunk",
        "user_message_chunk",
        "tool_call",
        "tool_call_update",
        "plan",
        "usage_update",
        "notice",
        "compaction_update",
    ]:
        assert update in design


def test_streaming_design_has_error_and_trace_semantics():
    design = (ROOT / "docs" / "ACP_STREAMING_DESIGN.md").read_text(encoding="utf-8")
    for term in ["session/cancel", "terminal 一次性", "顺序保持", "langfuse_trace_id", "未知事件忽略"]:
        assert term in design


def test_plan_b_design_has_two_stage_pipeline_and_fallbacks():
    design = (ROOT / "docs" / "PERSONA_PLAN_B_DESIGN.md").read_text(encoding="utf-8")
    for term in [
        "Stage 1: 触发判断",
        "Stage 2: 人格生成",
        "JSON 解析失败",
        "should_reply=false",
        "兜底文案",
        "persona-trigger",
        "persona-chat",
    ]:
        assert term in design
