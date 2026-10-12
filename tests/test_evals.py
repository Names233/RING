import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_ROUTES = {"chat", "tech", "embodiment"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_routing_cases_are_valid():
    cases = load_jsonl(ROOT / "evals" / "routing" / "cases.jsonl")
    assert len(cases) >= 12

    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "routing case ids must be unique"

    for case in cases:
        assert case["expected_route"] in VALID_ROUTES, case
        assert case["difficulty"] in VALID_DIFFICULTIES, case
        assert case["text"].strip(), case


def test_routing_cases_cover_all_routes():
    cases = load_jsonl(ROOT / "evals" / "routing" / "cases.jsonl")
    routes = {case["expected_route"] for case in cases}
    assert routes == VALID_ROUTES


def test_eval_design_documents_thresholds():
    design = (ROOT / "docs" / "EVAL_DESIGN.md").read_text(encoding="utf-8")
    for threshold in ["90%", "85%", "0.85", "0.5"]:
        assert threshold in design


def test_router_design_documents_degradation():
    design = (ROOT / "docs" / "ASTRBOT_ROUTER_DESIGN.md").read_text(encoding="utf-8")
    for failure in ["意图模型不可用", "Persona Provider 超时", "ACP bridge 超时", "AIRI 失败", "OpenViking 不可用"]:
        assert failure in design
