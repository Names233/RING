import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_evals.py"
sys.path.insert(0, str(ROOT / "scripts"))
import run_evals  # noqa: E402


def run_runner(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_routing_baseline_report_meets_thresholds():
    result = run_runner(["routing", "--baseline", "--format", "json"])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["case_count"] == 12
    assert report["accuracy"] >= 0.90
    assert report["macro_f1"] >= 0.85
    assert report["chat_to_tech_rate"] <= 0.05


def test_routing_markdown_report_contains_gate():
    result = run_runner(["routing", "--baseline"])
    assert result.returncode == 0, result.stderr
    assert "# Routing eval report" in result.stdout
    assert "all thresholds passed" in result.stdout


def test_routing_threshold_gate_exits_nonzero(tmp_path: Path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps({"id": "r1", "text": "今天好累啊", "expected_route": "chat"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    predictions_path = tmp_path / "predictions.jsonl"
    predictions_path.write_text(json.dumps({"id": "r1", "route": "tech"}) + "\n", encoding="utf-8")

    result = run_runner(
        ["routing", "--cases", str(cases_path), "--predictions", str(predictions_path), "--enforce-thresholds", "--format", "json"]
    )
    assert result.returncode == 1
    assert "threshold failures:" in result.stderr


def test_memory_metrics_use_first_matching_rank():
    cases = [{"id": "m1", "expected_uris": ["viking://skills/x/"], "expected_level": "L1"}]
    predictions = [
        {
            "id": "m1",
            "retrieved": [
                {"uri": "viking://memories/shared/", "level": "L0"},
                {"uri": "viking://skills/x", "level": "L1"},
            ],
        }
    ]
    report = run_evals.evaluate_memory(cases, predictions)
    assert report["hit_at_1"] == 0.0
    assert report["hit_at_5"] == 1.0
    assert report["mrr"] == 0.5
    assert report["level_match"] == 1.0


def test_memory_rejects_too_many_retrieved_items():
    cases = [{"id": "m1", "expected_uris": ["viking://skills/x/"], "expected_level": "L1"}]
    predictions = [
        {"id": "m1", "retrieved": [{"uri": f"viking://skills/{index}/", "level": "L1"} for index in range(6)]}
    ]
    with pytest.raises(run_evals.EvalError, match="at most 5"):
        run_evals.evaluate_memory(cases, predictions)


def test_persona_rule_checks():
    cases = [
        {
            "id": "p1",
            "forbidden": ["客服腔"],
            "expected_traits": ["warmth"],
        }
    ]
    responses = [
        {"id": "p1", "response": {"should_reply": True, "text": "在呢~", "emotion": "happy"}, "judge_score": 4.5},
        {"id": "p2", "response": {"should_reply": True, "text": "客服腔", "emotion": "happy"}, "judge_score": 4.0},
    ]
    del responses[1]
    report = run_evals.evaluate_persona(cases, responses)
    assert report["rule_violation_rate"] == 0.0
    assert report["average_judge_score"] == 4.5


def test_persona_p1_invariant_failure_is_reported():
    cases = [{"id": "p1", "forbidden": [], "expected_traits": ["warmth"]}]
    responses = [{"id": "p1", "response": {"should_reply": False, "text": "不该说话", "emotion": "neutral"}}]
    report = run_evals.evaluate_persona(cases, responses)
    assert report["rule_violation_rate"] == 1.0
    assert report["invalid"][0]["violations"][0].startswith("P1:")


def test_macro_f1_handles_all_classes():
    assert run_evals.macro_f1(["chat", "tech"], ["chat", "tech"], {"chat", "tech", "embodiment"}) == pytest.approx(2 / 3)


def test_output_file_is_created(tmp_path: Path):
    output = tmp_path / "reports" / "routing.json"
    result = run_runner(["routing", "--baseline", "--format", "json", "--output", str(output)])
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["kind"] == "routing"
